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

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ConstraintViolation:
    constraint_type: str           # budget | compliance | availability | latency | multi_region
    severity: str                  # critical | high | medium
    description: str               # what went wrong
    suggestion: str                # how to fix it
    details: dict = field(default_factory=dict)  # extra context (e.g. actual vs expected cost)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Service keyword helpers
# ---------------------------------------------------------------------------

def _all_services(architecture: dict) -> list[str]:
    """Return a flat list of all service names across all layers, lowercased."""
    layers = architecture.get("layers", {})
    services = []
    for layer_svcs in layers.values():
        if isinstance(layer_svcs, list):
            services.extend(s.lower() for s in layer_svcs)
    return services


def _any_match(services: list[str], keywords: list[str]) -> bool:
    """Return True if any service name contains any of the keywords."""
    return any(kw in svc for svc in services for kw in keywords)


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def _check_budget(
    requirements: dict,
    cost: dict,
) -> Optional[ConstraintViolation]:
    """Flag if estimated monthly cost exceeds the stated budget cap."""
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
        suggestion=(
            "Consider replacing provisioned compute (ECS, EC2) with serverless "
            "(Lambda, Fargate Spot), switching RDS to Aurora Serverless v2 "
            "(scales to zero when idle), or removing ElastiCache if caching can "
            "be handled in-process. The cost calculator scales with user load, "
            "so also check whether the stated scale is higher than necessary."
        ),
        details={
            "estimated_usd": estimated,
            "budget_cap_usd": cap,
            "overage_usd": round(overage, 2),
        },
    )


# Compliance rules: each standard maps to the services that must be present.
# The check is keyword-based — if any service name in the architecture
# contains the keyword, the requirement is satisfied.
_COMPLIANCE_RULES: dict[str, list[dict]] = {
    "hipaa": [
        {
            "keyword": "kms",
            "label": "AWS KMS",
            "reason": "HIPAA requires encryption of PHI at rest using managed keys.",
        },
        {
            "keyword": "cloudtrail",
            "label": "AWS CloudTrail",
            "reason": "HIPAA requires audit logging of all access to PHI.",
        },
        {
            "keyword": "guardduty",
            "label": "Amazon GuardDuty",
            "reason": "HIPAA expects continuous threat detection for environments storing health data.",
        },
        {
            "keyword": "vpc",
            "label": "VPC with private subnets",
            "reason": "HIPAA requires PHI to be isolated in a private network — not publicly accessible.",
        },
    ],
    "soc2": [
        {
            "keyword": "cloudtrail",
            "label": "AWS CloudTrail",
            "reason": "SOC 2 CC7.2 requires logging of all privileged and user activity.",
        },
        {
            "keyword": "guardduty",
            "label": "Amazon GuardDuty",
            "reason": "SOC 2 CC6.8 requires continuous monitoring for unauthorized access attempts.",
        },
        {
            "keyword": "waf",
            "label": "AWS WAF",
            "reason": "SOC 2 CC6.6 requires protection against common web exploits.",
        },
    ],
    "pci-dss": [
        {
            "keyword": "waf",
            "label": "AWS WAF",
            "reason": "PCI-DSS Requirement 6.6 mandates a WAF in front of all web-facing applications.",
        },
        {
            "keyword": "kms",
            "label": "AWS KMS",
            "reason": "PCI-DSS Requirement 3.4 requires strong encryption for cardholder data at rest.",
        },
        {
            "keyword": "cloudtrail",
            "label": "AWS CloudTrail",
            "reason": "PCI-DSS Requirement 10 mandates audit trails for all access to cardholder data.",
        },
        {
            "keyword": "guardduty",
            "label": "Amazon GuardDuty",
            "reason": "PCI-DSS Requirement 11.4 requires intrusion detection systems.",
        },
        {
            "keyword": "vpc",
            "label": "VPC with private subnets",
            "reason": "PCI-DSS Requirement 1 mandates network segmentation for cardholder data environments.",
        },
    ],
    "gdpr": [
        {
            "keyword": "kms",
            "label": "AWS KMS",
            "reason": "GDPR Article 32 requires encryption of personal data at rest and in transit.",
        },
        {
            "keyword": "cloudtrail",
            "label": "AWS CloudTrail",
            "reason": "GDPR Article 30 requires records of all processing activities.",
        },
    ],
    "fedramp": [
        {
            "keyword": "cloudtrail",
            "label": "AWS CloudTrail",
            "reason": "FedRAMP AU-2 requires comprehensive audit event logging.",
        },
        {
            "keyword": "guardduty",
            "label": "Amazon GuardDuty",
            "reason": "FedRAMP SI-3/SI-4 requires malware and intrusion detection.",
        },
        {
            "keyword": "kms",
            "label": "AWS KMS",
            "reason": "FedRAMP SC-28 requires encryption of data at rest with FIPS 140-2 validated modules.",
        },
        {
            "keyword": "config",
            "label": "AWS Config",
            "reason": "FedRAMP CM-6/CM-7 requires continuous configuration compliance monitoring.",
        },
    ],
}


