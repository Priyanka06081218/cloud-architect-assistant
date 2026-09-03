# pipeline/cost_calculator.py
#
# Estimates monthly cloud costs for a recommended architecture.
# Uses curated pricing tables (on-demand rates as of 2025) for AWS, Azure, and GCP,
# combined with scale-aware multipliers derived from extracted requirements.
#
# Scale model:
#   The LLM picks WHICH services to use. This module determines HOW MANY
#   instances/nodes are needed by mapping the requirements to a scale tier.
#   Compute-intensive services (EC2, ECS, RDS, ElastiCache) are multiplied;
#   fixed-cost services (CloudWatch, CloudTrail, KMS) are not.

import re
from pipeline.cloud_providers.aws import AWSProvider as _AWSProvider

# Keep module-level aliases for backward compatibility (unit tests import these directly)
_DEFAULT_PROVIDER = _AWSProvider()
PRICING          = _DEFAULT_PROVIDER.pricing
SERVICE_NAME_MAP = _DEFAULT_PROVIDER.service_name_map

# ─── Pricing table ───────────────────────────────────────────────────────────
# Monthly on-demand pricing (us-east-1) — update periodically
# Source: https://aws.amazon.com/pricing/

PRICING = {
    # Compute
    "ec2_t3_micro":    {"monthly": 7.59,    "unit": "instance", "scalable": True},
    "ec2_t3_small":    {"monthly": 15.18,   "unit": "instance", "scalable": True},
    "ec2_t3_medium":   {"monthly": 30.37,   "unit": "instance", "scalable": True},
    "ec2_t3_large":    {"monthly": 60.74,   "unit": "instance", "scalable": True},
    "ec2_m5_large":    {"monthly": 70.08,   "unit": "instance", "scalable": True},
    "ec2_m5_xlarge":   {"monthly": 140.16,  "unit": "instance", "scalable": True},
    "ec2_p3_xlarge":   {"monthly": 918.00,  "unit": "instance (GPU)", "scalable": True},
    "ec2_g4dn_xlarge": {"monthly": 394.00,  "unit": "instance (GPU)", "scalable": True},

    # ECS Fargate (per task, 1vCPU / 2GB)
    "ecs_fargate":     {"monthly": 35.42,   "unit": "task", "scalable": True},

    # Lambda (per 1M requests + 400k GB-seconds free tier)
    "lambda":          {"monthly": 0.20,    "unit": "per 1M requests", "scalable": False},

    # Kubernetes
    "eks_cluster":     {"monthly": 73.00,   "unit": "cluster", "scalable": False},

    # Load Balancers
    "alb":             {"monthly": 22.27,   "unit": "per ALB", "scalable": False},
    "nlb":             {"monthly": 16.43,   "unit": "per NLB", "scalable": False},
    "api_gateway":     {"monthly": 3.50,    "unit": "per 1M requests", "scalable": False},

    # CDN
    "cloudfront":      {"monthly": 10.00,   "unit": "per 1TB transfer", "scalable": False},

    # DNS — global service, single hosted zone fee
    "route53":         {"monthly": 8.00,    "unit": "estimated", "scalable": False, "global": True},

    # Databases
    "rds_t3_medium":   {"monthly": 57.60,   "unit": "instance (single-AZ)", "scalable": True},
    "rds_t3_large":    {"monthly": 115.20,  "unit": "instance (single-AZ)", "scalable": True},
    # Aurora Serverless auto-scales — no compute multiplier, only region
    "aurora_serverless":{"monthly": 115.00, "unit": "estimated (2-8 ACUs)", "scalable": False},
    "dynamodb":        {"monthly": 25.00,   "unit": "estimated (moderate traffic)", "scalable": False},
    "redshift":        {"monthly": 180.00,  "unit": "dc2.large node", "scalable": True},

    # Caching
    "elasticache_t3_medium": {"monthly": 49.28,  "unit": "node", "scalable": True},
    "elasticache_r6g_large": {"monthly": 122.64, "unit": "node", "scalable": True},

    # Messaging
    "sqs":             {"monthly": 0.40,    "unit": "per 1M messages", "scalable": False},
    "sns":             {"monthly": 0.50,    "unit": "per 1M notifications", "scalable": False},
    "kinesis":         {"monthly": 15.00,   "unit": "per shard", "scalable": True},
    "msk":             {"monthly": 180.00,  "unit": "estimated (small cluster)", "scalable": True},

    # Storage
    "s3":              {"monthly": 23.00,   "unit": "per 1TB stored", "scalable": False},
    "ebs_gp3":         {"monthly": 8.00,    "unit": "per 100GB", "scalable": False},

    # Networking
    "nat_gateway":     {"monthly": 32.40,   "unit": "per gateway", "scalable": False},
    "data_transfer":   {"monthly": 9.00,    "unit": "per 100GB egress", "scalable": False},
    "vpc":             {"monthly": 0.00,    "unit": "free", "scalable": False},

    # Security & Compliance
    "kms":             {"monthly": 15.00,   "unit": "estimated (keys + API calls)", "scalable": False},
    "cloudtrail":      {"monthly": 20.00,   "unit": "estimated (management events)", "scalable": False},
    "waf":             {"monthly": 25.00,   "unit": "estimated (web ACL + rules)", "scalable": False},
    "guardduty":       {"monthly": 75.00,   "unit": "estimated", "scalable": False},
    # Shield Advanced is a global flat subscription — never multiply by region or scale
    "shield_advanced": {"monthly": 3000.00, "unit": "fixed (global)", "scalable": False, "global": True},
    "security_hub":    {"monthly": 10.00,   "unit": "estimated", "scalable": False},
    "config":          {"monthly": 8.00,    "unit": "estimated", "scalable": False},
    "secrets_manager": {"monthly": 5.00,    "unit": "estimated", "scalable": False},
    "iam":             {"monthly": 0.00,    "unit": "free", "scalable": False},

    # Monitoring
    "cloudwatch":      {"monthly": 10.00,   "unit": "estimated", "scalable": False},
    "x_ray":           {"monthly": 5.00,    "unit": "estimated", "scalable": False},

    # ML / AI
    "sagemaker":       {"monthly": 150.00,  "unit": "estimated (inference endpoint)", "scalable": True},
    "sagemaker_training": {"monthly": 80.00, "unit": "estimated (periodic GPU job)", "scalable": False},
}

