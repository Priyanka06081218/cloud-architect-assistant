# pipeline/constraint_engine.py
#
# Deterministic constraint validation layer.
#
# After the LLM generates an architecture, this module checks whether the
# recommendation actually satisfies the constraints the user stated. This is
# intentionally rule-based, not LLM-based — LLMs can rationalize away
# constraint violations, but a budget cap is a budget cap.
#
# The validator runs after cost estimation so it has access to both the
# architecture (which services were recommended) and the cost (what it adds
# up to). Violations are returned as structured objects and included in the
# API response as a "constraint_violations" field.
#
# Supported constraint types:
#   - budget:       estimated cost exceeds the stated monthly cap
#   - compliance:   required compliance services are missing from the architecture
#   - availability: high-availability services are absent despite an SLA requirement
#   - latency:      caching / low-latency services absent despite a real-time requirement
#   - multi_region: no global routing layer despite a multi-region requirement
#
# Severity levels:
#   - critical: the architecture cannot meet the constraint as-is
#   - high:     the constraint is likely violated; recommend immediate action
#   - medium:   the constraint may be violated depending on configuration

from __future__ import annotations
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from pipeline.cloud_providers import get_provider

log = logging.getLogger(__name__)


@dataclass
class ConstraintViolation:
    constraint_type: str           # budget | compliance | availability | latency | multi_region
    severity: str                  # critical | high | medium
    description: str               # what went wrong
    suggestion: str                # how to fix it
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _all_services(architecture: dict) -> list[str]:
    """Return a flat list of all service names across all layers, lowercased."""
    layers = architecture.get("layers", {})
    services = []
    for layer_svcs in layers.values():
        if isinstance(layer_svcs, list):
            services.extend(s.lower() for s in layer_svcs)
    return services


def _any_match(services: list[str], keywords: list[str]) -> bool:
    return any(kw in svc for svc in services for kw in keywords)


def _check_budget(requirements: dict, cost: dict, provider) -> Optional[ConstraintViolation]:
    cap = requirements.get("budget_cap_usd")
    if not cap:
        return None
    try:
        cap = float(cap)
    except (TypeError, ValueError):
        return None

    estimated = cost.get("total_monthly_usd", 0)
    if estimated <= cap:
        return None

    overage = estimated - cap
    return ConstraintViolation(
        constraint_type="budget",
        severity="critical",
        description=(
            f"Estimated monthly cost (${estimated:,.0f}) exceeds the stated budget "
            f"cap of ${cap:,.0f}/month by ${overage:,.0f}."
        ),
        suggestion=provider.budget_suggestion,
        details={
            "estimated_usd":  estimated,
            "budget_cap_usd": cap,
            "overage_usd":    round(overage, 2),
        },
    )


def _check_compliance(requirements: dict, architecture: dict, provider) -> list[ConstraintViolation]:
    standards = [s.lower() for s in requirements.get("compliance_requirements", [])]
    if not standards:
        return []

    services   = _all_services(architecture)
    violations = []

    for standard in standards:
        rules   = provider.compliance_controls.get(standard, [])
        missing = [r for r in rules if not _any_match(services, [r["keyword"]])]
        if not missing:
            continue

        missing_labels  = [r["label"] for r in missing]
        missing_reasons = "\n".join(f"  - {r['label']}: {r['reason']}" for r in missing)

        violations.append(ConstraintViolation(
            constraint_type="compliance",
            severity="critical",
            description=(
                f"The architecture is missing {len(missing)} service(s) required for "
                f"{standard.upper()} compliance: {', '.join(missing_labels)}."
            ),
            suggestion=f"Add the following to the security or monitoring layer:\n{missing_reasons}",
            details={
                "standard":         standard.upper(),
                "missing_services": missing_labels,
            },
        ))

    return violations


def _check_availability(requirements: dict, architecture: dict, provider) -> Optional[ConstraintViolation]:
    min_avail = requirements.get("min_availability_percent")
    if not min_avail:
        return None
    try:
        min_avail = float(min_avail)
    except (TypeError, ValueError):
        return None

    if min_avail < 99.9:
        return None

    services = _all_services(architecture)

    ha_database   = _any_match(services, provider.ha_database_keywords)
    ha_compute    = _any_match(services, provider.ha_compute_keywords)
    load_balancer = _any_match(services, provider.ha_lb_keywords)

    labels  = provider.ha_missing_labels
    missing = []
    if not ha_database:
        missing.append(labels["db"])
    if not ha_compute:
        missing.append(labels["compute"])
    if not load_balancer:
        missing.append(labels["lb"])

    if not missing:
        return None

    return ConstraintViolation(
        constraint_type="availability",
        severity="high",
        description=(
            f"A {min_avail}% SLA was requested but the architecture may not achieve it. "
            f"Missing: {'; '.join(missing)}."
        ),
        suggestion=provider.ha_suggestion,
        details={
            "required_availability_percent": min_avail,
            "missing_components": missing,
        },
    )