def _check_compliance(
    requirements: dict,
    architecture: dict,
) -> list[ConstraintViolation]:
    """Flag missing services for each stated compliance standard."""
    standards = [s.lower() for s in requirements.get("compliance_requirements", [])]
    if not standards:
        return []

    services = _all_services(architecture)
    violations = []

    for standard in standards:
        rules = _COMPLIANCE_RULES.get(standard, [])
        missing = [r for r in rules if not _any_match(services, [r["keyword"]])]
        if not missing:
            continue

        missing_labels = [r["label"] for r in missing]
        missing_reasons = "\n".join(f"  - {r['label']}: {r['reason']}" for r in missing)

        violations.append(ConstraintViolation(
            constraint_type="compliance",
            severity="critical",
            description=(
                f"The architecture is missing {len(missing)} service(s) required for "
                f"{standard.upper()} compliance: {', '.join(missing_labels)}."
            ),
            suggestion=(
                f"Add the following to the security or monitoring layer:\n{missing_reasons}"
            ),
            details={
                "standard": standard.upper(),
                "missing_services": missing_labels,
            },
        ))

    return violations


def _check_availability(
    requirements: dict,
    architecture: dict,
) -> Optional[ConstraintViolation]:
    """Flag if a high-availability SLA is required but key HA services are absent."""
    min_avail = requirements.get("min_availability_percent")
    if not min_avail:
        return None

    try:
        min_avail = float(min_avail)
    except (TypeError, ValueError):
        return None

    # Only flag for requirements above 99.9% — single-AZ setups can still reach 99.9%
    if min_avail < 99.9:
        return None

    services = _all_services(architecture)

    # For 99.9%+, we expect multi-AZ database and managed compute
    ha_database = _any_match(services, ["aurora", "rds multi", "dynamodb", "elasticache"])
    ha_compute = _any_match(services, ["ecs", "eks", "fargate", "auto scaling", "lambda"])
    load_balancer = _any_match(services, ["load balancer", "alb", "nlb"])

    missing = []
    if not ha_database:
        missing.append("a Multi-AZ database (Aurora, DynamoDB, or ElastiCache)")
    if not ha_compute:
        missing.append("managed compute with auto-scaling (ECS Fargate, EKS, or Lambda)")
    if not load_balancer:
        missing.append("a load balancer (ALB or NLB) to distribute traffic across AZs")

    if not missing:
        return None

    return ConstraintViolation(
        constraint_type="availability",
        severity="high",
        description=(
            f"A {min_avail}% SLA was requested but the architecture may not achieve it. "
            f"Missing: {'; '.join(missing)}."
        ),
        suggestion=(
            "To reach 99.99%+ availability: use Aurora with Multi-AZ replicas or "
            "DynamoDB (globally distributed by default), place ECS tasks across at "
            "least 3 AZs behind an ALB with health checks, and enable auto-scaling "
            "policies to replace unhealthy instances automatically."
        ),
        details={
            "required_availability_percent": min_avail,
            "missing_components": missing,
        },
    )


