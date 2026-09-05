# pipeline/candidates.py
#
# Generates alternative candidate architectures from the LLM's primary recommendation.
#
# The LLM produces one architecture. This module produces 2-4 variants by swapping
# the primary compute and/or database service for alternatives — container ↔ serverless
# ↔ kubernetes, relational ↔ nosql. Each variant is a full architecture dict that
# the evaluator can score independently.
#
# Swapping rules:
#   compute:  container_compute ↔ serverless_compute ↔ kubernetes
#   database: relational_db ↔ nosql_db (only when the workload is not schema-dependent)
#
# Variants that would be technically inappropriate (e.g., serverless + GPU) are
# filtered out using the same hard-limit logic as the compute rules in generator.py.

from __future__ import annotations
import copy
from pipeline.ir import classify, resolve, extract_capabilities

# Compute capability swap graph: for each type, what are the meaningful alternatives?
_COMPUTE_SWAPS: dict[str, list[str]] = {
    "container_compute":  ["serverless_compute", "kubernetes"],
    "serverless_compute": ["container_compute", "kubernetes"],
    "kubernetes":         ["container_compute"],
    "vm_compute":         ["container_compute", "kubernetes"],
}

# Database capability swaps (conservative — only offer NoSQL alternative when
# the workload doesn't strongly imply relational constraints)
_DB_SWAPS: dict[str, list[str]] = {
    "relational_db": ["nosql_db"],
    "nosql_db":      ["relational_db"],
}

# Workload signals that make NoSQL inappropriate (schema-dependent, joins, ACID)
_RELATIONAL_SIGNALS = [
    "financial", "payment", "banking", "accounting", "erp", "crm",
    "invoice", "transaction ledger", "double-entry", "reporting", "bi ",
    "analytics warehouse", "compliance report",
]

# Workload signals that make Kubernetes overkill (small scale, low complexity)
_NO_K8S_SIGNALS = [
    "static site", "simple api", "prototype", "mvp", "low traffic",
    "hobby", "personal project", "blog",
]


def _swap_service_in_layer(layer_services: list[str], old_cap: str, new_service: str) -> list[str]:
    """Replace the first service matching old_cap with new_service in a layer."""
    result = []
    replaced = False
    for svc in layer_services:
        if not replaced and classify(svc) == old_cap:
            result.append(new_service)
            replaced = True
        else:
            result.append(svc)
    if not replaced:
        result.append(new_service)
    return result


def _apply_swap(architecture: dict, old_cap: str, new_service: str) -> dict:
    """Return a deep-copied architecture with old_cap replaced by new_service."""
    arch = copy.deepcopy(architecture)
    layers = arch.get("layers", {})
    for layer_name, services in layers.items():
        caps = [classify(s) for s in services]
        if old_cap in caps:
            layers[layer_name] = _swap_service_in_layer(services, old_cap, new_service)
            break  # only replace in the first layer where it appears
    return arch


def _serverless_inappropriate(requirements: dict) -> bool:
    combined = (
        requirements.get("raw_query", "") + " " +
        str(requirements.get("workload_type", ""))
    ).lower()
    gpu_signals = ["gpu", "fine-tun", "training", "cuda", "deep learning"]
    long_job    = ["etl", "hours", "nightly batch", "large dataset"]
    return any(t in combined for t in gpu_signals + long_job)


def _k8s_overkill(requirements: dict) -> bool:
    combined = (
        requirements.get("raw_query", "") + " " +
        str(requirements.get("workload_type", ""))
    ).lower()
    return any(t in combined for t in _NO_K8S_SIGNALS)


def _nosql_inappropriate(requirements: dict) -> bool:
    combined = (
        requirements.get("raw_query", "") + " " +
        str(requirements.get("workload_type", ""))
    ).lower()
    return any(t in combined for t in _RELATIONAL_SIGNALS)


def generate_candidates(
    primary_architecture: dict,
    requirements: dict,
) -> list[dict]:
    """Return a list of candidate architectures including the primary.

    Each candidate is a dict:
        {
            "label":        str,   # short description of this variant
            "change":       str,   # what was swapped vs. the primary
            "architecture": dict,  # full architecture dict (layers + reasoning)
            "is_primary":   bool,
        }
    """
    cloud = requirements.get("cloud_provider", "aws").lower()
    caps  = extract_capabilities(primary_architecture)

    # Identify what the primary architecture is using
    primary_compute = next(
        (c for c in ["container_compute", "kubernetes", "serverless_compute", "vm_compute"]
         if c in caps), None
    )
    primary_db = next(
        (c for c in ["relational_db", "nosql_db"] if c in caps), None
    )

    candidates = [
        {
            "label":        "Primary (LLM recommended)",
            "change":       "baseline",
            "architecture": primary_architecture,
            "is_primary":   True,
        }
    ]

    # Compute swaps
    if primary_compute and primary_compute in _COMPUTE_SWAPS:
        for alt_cap in _COMPUTE_SWAPS[primary_compute]:
            if alt_cap == "serverless_compute" and _serverless_inappropriate(requirements):
                continue
            if alt_cap == "kubernetes" and _k8s_overkill(requirements):
                continue
            new_svc = resolve(alt_cap, cloud)
            if not new_svc:
                continue
            alt_arch = _apply_swap(primary_architecture, primary_compute, new_svc)
            label = _label_for_cap(alt_cap)
            candidates.append({
                "label":        f"{label} variant",
                "change":       f"{_label_for_cap(primary_compute)} → {new_svc}",
                "architecture": alt_arch,
                "is_primary":   False,
            })

    # Database swap (only one — relational ↔ nosql)
    if primary_db and primary_db in _DB_SWAPS:
        for alt_db_cap in _DB_SWAPS[primary_db]:
            if alt_db_cap == "nosql_db" and _nosql_inappropriate(requirements):
                continue
            new_svc = resolve(alt_db_cap, cloud)
            if not new_svc:
                continue
            alt_arch = _apply_swap(primary_architecture, primary_db, new_svc)
            db_label = "NoSQL DB" if alt_db_cap == "nosql_db" else "Relational DB"
            candidates.append({
                "label":        f"{db_label} variant",
                "change":       f"database → {new_svc}",
                "architecture": alt_arch,
                "is_primary":   False,
            })

    return candidates[:5]  # cap at 5 to keep evaluation fast


def _label_for_cap(cap: str) -> str:
    return {
        "container_compute":  "Managed container",
        "serverless_compute": "Serverless",
        "kubernetes":         "Kubernetes",
        "vm_compute":         "VM-based",
        "relational_db":      "SQL DB",
        "nosql_db":           "NoSQL DB",
    }.get(cap, cap)