def _check_latency(requirements: dict, architecture: dict, provider) -> Optional[ConstraintViolation]:
    if not requirements.get("requires_realtime"):
        return None

    services = _all_services(architecture)

    has_cache   = _any_match(services, provider.cache_keywords)
    has_cdn     = _any_match(services, provider.cdn_keywords)
    has_fast_db = _any_match(services, provider.fast_db_keywords)

    if has_cache or (has_cdn and has_fast_db):
        return None

    return ConstraintViolation(
        constraint_type="latency",
        severity="high",
        description=(
            "Real-time or low-latency performance was requested, but the architecture "
            "lacks the services typically required to achieve sub-100ms response times at scale."
        ),
        suggestion=provider.latency_suggestion,
        details={},
    )


def _check_multi_region(requirements: dict, architecture: dict, provider) -> Optional[ConstraintViolation]:
    if not requirements.get("requires_multi_region"):
        return None

    services = _all_services(architecture)

    if _any_match(services, provider.multi_region_keywords):
        return None

    return ConstraintViolation(
        constraint_type="multi_region",
        severity="high",
        description=(
            "Multi-region deployment was requested, but the architecture does not "
            "include a global routing or replication layer."
        ),
        suggestion=provider.multi_region_suggestion,
        details={},
    )


def validate_constraints(
    requirements: dict,
    architecture: dict,
    cost: dict,
) -> list[ConstraintViolation]:
    """Run all constraint validators and return a list of violations."""
    cloud    = (requirements.get("cloud_provider") or "aws").lower()
    provider = get_provider(cloud)

    violations: list[ConstraintViolation] = []

    budget_violation = _check_budget(requirements, cost, provider)
    if budget_violation:
        violations.append(budget_violation)

    violations.extend(_check_compliance(requirements, architecture, provider))

    availability_violation = _check_availability(requirements, architecture, provider)
    if availability_violation:
        violations.append(availability_violation)

    latency_violation = _check_latency(requirements, architecture, provider)
    if latency_violation:
        violations.append(latency_violation)

    multi_region_violation = _check_multi_region(requirements, architecture, provider)
    if multi_region_violation:
        violations.append(multi_region_violation)

    if violations:
        log.info(
            f"Constraint engine: {len(violations)} violation(s) — "
            + ", ".join(f"{v.constraint_type}({v.severity})" for v in violations)
        )
    else:
        log.info("Constraint engine: all constraints satisfied")

    return violations


if __name__ == "__main__":
    import json

    reqs_aws = {
        "cloud_provider": "aws",
        "budget_cap_usd": 200.0,
        "compliance_requirements": ["hipaa"],
        "requires_multi_region": True,
        "requires_realtime": True,
        "min_availability_percent": 99.99,
    }
    arch_aws = {
        "layers": {
            "edge": ["Amazon CloudFront"],
            "networking": ["VPC", "AWS Application Load Balancer"],
            "compute": ["AWS Lambda"],
            "database": ["Amazon RDS"],
            "monitoring": ["Amazon CloudWatch"],
            "security": [],
        }
    }

    reqs_gcp = {
        "cloud_provider": "gcp",
        "budget_cap_usd": 500.0,
        "compliance_requirements": ["hipaa"],
        "requires_multi_region": True,
        "requires_realtime": True,
        "min_availability_percent": 99.99,
    }
    arch_gcp = {
        "layers": {
            "edge": ["Cloud CDN"],
            "networking": ["Cloud Load Balancing", "VPC Network"],
            "compute": ["Cloud Run"],
            "database": ["Cloud SQL"],
            "monitoring": ["Cloud Monitoring"],
            "security": [],
        }
    }

    print("=== AWS violations ===")
    results = validate_constraints(reqs_aws, arch_aws, {"total_monthly_usd": 450})
    print(json.dumps([v.to_dict() for v in results], indent=2))

    print("\n=== GCP violations ===")
    results = validate_constraints(reqs_gcp, arch_gcp, {"total_monthly_usd": 600})
    print(json.dumps([v.to_dict() for v in results], indent=2))