def _check_latency(
    requirements: dict,
    architecture: dict,
) -> Optional[ConstraintViolation]:
    """Flag if real-time or low-latency is required but no caching layer is present."""
    if not requirements.get("requires_realtime"):
        return None

    services = _all_services(architecture)

    has_cache = _any_match(services, ["elasticache", "redis", "memcached", "dax"])
    has_cdn = _any_match(services, ["cloudfront", "cdn"])
    has_fast_db = _any_match(services, ["dynamodb", "dax"])

    if has_cache or (has_cdn and has_fast_db):
        return None

    missing = []
    if not has_cache:
        missing.append("ElastiCache (Redis) for in-memory caching")
    if not has_fast_db:
        missing.append("DynamoDB for single-digit millisecond reads at any scale")
    if not has_cdn:
        missing.append("CloudFront to serve static content from edge locations")

    return ConstraintViolation(
        constraint_type="latency",
        severity="high",
        description=(
            "Real-time or low-latency performance was requested, but the architecture "
            "lacks the services typically required to achieve sub-100ms response times "
            "at scale."
        ),
        suggestion=(
            "Add: " + ", ".join(missing) + ". "
            "ElastiCache (Redis) is the most impactful single change — it removes "
            "database round-trips for frequently read data. DynamoDB provides consistent "
            "single-digit millisecond reads regardless of table size."
        ),
        details={"missing_for_low_latency": missing},
    )


def _check_multi_region(
    requirements: dict,
    architecture: dict,
) -> Optional[ConstraintViolation]:
    """Flag if multi-region was requested but no global routing layer is present."""
    if not requirements.get("requires_multi_region"):
        return None

    services = _all_services(architecture)

    has_global_routing = _any_match(services, [
        "route 53", "global accelerator", "cloudfront", "aurora global",
        "dynamodb global", "s3 replication",
    ])

    if has_global_routing:
        return None

    return ConstraintViolation(
        constraint_type="multi_region",
        severity="high",
        description=(
            "Multi-region deployment was requested, but the architecture does not "
            "include a global routing or replication layer."
        ),
        suggestion=(
            "Add Route 53 with latency-based or geolocation routing to direct users "
            "to the nearest region. For the database layer, use Aurora Global Database "
            "(sub-1s cross-region replication) or DynamoDB Global Tables (active-active "
            "across multiple regions). AWS Global Accelerator can further reduce latency "
            "by routing traffic over AWS's backbone rather than the public internet."
        ),
        details={},
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_constraints(
    requirements: dict,
    architecture: dict,
    cost: dict,
) -> list[ConstraintViolation]:
    """Run all constraint validators and return a list of violations.

    Args:
        requirements: structured output from extract_requirements()
        architecture: the 'architecture' key from generate_architecture()
        cost: the output from estimate_cost()

    Returns:
        List of ConstraintViolation objects (empty if all constraints are satisfied).
    """
    violations: list[ConstraintViolation] = []

    # Budget
    budget_violation = _check_budget(requirements, cost)
    if budget_violation:
        violations.append(budget_violation)

    # Compliance
    violations.extend(_check_compliance(requirements, architecture))

    # Availability SLA
    availability_violation = _check_availability(requirements, architecture)
    if availability_violation:
        violations.append(availability_violation)

    # Real-time / low latency
    latency_violation = _check_latency(requirements, architecture)
    if latency_violation:
        violations.append(latency_violation)

    # Multi-region
    multi_region_violation = _check_multi_region(requirements, architecture)
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
    # Quick smoke test
    import json

    reqs = {
        "budget_cap_usd": 200.0,
        "compliance_requirements": ["hipaa"],
        "requires_multi_region": True,
        "requires_realtime": True,
        "min_availability_percent": 99.99,
    }
    arch = {
        "layers": {
            "edge": ["Amazon CloudFront"],
            "networking": ["VPC", "AWS Application Load Balancer"],
            "compute": ["AWS Lambda"],
            "database": ["Amazon RDS"],
            "messaging": [],
            "monitoring": ["Amazon CloudWatch"],
            "security": [],
        }
    }
    cost_result = {"total_monthly_usd": 450}

    results = validate_constraints(reqs, arch, cost_result)
    print(json.dumps([v.to_dict() for v in results], indent=2))
