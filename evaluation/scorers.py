# evaluation/scorers.py
#
# Scoring functions for the golden set evaluation.
#
# Scoring dimensions:
#   1. capability_completeness  — required capabilities present? (via ir.classify)
#   2. provider_correctness     — services from the right cloud only?
#   3. forbidden_violations     — no banned services present?
#   4. cost_range               — estimated cost within expected range?
#   5. compliance_coverage      — actual compliance services present? (not just text mention)
#   6. constraint_satisfaction  — constraint engine reports 0 violations?

from __future__ import annotations
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pipeline.ir as ir
from pipeline.cloud_providers import get_provider
from pipeline.constraint_engine import validate_constraints


# ---------------------------------------------------------------------------
# Service extraction
# ---------------------------------------------------------------------------

def extract_services(architecture: dict) -> list[str]:
    """Flatten all services from architecture layers into a single list."""
    layers = architecture.get("layers", {})
    services = []
    for layer_services in layers.values():
        if isinstance(layer_services, list):
            services.extend(layer_services)
    return services


def _service_match(expected: str, actual_services: list[str]) -> bool:
    """Case-insensitive substring match."""
    expected_lower = expected.lower()
    return any(expected_lower in svc.lower() for svc in actual_services)


# ---------------------------------------------------------------------------
# Score 1: Capability completeness
# Uses ir.classify() to map actual services → capability classes, then checks
# whether required_capabilities are covered. Falls back to substring match if
# the scenario has no required_capabilities (backward compatibility).
# ---------------------------------------------------------------------------

def score_capability_completeness(
    required_capabilities: list[str],
    actual_services: list[str],
    expected_services: list[str] | None = None,
) -> dict:
    if not required_capabilities:
        # Legacy fallback: substring match against expected_services
        if not expected_services:
            return {"score": 1.0, "matched": [], "missing": [], "method": "none",
                    "note": "no requirements defined"}
        matched = [s for s in expected_services if _service_match(s, actual_services)]
        missing = [s for s in expected_services if not _service_match(s, actual_services)]
        return {
            "score": len(matched) / len(expected_services),
            "matched": matched,
            "missing": missing,
            "method": "substring",
        }

    # Classify actual services into capabilities
    actual_caps: set[str] = set()
    for svc in actual_services:
        cap = ir.classify(svc)
        if cap:
            actual_caps.add(cap)

    matched = [cap for cap in required_capabilities if cap in actual_caps]
    missing = [cap for cap in required_capabilities if cap not in actual_caps]

    return {
        "score": len(matched) / len(required_capabilities),
        "matched": matched,
        "missing": missing,
        "actual_capabilities": sorted(actual_caps),
        "method": "capability_class",
    }


# ---------------------------------------------------------------------------
# Score 2: Provider correctness
# Flags any service that matches a competing cloud's known service keywords.
# ---------------------------------------------------------------------------

_CLOUD_KEYWORDS: dict[str, list[str]] = {
    "aws": [
        "aws lambda", "amazon lambda", " lambda",
        "amazon dynamodb", "dynamodb",
        "amazon ec2", " ec2 ", "ec2 auto",
        "amazon s3", " s3 ",
        "amazon cloudfront", "cloudfront",
        "amazon elasticache", "elasticache",
        "amazon cloudwatch", "cloudwatch",
        "aws cloudtrail", "cloudtrail",
        "amazon kinesis", " kinesis",
        "amazon sagemaker", "sagemaker",
        "amazon aurora", " aurora",
        "amazon rds", " rds",
        "amazon ecs", " ecs ", "fargate",
        "amazon eks", " eks",
        "amazon api gateway",
        "aws kms", " kms",
        "aws waf",
    ],
    "azure": [
        "azure functions",
        "azure cosmos db", "cosmos db",
        "azure blob storage", "blob storage",
        "azure sql",
        "azure cdn",
        "azure event hubs", "event hub",
        "azure service bus", "service bus",
        "azure monitor",
        "azure openai",
        "azure kubernetes", " aks",
        "azure container apps", "container apps",
        "azure api management", "api management",
        "azure key vault", "key vault",
        "azure front door", "front door",
        "azure machine learning",
        "azure cache for redis",
    ],
    "gcp": [
        "cloud run",
        "cloud functions",
        "firestore",
        "cloud sql",
        "cloud cdn",
        "cloud pub/sub", "pub/sub",
        "google dataflow", "dataflow",
        "cloud monitoring",
        "vertex ai",
        "bigquery",
        "google kubernetes", " gke",
        "cloud storage",
        "memorystore",
        "cloud armor",
        "cloud spanner",
        "cloud endpoints",
    ],
}


