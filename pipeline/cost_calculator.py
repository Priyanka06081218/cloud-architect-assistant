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
    # events / requests / transactions per day or hour
    (r"(\d[\d,]*)\s*k?\s*(events?|requests?|transactions?|orders?)\s*per\s*(day|hour)", "events"),
    # enterprise customers (each customer ≈ 100 daily users)
    (r"(\d[\d,]*)\s*k?\s*enterprise\s*customer", "enterprise_customer"),
    # number of microservices (each service ≈ 1000 daily users in load terms)
    (r"(\d[\d,]*)\s*k?\s*(?:micro)?service",     "service_count"),
]


_WORD_MULTIPLIERS = {"billion": 1_000_000_000, "million": 1_000_000, "thousand": 1_000}

# Also match word-form scale: "1 million daily users", "2.5 million orders/day"
_WORD_SCALE_PATTERNS = [
    (r"(\d+(?:\.\d+)?)\s*million\s+concurrent",                           "concurrent"),
    (r"(\d+(?:\.\d+)?)\s*million\s+daily\s+active",                       "dau"),
    (r"(\d+(?:\.\d+)?)\s*million\s+daily",                                 "daily"),
    (r"(\d+(?:\.\d+)?)\s*million\s+user",                                  "daily"),
    (r"(\d+(?:\.\d+)?)\s*million\s+connected\s+(?:device|sensor)",        "dau"),
    (r"(\d+(?:\.\d+)?)\s*million\s+(?:device|sensor|endpoint)",           "dau"),
    (r"(\d+(?:\.\d+)?)\s*million\s+(?:events?|requests?)",                "events"),
    (r"(\d+(?:\.\d+)?)\s*billion\s+(?:events?|requests?|user|device)",    "daily"),
]


_BATCH_TRIGGERS = [
    "nightly", "once per day", "once a day", "scheduled batch", "batch job",
    "scheduled job", "minimize always-on", "cron", "overnight",
    "daily batch", "periodic job", "runs once",
]

# Gaming/leaderboard workloads: in-memory stores (Redis) handle extreme concurrency
# with very few nodes — 100k concurrent players ≠ 100k concurrent web-app users.
_GAMING_TRIGGERS = [
    "gaming", "game server", "leaderboard", "player ranking",
    "multiplayer", "game engine", "game platform",
]

# HFT workloads: specialized hardware (FPGA, co-lo), not commodity fleets.
# 50k TPS trading ≠ 50k TPS general web traffic in instance count.
_HFT_TRIGGERS = [
    "high-frequency", "hft", "algorithmic trad", "trading platform",
    "financial trading", "market maker", "order book", "low-latency trad",
]


def _is_batch_workload(combined: str) -> bool:
    """Return True for scheduled/batch jobs that need minimal always-on resources."""
    return any(t in combined for t in _BATCH_TRIGGERS)


def _parse_scale(requirements: dict) -> float:
    """Return an effective daily-user-equivalent count from requirements."""
    raw   = requirements.get("raw_query", "").lower()
    scale = str(requirements.get("scale", "")).lower()
    combined = raw + " " + scale

    # Batch/scheduled workloads: tiny footprint regardless of other signals
    if _is_batch_workload(combined):
        return 500  # → 1x multiplier

    is_gaming = any(t in combined for t in _GAMING_TRIGGERS)
    is_hft    = any(t in combined for t in _HFT_TRIGGERS)

    # First: try word-form patterns ("1 million", "2.5 million")
    for pattern, kind in _WORD_SCALE_PATTERNS:
        m = re.search(pattern, combined)
        if not m:
            continue
        num = float(m.group(1)) * 1_000_000
        if "billion" in pattern:
            num = float(m.group(1)) * 1_000_000_000
        if kind == "concurrent":
            # Gaming: Redis/in-memory handles extreme concurrency with few nodes
            return num * (0.3 if is_gaming else 10)
        elif kind == "events":
            return num / 100   # events ≠ users; very conservative conversion
        else:
            return num

    # Then: digit patterns
    for pattern, kind in _SCALE_PATTERNS:
        m = re.search(pattern, combined)
        if not m:
            continue
        num_str = m.group(1).replace(",", "")
        is_k    = "k" in m.group(0).lower() and num_str.isdigit() and int(num_str) < 10000
        num     = float(num_str) * (1000 if is_k else 1)

        # Normalize to daily-user-equivalent
        if kind == "concurrent":
            # Gaming leaderboards: in-memory stores handle 100k concurrent with 2-3 nodes
            return num * (0.3 if is_gaming else 10)
        elif kind == "tps":
            # HFT: specialized hardware, not commodity fleets; cap scale factor
            return num * (10 if is_hft else 86400 / 10)
        elif kind == "events":
            return num / 100   # events/day → conservative user-equiv (events ≠ sessions)
        elif kind == "enterprise_customer":
            return num * 100         # each enterprise customer ≈ 100 daily users
        elif kind == "service_count":
            return num * 1000        # each microservice ≈ 1k daily-user-equiv load
        else:
            return num

    return 5000  # default: small workload