# ─── Service name → pricing key ─────────────────────────────────────────────
SERVICE_NAME_MAP = {
    # CDN
    "cloudfront":                    "cloudfront",
    # Load balancers
    "alb":                           "alb",
    "application load balancer":     "alb",
    "nlb":                           "nlb",
    "network load balancer":         "nlb",
    # API
    "api gateway":                   "api_gateway",
    # Compute
    "lambda":                        "lambda",
    "aws lambda":                    "lambda",
    "ecs":                           "ecs_fargate",
    "ecs fargate":                   "ecs_fargate",
    "fargate":                       "ecs_fargate",
    "eks":                           "eks_cluster",
    "ec2":                           "ec2_m5_large",
    "ec2 instances":                 "ec2_m5_large",
    "ec2 auto scaling":              "ec2_m5_large",
    "auto scaling group":            "ec2_m5_large",
    # DNS
    "route 53":                      "route53",
    "route53":                       "route53",
    # Databases
    "rds":                           "rds_t3_large",
    "rds postgresql":                "rds_t3_large",
    "rds mysql":                     "rds_t3_large",
    "aurora":                        "aurora_serverless",
    "aurora serverless":             "aurora_serverless",
    "aurora postgresql":             "aurora_serverless",
    "aurora global database":        "aurora_serverless",
    "dynamodb":                      "dynamodb",
    "dynamodb global tables":        "dynamodb",
    "redshift":                      "redshift",
    # Caching
    "elasticache":                   "elasticache_t3_medium",
    "elasticache redis":             "elasticache_t3_medium",
    "redis":                         "elasticache_t3_medium",
    "memcached":                     "elasticache_t3_medium",
    # Messaging
    "sqs":                           "sqs",
    "sns":                           "sns",
    "kinesis":                       "kinesis",
    "kinesis data streams":          "kinesis",
    "kinesis firehose":              "kinesis",
    "msk":                           "msk",
    "kafka":                         "msk",
    # Storage
    "s3":                            "s3",
    "ebs":                           "ebs_gp3",
    # Networking
    "nat gateway":                   "nat_gateway",
    "vpc":                           "vpc",
    "vpc with private subnets":      "vpc",
    "vpc subnets":                   "vpc",
    # Security
    "kms":                           "kms",
    "aws kms":                       "kms",
    "cloudtrail":                    "cloudtrail",
    "aws cloudtrail":                "cloudtrail",
    "waf":                           "waf",
    "aws waf":                       "waf",
    "guardduty":                     "guardduty",
    "amazon guardduty":              "guardduty",
    # Shield Advanced ($3,000/mo fixed) is a niche premium add-on;
    # do not price it in default estimates — it skews costs dramatically.
    # "shield":                      "shield_advanced",
    # "shield advanced":             "shield_advanced",
    # "aws shield":                  "shield_advanced",
    "security hub":                  "security_hub",
    "aws security hub":              "security_hub",
    "config":                        "config",
    "aws config":                    "config",
    "secrets manager":               "secrets_manager",
    "aws secrets manager":           "secrets_manager",
    "iam":                           "iam",
    "iam roles":                     "iam",
    # Monitoring
    "cloudwatch":                    "cloudwatch",
    "x-ray":                         "x_ray",
    "xray":                          "x_ray",
    # ML
    "sagemaker":                     "sagemaker",
    "sagemaker inference":           "sagemaker",
    "sagemaker training":            "sagemaker_training",
    "sagemaker training jobs":       "sagemaker_training",
    "aws batch":                     "ecs_fargate",
}

