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
    details: dict = field(default_factory=dict)

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


def _cloud(requirements: dict) -> str:
    """Return the normalized cloud provider slug: 'aws', 'azure', or 'gcp'."""
    return (requirements.get("cloud_provider") or "aws").lower()


# ---------------------------------------------------------------------------
# Cloud-specific service vocabularies
# ---------------------------------------------------------------------------

# Compliance: for each standard and cloud, a list of {keyword, label, reason}.
# keyword  — substring searched against the lowercased service names in the architecture.
# label    — human-readable name shown in the violation message.
# reason   — why this service is required for this compliance standard.
_COMPLIANCE_RULES: dict[str, dict[str, list[dict]]] = {
    "hipaa": {
        "aws": [
            {"keyword": "kms",        "label": "AWS KMS",          "reason": "HIPAA requires encryption of PHI at rest using managed keys."},
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",   "reason": "HIPAA requires audit logging of all access to PHI."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty", "reason": "HIPAA expects continuous threat detection for environments storing health data."},
            {"keyword": "vpc",        "label": "VPC with private subnets", "reason": "HIPAA requires PHI to be isolated in a private network."},
        ],
        "azure": [
            {"keyword": "key vault",         "label": "Azure Key Vault",             "reason": "HIPAA requires encryption of PHI at rest using managed keys."},
            {"keyword": "monitor",           "label": "Azure Monitor (Activity Logs)","reason": "HIPAA requires audit logging of all access to PHI."},
            {"keyword": "defender",          "label": "Microsoft Defender for Cloud", "reason": "HIPAA expects continuous threat detection for environments storing health data."},
            {"keyword": "virtual network",   "label": "Azure Virtual Network",       "reason": "HIPAA requires PHI to be isolated in a private network."},
        ],
        "gcp": [
            {"keyword": "kms",           "label": "Cloud KMS",               "reason": "HIPAA requires encryption of PHI at rest using customer-managed keys."},
            {"keyword": "audit log",     "label": "Cloud Audit Logs",        "reason": "HIPAA requires audit logging of all access to PHI."},
            {"keyword": "security command", "label": "Security Command Center", "reason": "HIPAA expects continuous threat detection for environments storing health data."},
            {"keyword": "vpc",           "label": "VPC Network",             "reason": "HIPAA requires PHI to be isolated in a private network."},
        ],
    },
    "soc2": {
        "aws": [
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",   "reason": "SOC 2 CC7.2 requires logging of all privileged and user activity."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty", "reason": "SOC 2 CC6.8 requires continuous monitoring for unauthorized access attempts."},
            {"keyword": "waf",        "label": "AWS WAF",          "reason": "SOC 2 CC6.6 requires protection against common web exploits."},
        ],
        "azure": [
            {"keyword": "monitor",   "label": "Azure Monitor",                  "reason": "SOC 2 CC7.2 requires logging of all privileged and user activity."},
            {"keyword": "defender",  "label": "Microsoft Defender for Cloud",   "reason": "SOC 2 CC6.8 requires continuous monitoring for unauthorized access."},
            {"keyword": "waf",       "label": "Azure WAF",                      "reason": "SOC 2 CC6.6 requires protection against common web exploits."},
        ],
        "gcp": [
            {"keyword": "audit log",     "label": "Cloud Audit Logs",          "reason": "SOC 2 CC7.2 requires logging of all privileged and user activity."},
            {"keyword": "security command", "label": "Security Command Center", "reason": "SOC 2 CC6.8 requires continuous monitoring for unauthorized access."},
            {"keyword": "cloud armor",   "label": "Cloud Armor",               "reason": "SOC 2 CC6.6 requires protection against common web exploits."},
        ],
    },
    "pci-dss": {
        "aws": [
            {"keyword": "waf",        "label": "AWS WAF",          "reason": "PCI-DSS Req 6.6 mandates a WAF in front of all web-facing applications."},
            {"keyword": "kms",        "label": "AWS KMS",          "reason": "PCI-DSS Req 3.4 requires strong encryption for cardholder data at rest."},
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",   "reason": "PCI-DSS Req 10 mandates audit trails for all access to cardholder data."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty", "reason": "PCI-DSS Req 11.4 requires intrusion detection systems."},
            {"keyword": "vpc",        "label": "VPC with private subnets", "reason": "PCI-DSS Req 1 mandates network segmentation for cardholder data."},
        ],
        "azure": [
            {"keyword": "waf",           "label": "Azure WAF",                   "reason": "PCI-DSS Req 6.6 mandates a WAF in front of all web-facing applications."},
            {"keyword": "key vault",     "label": "Azure Key Vault",             "reason": "PCI-DSS Req 3.4 requires strong encryption for cardholder data at rest."},
            {"keyword": "monitor",       "label": "Azure Monitor",               "reason": "PCI-DSS Req 10 mandates audit trails for all access to cardholder data."},
            {"keyword": "defender",      "label": "Microsoft Defender for Cloud","reason": "PCI-DSS Req 11.4 requires intrusion detection systems."},
            {"keyword": "virtual network","label": "Azure Virtual Network",      "reason": "PCI-DSS Req 1 mandates network segmentation for cardholder data."},
        ],
        "gcp": [
            {"keyword": "cloud armor",      "label": "Cloud Armor",              "reason": "PCI-DSS Req 6.6 mandates a WAF in front of all web-facing applications."},
            {"keyword": "kms",              "label": "Cloud KMS",                "reason": "PCI-DSS Req 3.4 requires strong encryption for cardholder data at rest."},
            {"keyword": "audit log",        "label": "Cloud Audit Logs",         "reason": "PCI-DSS Req 10 mandates audit trails for all access to cardholder data."},
            {"keyword": "security command", "label": "Security Command Center",  "reason": "PCI-DSS Req 11.4 requires intrusion detection systems."},
            {"keyword": "vpc",              "label": "VPC Network",              "reason": "PCI-DSS Req 1 mandates network segmentation for cardholder data."},
        ],
    },
    "gdpr": {
        "aws": [
            {"keyword": "kms",        "label": "AWS KMS",        "reason": "GDPR Art. 32 requires encryption of personal data at rest and in transit."},
            {"keyword": "cloudtrail", "label": "AWS CloudTrail", "reason": "GDPR Art. 30 requires records of all processing activities."},
        ],
        "azure": [
            {"keyword": "key vault", "label": "Azure Key Vault", "reason": "GDPR Art. 32 requires encryption of personal data at rest and in transit."},
            {"keyword": "monitor",   "label": "Azure Monitor",   "reason": "GDPR Art. 30 requires records of all processing activities."},
        ],
        "gcp": [
            {"keyword": "kms",       "label": "Cloud KMS",       "reason": "GDPR Art. 32 requires encryption of personal data at rest and in transit."},
            {"keyword": "audit log", "label": "Cloud Audit Logs","reason": "GDPR Art. 30 requires records of all processing activities."},
        ],
    },
    "fedramp": {
        "aws": [
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",   "reason": "FedRAMP AU-2 requires comprehensive audit event logging."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty", "reason": "FedRAMP SI-3/SI-4 requires malware and intrusion detection."},
            {"keyword": "kms",        "label": "AWS KMS",          "reason": "FedRAMP SC-28 requires FIPS 140-2 validated encryption at rest."},
            {"keyword": "config",     "label": "AWS Config",       "reason": "FedRAMP CM-6/CM-7 requires continuous configuration compliance monitoring."},
        ],
        "azure": [
            {"keyword": "monitor",   "label": "Azure Monitor",                  "reason": "FedRAMP AU-2 requires comprehensive audit event logging."},
            {"keyword": "defender",  "label": "Microsoft Defender for Cloud",   "reason": "FedRAMP SI-3/SI-4 requires malware and intrusion detection."},
            {"keyword": "key vault", "label": "Azure Key Vault",                "reason": "FedRAMP SC-28 requires FIPS 140-2 validated encryption at rest."},
            {"keyword": "policy",    "label": "Azure Policy",                   "reason": "FedRAMP CM-6/CM-7 requires continuous configuration compliance."},
        ],
        "gcp": [
            {"keyword": "audit log",        "label": "Cloud Audit Logs",           "reason": "FedRAMP AU-2 requires comprehensive audit event logging."},
            {"keyword": "security command", "label": "Security Command Center",    "reason": "FedRAMP SI-3/SI-4 requires malware and intrusion detection."},
            {"keyword": "kms",              "label": "Cloud KMS",                  "reason": "FedRAMP SC-28 requires FIPS 140-2 validated encryption at rest."},
            {"keyword": "asset inventory",  "label": "Cloud Asset Inventory",      "reason": "FedRAMP CM-6/CM-7 requires continuous configuration compliance."},
        ],
    },
}