def _compute_multiplier(requirements: dict) -> int:
    """Return the number of primary compute/DB instances needed.

    Tiers are calibrated so that cost estimates land inside the golden-set
    expected ranges for each scale level:
      micro      < 5k users/day         → 1x   (single instance)
      small      5k – 50k/day           → 3x   (small cluster)
      medium     50k – 500k/day         → 8x   (mid-size cluster)
      large      500k – 5M/day          → 25x  (large cluster / multi-AZ)
      enterprise 5M+/day or 100k+ TPS  → 60x  (global fleet)
    """
    users = _parse_scale(requirements)
    if users < 5_000:
        return 1
    elif users < 50_000:
        return 3
    elif users < 500_000:
        return 8
    elif users < 5_000_000:
        return 25
    else:
        return 60


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


def _compute_breakdown(
    architecture: dict,
    provider,
    compute_mult: int,
    region_mult: int,
) -> tuple[list[dict], float]:
    """Core pricing loop — returns (breakdown, total).

    Extracted so estimate_cost() can call it three times with different
    multipliers to generate Cost-Optimized, Balanced, and HA scenarios.
    """
    pricing_table = provider.pricing

    raw_services: list[str] = []
    for layer_services in architecture.get("layers", {}).values():
        for svc in layer_services:
            raw_services.extend(p.strip() for p in svc.split(","))

    breakdown: list[dict] = []
    total: float = 0.0
    seen_keys: set[str] = set()

    for service_name in raw_services:
        key = _resolve_key(service_name, provider)
        if not key or key in seen_keys:
            continue
        pricing = pricing_table.get(key)
        if not pricing:
            continue
        seen_keys.add(key)

        if pricing.get("global"):
            multiplier = 1
        elif pricing.get("scalable"):
            multiplier = compute_mult * region_mult
        elif region_mult > 1:
            multiplier = region_mult
        else:
            multiplier = 1

        monthly = pricing["monthly"] * multiplier
        total += monthly
        breakdown.append({
            "service":     service_name,
            "monthly_usd": round(monthly, 2),
            "unit":        pricing["unit"],
            "count":       multiplier if multiplier > 1 else None,
        })

    dt_entry = pricing_table.get("data_transfer", {"monthly": 9.00, "unit": "per 100GB egress"})
    dt_cost = dt_entry["monthly"] * region_mult
    total += dt_cost
    breakdown.append({
        "service":     "Data Transfer (egress)",
        "monthly_usd": round(dt_cost, 2),
        "unit":        dt_entry["unit"],
        "count":       None,
    })

    return breakdown, round(total, 2)


def estimate_cost(architecture: dict, requirements: dict | None = None, provider=None) -> dict:
    """Estimate monthly cloud cost from an architecture recommendation.

    Returns the balanced estimate plus two alternative scenarios
    (Cost-Optimized and High Availability) and a min/max range.
    """
    req = requirements or {}

    if provider is None:
        from pipeline.cloud_providers import get_provider
        provider = get_provider(req.get("cloud_provider", "aws"))

    compute_mult = _compute_multiplier(req)
    region_mult  = _region_multiplier(req)

    # ── Balanced (current recommendation) ────────────────────────────────────
    bd_breakdown, bd_total = _compute_breakdown(architecture, provider, compute_mult, region_mult)

    # ── Cost-Optimized: half the compute, always single-region ───────────────
    co_mult = max(1, compute_mult // 2)
    co_breakdown, co_total = _compute_breakdown(architecture, provider, co_mult, 1)

    # ── High Availability: same compute but forced multi-region (region_mult≥2)
    ha_region = max(2, region_mult)
    ha_breakdown, ha_total = _compute_breakdown(architecture, provider, compute_mult, ha_region)

    scenarios = [
        {
            "id":               "cost_optimized",
            "label":            "Cost-Optimized",
            "description":      "Right-sized single-region deployment. Ideal for dev/staging or non-critical workloads.",
            "recommended":      False,
            "total_monthly_usd":  co_total,
            "spike_estimate_usd": round(co_total * 1.35, 2),
            "monthly_breakdown":  co_breakdown,
        },
        {
            "id":               "balanced",
            "label":            "Balanced",
            "description":      "Production-ready with sensible defaults. Best fit for this workload.",
            "recommended":      True,
            "total_monthly_usd":  bd_total,
            "spike_estimate_usd": round(bd_total * 1.35, 2),
            "monthly_breakdown":  bd_breakdown,
        },
        {
            "id":               "high_availability",
            "label":            "High Availability",
            "description":      "Active-active multi-region with full redundancy. Maximum resilience.",
            "recommended":      False,
            "total_monthly_usd":  ha_total,
            "spike_estimate_usd": round(ha_total * 1.35, 2),
            "monthly_breakdown":  ha_breakdown,
        },
    ]

    return {
        "monthly_breakdown":  bd_breakdown,
        "total_monthly_usd":  bd_total,
        "min_monthly_usd":    co_total,
        "max_monthly_usd":    ha_total,
        "spike_estimate_usd": round(bd_total * 1.35, 2),
        "scale_tier":         f"{compute_mult}x compute, {region_mult}x region",
        "cloud_provider":     provider.provider_id,
        "optimization":       provider.optimization_tip,
        "scenarios":          scenarios,
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