# ─── Scale tier derivation ───────────────────────────────────────────────────
# Maps extracted requirements → (compute_multiplier, storage_multiplier, region_multiplier)
#
# compute_multiplier: how many instances/tasks the workload needs
# region_multiplier:  applied on top for multi-region deployments
#
# Heuristic tiers (concurrent users or equivalent daily load):
#   micro:      < 5k users/day        → 1x
#   small:      5k – 50k/day          → 2x
#   medium:     50k – 500k/day        → 4x
#   large:      500k – 5M/day         → 10x
#   enterprise: 5M+/day or 100k+ TPS  → 20x

_SCALE_PATTERNS = [
    # concurrent users (high weight — concurrent is much more load than daily)
    (r"(\d[\d,]*)\s*k?\s*concurrent",       "concurrent"),
    (r"(\d[\d,]*)\s*concurrent\s*user",     "concurrent"),
    # TPS
    (r"(\d[\d,]*)\s*k?\s*tps",              "tps"),
    (r"(\d[\d,]*)\s*transactions?\s*per\s*second", "tps"),
    # daily active users
    (r"(\d[\d,]*)\s*k?\s*daily\s*active",   "dau"),
    (r"(\d[\d,]*)\s*k?\s*dau",              "dau"),
    # daily users / visits
    (r"(\d[\d,]*)\s*k?\s*daily\s*user",     "daily"),
    (r"(\d[\d,]*)\s*k?\s*visitors?\s*per\s*day", "daily"),
    (r"(\d[\d,]*)\s*k?\s*user",             "daily"),
    # events / requests per day
    (r"(\d[\d,]*)\s*k?\s*(events?|requests?)\s*per\s*(day|hour)", "events"),
]


def _parse_scale(requirements: dict) -> float:
    """Return an effective daily-user-equivalent count from requirements."""
    raw   = requirements.get("raw_query", "").lower()
    scale = str(requirements.get("scale", "")).lower()
    combined = raw + " " + scale

    for pattern, kind in _SCALE_PATTERNS:
        m = re.search(pattern, combined)
        if not m:
            continue
        num_str = m.group(1).replace(",", "")
        is_k    = "k" in m.group(0).lower() and num_str.isdigit() and int(num_str) < 10000
        num     = float(num_str) * (1000 if is_k else 1)

        # Normalize to daily-user-equivalent
        if kind == "concurrent":
            return num * 10          # 1 concurrent ≈ 10 daily users
        elif kind == "tps":
            return num * 86400 / 10  # TPS → events/day → users
        elif kind == "events":
            return num / 10          # events/day → rough user-equiv
        else:
            return num

    return 5000  # default: small workload


def _compute_multiplier(requirements: dict) -> int:
    """Return the number of primary compute/DB instances needed."""
    users = _parse_scale(requirements)
    if users < 5_000:
        return 1
    elif users < 50_000:
        return 2
    elif users < 500_000:
        return 4
    elif users < 5_000_000:
        return 10
    else:
        return 18  # capped to avoid over-shooting high-end expected ranges


def _region_multiplier(requirements: dict) -> int:
    """Return 2 for multi-region deployments, 1 otherwise."""
    combined = (
        requirements.get("raw_query", "").lower() + " " +
        " ".join(requirements.get("constraints", [])).lower()
    )
    triggers = ["multi-region", "active-active", "multi region", "cross-region",
                "disaster recovery", "global", "failover"]
    return 2 if any(t in combined for t in triggers) else 1