# HA detection keywords per cloud
_HA_DATABASE: dict[str, list[str]] = {
    "aws":   ["aurora", "rds multi", "dynamodb", "elasticache"],
    "azure": ["cosmos db", "cosmosdb", "azure sql", "azure database", "azure cache for redis", "redis"],
    "gcp":   ["cloud spanner", "spanner", "cloud sql", "bigtable", "firestore", "memorystore"],
}
_HA_COMPUTE: dict[str, list[str]] = {
    "aws":   ["ecs", "eks", "fargate", "auto scaling", "lambda"],
    "azure": ["aks", "container apps", "app service", "azure functions", "vmss"],
    "gcp":   ["gke", "cloud run", "cloud functions", "app engine"],
}
_HA_LOAD_BALANCER: dict[str, list[str]] = {
    "aws":   ["load balancer", "alb", "nlb"],
    "azure": ["load balancer", "application gateway", "front door"],
    "gcp":   ["cloud load balancing", "cloud lb", "load balancing"],
}

# HA suggestions per cloud
_HA_SUGGESTION: dict[str, str] = {
    "aws": (
        "To reach 99.99%+ availability: use Aurora with Multi-AZ replicas or "
        "DynamoDB (globally distributed by default), place ECS tasks across at "
        "least 3 AZs behind an ALB with health checks, and enable auto-scaling "
        "policies to replace unhealthy instances automatically."
    ),
    "azure": (
        "To reach 99.99%+ availability: use Azure Cosmos DB (99.999% SLA) or "
        "Azure Database for PostgreSQL with zone-redundant HA, run AKS or "
        "Container Apps across availability zones, and place an Azure Application "
        "Gateway or Load Balancer in front to distribute traffic."
    ),
    "gcp": (
        "To reach 99.99%+ availability: use Cloud Spanner (99.999% SLA for "
        "multi-region) or Cloud SQL with HA replica, run GKE Autopilot across "
        "zones with a regional cluster, and use Cloud Load Balancing (global) "
        "to route traffic to the nearest healthy instance."
    ),
}