def score_provider_correctness(
    cloud_provider: str,
    actual_services: list[str],
) -> dict:
    """Check that no competitor-cloud services appear in the architecture."""
    cloud = cloud_provider.lower()
    competitor_clouds = [c for c in _CLOUD_KEYWORDS if c != cloud]

    services_lower = [s.lower() for s in actual_services]
    violations: list[str] = []

    for comp_cloud in competitor_clouds:
        for kw in _CLOUD_KEYWORDS[comp_cloud]:
            kw_stripped = kw.strip()
            for svc in services_lower:
                if kw_stripped in svc and svc not in [v.split(" (")[0] for v in violations]:
                    violations.append(f"{svc} ({comp_cloud} service)")
                    break

    if not actual_services:
        return {"score": 1.0, "violations": [], "passed": True, "note": "no services to check"}

    score = 1.0 if not violations else max(0.0, 1.0 - len(violations) / len(actual_services))
    return {
        "score": round(score, 3),
        "violations": violations[:10],
        "passed": len(violations) == 0,
    }


# ---------------------------------------------------------------------------
# Score 3: Forbidden service violations (unchanged)
# ---------------------------------------------------------------------------

def score_forbidden_violations(
    forbidden_services: list[str],
    actual_services: list[str],
) -> dict:
    violations = [s for s in forbidden_services if _service_match(s, actual_services)]
    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "violation_count": len(violations),
    }


# ---------------------------------------------------------------------------
# Score 4: Cost range check (unchanged)
# ---------------------------------------------------------------------------

def score_cost_range(
    expected_range: Optional[list],
    actual_cost_usd: Optional[float],
) -> dict:
    if expected_range is None or actual_cost_usd is None:
        return {"passed": None, "actual": actual_cost_usd, "expected_range": expected_range,
                "note": "no range defined or no cost returned"}
    min_cost, max_cost = expected_range
    passed = min_cost <= actual_cost_usd <= max_cost
    return {
        "passed": passed,
        "actual": actual_cost_usd,
        "expected_range": expected_range,
        "note": (
            f"${actual_cost_usd:.0f}/mo is within [{min_cost}, {max_cost}]"
            if passed else
            f"${actual_cost_usd:.0f}/mo is outside [{min_cost}, {max_cost}]"
        ),
    }


# ---------------------------------------------------------------------------
# Score 5: Compliance coverage — actual service presence, not string mention
# Uses provider.compliance_controls (same data the constraint engine uses).
# ---------------------------------------------------------------------------

def score_compliance_coverage(
    required_compliance: list[str],
    cloud_provider: str,
    actual_services: list[str],
) -> dict:
    if not required_compliance:
        return {"score": 1.0, "passed_standards": [], "failed_standards": [],
                "details": {}, "note": "no compliance required"}

    provider = get_provider(cloud_provider.lower())
    services_lower = [s.lower() for s in actual_services]

    passed_standards: list[str] = []
    partial_standards: list[str] = []
    failed_standards: list[str] = []
    details: dict = {}

    for standard in required_compliance:
        # Try several key normalizations
        rules = None
        for key in (standard.lower(), standard.upper(),
                    standard.lower().replace("-", ""),
                    standard.lower().replace("_", "-")):
            rules = provider.compliance_controls.get(key)
            if rules:
                break

        if not rules:
            partial_standards.append(standard)
            details[standard] = {"note": "unknown standard for this provider",
                                  "found": [], "missing": []}
            continue

        found   = [r for r in rules if any(r["keyword"] in svc for svc in services_lower)]
        missing = [r for r in rules if not any(r["keyword"] in svc for svc in services_lower)]
        details[standard] = {
            "found":   [r["label"] for r in found],
            "missing": [r["label"] for r in missing],
        }

        if not missing:
            passed_standards.append(standard)
        elif found:
            partial_standards.append(standard)
        else:
            failed_standards.append(standard)

    total = len(required_compliance)
    score = (
        len(passed_standards) * 1.0 + len(partial_standards) * 0.5
    ) / total if total else 1.0

    return {
        "score":            round(score, 3),
        "passed_standards": passed_standards,
        "partial_standards": partial_standards,
        "failed_standards": failed_standards,
        "details":          details,
    }


# ---------------------------------------------------------------------------
# Score 6: Constraint satisfaction via the deterministic constraint engine
# ---------------------------------------------------------------------------

def _scenario_to_requirements(scenario: dict, cloud_provider: str) -> dict:
    """Convert a golden-set scenario's constraints into the pipeline requirements format."""
    constraints = scenario.get("expected_constraints", {})
    tags = set(scenario.get("tags", []))
    availability = constraints.get("availability")
    return {
        "cloud_provider":           cloud_provider,
        "budget_cap_usd":           constraints.get("budget_usd"),
        "compliance_requirements":  constraints.get("compliance", []),
        "min_availability_percent": availability * 100 if availability else None,
        "requires_realtime":        any(t in tags for t in (
                                        "real-time", "low-latency", "ultra-low-latency")),
        "requires_multi_region":    any(t in tags for t in (
                                        "multi-region", "active-active", "global")),
    }