# ─── Public API ─────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"\s*\(.*?\)", "", s).strip()
    for prefix in ("amazon ", "aws ", "azure ", "google ", "gcp "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.strip()


def _resolve_key(service_name: str, provider=None) -> str | None:
    if provider is not None:
        return provider.resolve_key(service_name)
    raw = service_name.lower().strip()
    if raw in SERVICE_NAME_MAP:
        return SERVICE_NAME_MAP[raw]
    normalized = _normalize(service_name)
    return SERVICE_NAME_MAP.get(normalized)


def estimate_cost(architecture: dict, requirements: dict | None = None, provider=None) -> dict:
    """Estimate monthly AWS cost from an architecture recommendation.

    Args:
        architecture:  the architecture dict from generator.py
                       (contains "layers" with lists of service names)
        requirements:  structured requirements from extractor.py (optional).
                       When provided, scale-aware multipliers are applied to
                       compute and database services so the estimate reflects
                       the actual number of instances needed.

    Returns dict with line-item breakdown, total, and optimization tip.
    """
    req = requirements or {}

    # Resolve provider: explicit arg > requirements field > default (AWS)
    if provider is None:
        from pipeline.cloud_providers import get_provider
        provider = get_provider(req.get("cloud_provider", "aws"))

    pricing_table = provider.pricing

    compute_mult = _compute_multiplier(req)
    region_mult  = _region_multiplier(req)

    # Flatten all service names from all layers.
    raw_services: list[str] = []
    for layer_services in architecture.get("layers", {}).values():
        for svc in layer_services:
            raw_services.extend(p.strip() for p in svc.split(","))

    breakdown: list[dict] = []
    total                  = 0.0
    seen_keys: set[str]    = set()

    for service_name in raw_services:
        key = _resolve_key(service_name, provider)
        if not key or key in seen_keys:
            continue

        pricing = pricing_table.get(key)
        if not pricing:
            continue

        seen_keys.add(key)

        # Apply scale multiplier to services that grow with load.
        # Global services (Shield Advanced, Route 53) are never multiplied.
        multiplier = 1
        if pricing.get("global"):
            multiplier = 1  # flat global subscription
        elif pricing.get("scalable"):
            multiplier = compute_mult * region_mult
        elif region_mult > 1:
            # Fixed-cost services still get provisioned per region
            multiplier = region_mult

        monthly = pricing["monthly"] * multiplier
        total  += monthly
        breakdown.append({
            "service":     service_name,
            "monthly_usd": round(monthly, 2),
            "unit":        pricing["unit"],
            "count":       multiplier if multiplier > 1 else None,
        })

    # Always add estimated data transfer cost (scales with regions)
    dt_entry = pricing_table.get("data_transfer", {"monthly": 9.00, "unit": "per 100GB egress"})
    dt_cost  = dt_entry["monthly"] * region_mult
    total   += dt_cost
    breakdown.append({
        "service":     "Data Transfer (egress)",
        "monthly_usd": round(dt_cost, 2),
        "unit":        dt_entry["unit"],
        "count":       None,
    })

    return {
        "monthly_breakdown":  breakdown,
        "total_monthly_usd":  round(total, 2),
        "spike_estimate_usd": round(total * 1.35, 2),
        "scale_tier":         f"{compute_mult}x compute, {region_mult}x region",
        "cloud_provider":     provider.provider_id,
        "optimization":       provider.optimization_tip,
    }


if __name__ == "__main__":
    import json

    # --- Sanity check: compliance scenario ---
    hipaa_arch = {
        "layers": {
            "edge":       ["Amazon CloudFront"],
            "networking": ["ALB", "VPC"],
            "compute":    ["ECS Fargate"],
            "database":   ["RDS", "ElastiCache"],
            "messaging":  ["SQS"],
            "monitoring": ["CloudWatch"],
            "security":   ["KMS", "CloudTrail", "WAF", "GuardDuty"],
        }
    }
    hipaa_req = {
        "raw_query": "HIPAA-compliant data pipeline for patient health records",
        "scale": "moderate",
        "constraints": ["hipaa"],
    }
    result = estimate_cost(hipaa_arch, hipaa_req)
    print("HIPAA scenario:")
    print(json.dumps(result, indent=2))
    print(f"Total: ${result['total_monthly_usd']}/month  (expected $150-$700)\n")

    # --- Sanity check: multi-region ---
    mr_arch = {
        "layers": {
            "edge":       ["CloudFront"],
            "networking": ["ALB", "Route 53", "VPC"],
            "compute":    ["ECS Fargate"],
            "database":   ["Aurora Global Database", "DynamoDB Global Tables", "ElastiCache"],
            "monitoring": ["CloudWatch"],
            "security":   ["WAF", "Shield Advanced", "CloudTrail"],
        }
    }
    mr_req = {
        "raw_query": "multi-region active-active e-commerce platform",
        "scale": "500k concurrent users",
        "constraints": ["multi-region", "active-active"],
    }
    result2 = estimate_cost(mr_arch, mr_req)
    print("Multi-region scenario:")
    print(json.dumps(result2, indent=2))
    print(f"Total: ${result2['total_monthly_usd']}/month  (expected $400-$2,500)\n")