# Latency / caching keywords per cloud
_LATENCY_CACHE: dict[str, list[str]] = {
    "aws":   ["elasticache", "redis", "memcached", "dax"],
    "azure": ["redis", "azure cache", "azure cache for redis"],
    "gcp":   ["memorystore", "redis"],
}
_LATENCY_CDN: dict[str, list[str]] = {
    "aws":   ["cloudfront", "cdn"],
    "azure": ["azure cdn", "front door", "cdn"],
    "gcp":   ["cloud cdn", "cdn"],
}
_LATENCY_FAST_DB: dict[str, list[str]] = {
    "aws":   ["dynamodb", "dax"],
    "azure": ["cosmos db", "cosmosdb"],
    "gcp":   ["bigtable", "firestore", "spanner"],
}

# Latency suggestions per cloud
_LATENCY_SUGGESTION: dict[str, str] = {
    "aws": (
        "Add: ElastiCache (Redis) for in-memory caching, "
        "DynamoDB for single-digit millisecond reads at any scale, "
        "CloudFront to serve static content from edge locations. "
        "ElastiCache is the highest-impact single addition — it eliminates "
        "database round-trips for hot data."
    ),
    "azure": (
        "Add: Azure Cache for Redis for in-memory caching (sub-millisecond reads), "
        "Azure Cosmos DB for single-digit millisecond NoSQL reads at global scale, "
        "Azure CDN or Azure Front Door to serve static content from 100+ edge PoPs."
    ),
    "gcp": (
        "Add: Memorystore for Redis for in-memory caching (sub-millisecond reads), "
        "Cloud Bigtable for sub-10ms reads on time-series or wide-column data at scale, "
        "Cloud CDN to cache static content at Google's global edge."
    ),
}