def score_constraint_satisfaction(
    scenario: dict,
    architecture: dict,
    cost: dict,
    cloud_provider: str,
) -> dict:
    """Run the constraint engine and return fraction of constraint types satisfied."""
    requirements = _scenario_to_requirements(scenario, cloud_provider)
    try:
        violations = validate_constraints(requirements, architecture, cost)
    except Exception as e:
        return {"score": 0.0, "violations": [], "checked": [],
                "satisfied": [], "violated": [], "error": str(e)}

    # Determine which constraint types were actually active
    checked_types: set[str] = set()
    if requirements.get("budget_cap_usd"):
        checked_types.add("budget")
    if requirements.get("compliance_requirements"):
        checked_types.add("compliance")
    if (requirements.get("min_availability_percent") or 0) >= 99.9:
        checked_types.add("availability")
    if requirements.get("requires_realtime"):
        checked_types.add("latency")
    if requirements.get("requires_multi_region"):
        checked_types.add("multi_region")

    if not checked_types:
        return {"score": 1.0, "violations": [], "checked": [],
                "satisfied": [], "violated": [], "note": "no constraints to check"}

    violated_types = {v.constraint_type for v in violations} & checked_types
    satisfied_types = checked_types - violated_types

    return {
        "score":      round(len(satisfied_types) / len(checked_types), 3),
        "checked":    sorted(checked_types),
        "satisfied":  sorted(satisfied_types),
        "violated":   sorted(violated_types),
        "violations": [v.to_dict() for v in violations],
    }


# ---------------------------------------------------------------------------
# Aggregate: score one scenario
# ---------------------------------------------------------------------------

def score_scenario(scenario: dict, pipeline_output: dict, cloud_provider: str = "aws") -> dict:
    """
    Run all scorers against one scenario's pipeline output.
    Returns a dict with per-dimension scores and an overall weighted score.
    """
    if pipeline_output.get("error"):
        return {
            "id":            scenario["id"],
            "error":         pipeline_output["error"],
            "passed":        False,
            "overall_score": 0.0,
        }

    architecture    = pipeline_output.get("architecture", {})
    cost_info       = pipeline_output.get("cost", {})
    actual_services = extract_services(architecture)
    actual_cost     = cost_info.get("total_monthly_usd")
    compliance      = scenario.get("expected_constraints", {}).get("compliance", [])

    completeness     = score_capability_completeness(
        scenario.get("required_capabilities", []),
        actual_services,
        scenario.get("expected_services", []),
    )
    provider_correct = score_provider_correctness(cloud_provider, actual_services)
    forbidden        = score_forbidden_violations(scenario.get("forbidden_services", []), actual_services)
    cost             = score_cost_range(scenario.get("expected_cost_range"), actual_cost)
    compliance_cov   = score_compliance_coverage(compliance, cloud_provider, actual_services)
    constraint_sat   = score_constraint_satisfaction(scenario, architecture, cost_info, cloud_provider)

    # Weighted score — 5 dimensions
    weights = {
        "completeness": 0.30,
        "provider":     0.15,
        "cost":         0.20,
        "compliance":   0.15,
        "constraint":   0.20,
    }

    if cost["passed"] is None:
        # Cost not applicable: redistribute that weight proportionally across the other 4
        w_total = weights["completeness"] + weights["provider"] + weights["compliance"] + weights["constraint"]
        weighted_score = (
            completeness["score"]   * weights["completeness"] / w_total +
            provider_correct["score"] * weights["provider"] / w_total +
            compliance_cov["score"] * weights["compliance"] / w_total +
            constraint_sat["score"] * weights["constraint"] / w_total
        )
    else:
        cost_score = 1.0 if cost["passed"] else 0.0
        weighted_score = (
            completeness["score"]     * weights["completeness"] +
            provider_correct["score"] * weights["provider"] +
            compliance_cov["score"]   * weights["compliance"] +
            constraint_sat["score"]   * weights["constraint"] +
            cost_score                * weights["cost"]
        )

    # Forbidden violations are critical: any violation caps overall score at 0.4
    if not forbidden["passed"]:
        weighted_score = min(weighted_score, 0.4)

    return {
        "id":              scenario["id"],
        "category":        scenario["category"],
        "difficulty":      scenario["difficulty"],
        "actual_services": actual_services,
        "completeness":    completeness,
        "provider_correct": provider_correct,
        "forbidden":       forbidden,
        "cost":            cost,
        "compliance":      compliance_cov,
        "constraint":      constraint_sat,
        "overall_score":   round(weighted_score, 3),
        "passed":          weighted_score >= 0.65 and forbidden["passed"],
    }