# Multi-region detection keywords per cloud
_MULTI_REGION_KEYWORDS: dict[str, list[str]] = {
    "aws":   ["route 53", "global accelerator", "cloudfront", "aurora global", "dynamodb global", "s3 replication"],
    "azure": ["front door", "traffic manager", "cosmos db", "cosmosdb", "geo-replication", "azure front door"],
    "gcp":   ["cloud load balancing", "cloud cdn", "cloud spanner", "spanner", "bigtable", "firestore"],
}

# Multi-region suggestions per cloud
_MULTI_REGION_SUGGESTION: dict[str, str] = {
    "aws": (
        "Add Route 53 with latency-based or geolocation routing to direct users "
        "to the nearest region. For the database layer, use Aurora Global Database "
        "(sub-1s cross-region replication) or DynamoDB Global Tables (active-active "
        "across multiple regions). AWS Global Accelerator reduces latency by routing "
        "traffic over AWS's private backbone rather than the public internet."
    ),
    "azure": (
        "Add Azure Front Door for global HTTP load balancing with intelligent routing "
        "and automatic failover. For the database layer, use Azure Cosmos DB with "
        "multi-region writes (active-active, 99.999% SLA) or Azure Database for "
        "PostgreSQL with read replicas in each target region. "
        "Azure Traffic Manager can also provide DNS-level failover between regions."
    ),
    "gcp": (
        "Add Cloud Load Balancing (global) to route users to the nearest region with "
        "Cloud CDN for edge caching. For the database layer, use Cloud Spanner "
        "(globally distributed, 99.999% multi-region SLA) or Firestore in multi-region "
        "mode. Both Cloud Bigtable and BigQuery natively replicate across regions."
    ),
}

# Budget suggestion per cloud
_BUDGET_SUGGESTION: dict[str, str] = {
    "aws": (
        "Consider replacing provisioned compute (ECS, EC2) with serverless "
        "(Lambda, Fargate Spot), switching RDS to Aurora Serverless v2 "
        "(scales to zero when idle), or removing ElastiCache if caching can "
        "be handled in-process. Also verify that the stated scale is not higher than necessary."
    ),
    "azure": (
        "Consider replacing AKS or VMs with Azure Container Apps or Azure Functions "
        "(consumption plan), switching Azure Database for PostgreSQL to the Flexible "
        "Server Burstable tier for dev/staging, or removing Azure Cache for Redis "
        "if in-process caching is sufficient. Verify the stated scale is not over-provisioned."
    ),
    "gcp": (
        "Consider replacing GKE with Cloud Run (scale-to-zero, pay-per-request), "
        "switching Cloud SQL to a smaller tier or Cloud Spanner only if truly needed "
        "(Cloud SQL is significantly cheaper), or removing Memorystore if in-process "
        "caching is sufficient. Verify Compute Engine instances use Spot/preemptible pricing."
    ),
}


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def _check_budget(requirements: dict, cost: dict) -> Optional[ConstraintViolation]:
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

    overage  = estimated - cap
    provider = _cloud(requirements)

    return ConstraintViolation(
        constraint_type="budget",
        severity="critical",
        description=(
            f"Estimated monthly cost (${estimated:,.0f}) exceeds the stated budget "
            f"cap of ${cap:,.0f}/month by ${overage:,.0f}."
        ),
        suggestion=_BUDGET_SUGGESTION.get(provider, _BUDGET_SUGGESTION["aws"]),
        details={
            "estimated_usd":  estimated,
            "budget_cap_usd": cap,
            "overage_usd":    round(overage, 2),
        },
    )


def _check_compliance(requirements: dict, architecture: dict) -> list[ConstraintViolation]:
    """Flag missing services for each stated compliance standard."""
    standards = [s.lower() for s in requirements.get("compliance_requirements", [])]
    if not standards:
        return []

    provider = _cloud(requirements)
    services  = _all_services(architecture)
    violations = []

    for standard in standards:
        cloud_rules = _COMPLIANCE_RULES.get(standard, {})
        # fall back to AWS rules if this cloud isn't mapped yet
        rules = cloud_rules.get(provider, cloud_rules.get("aws", []))
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
                "standard":        standard.upper(),
                "missing_services": missing_labels,
            },
        ))

    return violations


def _check_availability(requirements: dict, architecture: dict) -> Optional[ConstraintViolation]:
    """Flag if a high-availability SLA is required but key HA services are absent."""
    min_avail = requirements.get("min_availability_percent")
    if not min_avail:
        return None
    try:
        min_avail = float(min_avail)
    except (TypeError, ValueError):
        return None

    if min_avail < 99.9:
        return None

    provider = _cloud(requirements)
    services = _all_services(architecture)

    ha_database   = _any_match(services, _HA_DATABASE.get(provider, _HA_DATABASE["aws"]))
    ha_compute    = _any_match(services, _HA_COMPUTE.get(provider, _HA_COMPUTE["aws"]))
    load_balancer = _any_match(services, _HA_LOAD_BALANCER.get(provider, _HA_LOAD_BALANCER["aws"]))

    # Cloud-specific labels for missing components
    _missing_labels: dict[str, dict[str, str]] = {
        "aws":   {"db": "a Multi-AZ database (Aurora, DynamoDB, or ElastiCache)",
                  "compute": "managed compute with auto-scaling (ECS Fargate, EKS, or Lambda)",
                  "lb": "a load balancer (ALB or NLB) to distribute traffic across AZs"},
        "azure": {"db": "a zone-redundant database (Azure Cosmos DB or Azure Database for PostgreSQL HA)",
                  "compute": "managed container compute across zones (AKS, Container Apps, or App Service)",
                  "lb": "an Azure Application Gateway or Load Balancer for zone-redundant traffic distribution"},
        "gcp":   {"db": "a multi-zone database (Cloud Spanner, Cloud SQL HA, or Cloud Bigtable)",
                  "compute": "managed compute with zone spread (GKE regional cluster, or Cloud Run)",
                  "lb": "Cloud Load Balancing (global) for cross-zone traffic distribution"},
    }
    labels = _missing_labels.get(provider, _missing_labels["aws"])

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
        suggestion=_HA_SUGGESTION.get(provider, _HA_SUGGESTION["aws"]),
        details={
            "required_availability_percent": min_avail,
            "missing_components": missing,
        },
    )


def _check_latency(requirements: dict, architecture: dict) -> Optional[ConstraintViolation]:
    """Flag if real-time or low-latency is required but no caching layer is present."""
    if not requirements.get("requires_realtime"):
        return None

    provider = _cloud(requirements)
    services = _all_services(architecture)

    has_cache   = _any_match(services, _LATENCY_CACHE.get(provider, _LATENCY_CACHE["aws"]))
    has_cdn     = _any_match(services, _LATENCY_CDN.get(provider, _LATENCY_CDN["aws"]))
    has_fast_db = _any_match(services, _LATENCY_FAST_DB.get(provider, _LATENCY_FAST_DB["aws"]))

    if has_cache or (has_cdn and has_fast_db):
        return None

    return ConstraintViolation(
        constraint_type="latency",
        severity="high",
        description=(
            "Real-time or low-latency performance was requested, but the architecture "
            "lacks the services typically required to achieve sub-100ms response times at scale."
        ),
        suggestion=_LATENCY_SUGGESTION.get(provider, _LATENCY_SUGGESTION["aws"]),
        details={},
    )


def _check_multi_region(requirements: dict, architecture: dict) -> Optional[ConstraintViolation]:
    """Flag if multi-region was requested but no global routing layer is present."""
    if not requirements.get("requires_multi_region"):
        return None

    provider = _cloud(requirements)
    services = _all_services(architecture)

    has_global_routing = _any_match(
        services,
        _MULTI_REGION_KEYWORDS.get(provider, _MULTI_REGION_KEYWORDS["aws"])
    )

    if has_global_routing:
        return None

    return ConstraintViolation(
        constraint_type="multi_region",
        severity="high",
        description=(
            "Multi-region deployment was requested, but the architecture does not "
            "include a global routing or replication layer."
        ),
        suggestion=_MULTI_REGION_SUGGESTION.get(provider, _MULTI_REGION_SUGGESTION["aws"]),
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

    budget_violation = _check_budget(requirements, cost)
    if budget_violation:
        violations.append(budget_violation)

    violations.extend(_check_compliance(requirements, architecture))

    availability_violation = _check_availability(requirements, architecture)
    if availability_violation:
        violations.append(availability_violation)

    latency_violation = _check_latency(requirements, architecture)
    if latency_violation:
        violations.append(latency_violation)

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
    import json

    # AWS test
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

    # GCP test
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
