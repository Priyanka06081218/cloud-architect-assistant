# pipeline/performance_model.py
#
# Estimates p50/p95 latency, max throughput (RPS), and availability for a
# recommended architecture. All figures are approximations based on documented
# SLAs and typical benchmark ranges — right order of magnitude for comparing
# architectures, not production SLOs.
#
# Methodology:
#   Latency   — sum p50/p95 latency contributions along the synchronous request
#               path: edge → load balancer → compute → database (cache shortcut
#               replaces DB latency when a cache tier is present)
#   Throughput — bottleneck analysis: find the compute service, multiply its
#               per-unit RPS capacity by the estimated instance count
#   Availability — multiply SLAs of services on the critical path (series model);
#               redundant (multi-AZ) services get a small uplift

from __future__ import annotations
import re

# (p50_ms, p95_ms) latency each service adds when it sits on the synchronous
# request path. Values are conservative estimates from public benchmarks.
_LATENCY_MS: dict[str, tuple[float, float]] = {
    # CDN / edge — cache hit path (miss falls through to compute)
    "cloudfront":               (5,   15),
    "azure cdn":                (5,   15),
    "azure front door":         (8,   20),
    "cloud cdn":                (5,   15),

    # Load balancers
    "alb":                      (1,    3),
    "application load balancer":(1,    3),
    "nlb":                      (0.5,  1),
    "network load balancer":    (0.5,  1),
    "azure load balancer":      (1,    3),
    "application gateway":      (2,    5),
    "cloud load balancing":     (1,    3),

    # API gateways — routing + auth overhead
    "api gateway":              (8,   20),
    "azure api management":     (10,  25),
    "cloud endpoints":          (8,   20),

    # Compute — processing time, warm instances
    "ecs fargate":              (15,  40),
    "ecs":                      (15,  40),
    "fargate":                  (15,  40),
    "eks":                      (12,  35),
    "aks":                      (12,  35),
    "gke":                      (12,  35),
    "ec2":                      (10,  30),
    "azure container apps":     (15,  40),
    "cloud run":                (15,  45),
    "app engine":               (20,  60),
    "azure app service":        (15,  45),

    # Serverless compute — cold start risk inflates p95 significantly
    "lambda":                   (10, 250),
    "aws lambda":               (10, 250),
    "azure functions":          (10, 350),
    "cloud functions":          (10, 250),

    # Relational databases
    "rds":                      (8,   25),
    "aurora":                   (4,   15),
    "aurora serverless":        (5,   20),
    "cloud sql":                (8,   25),
    "azure database for postgresql": (8, 25),
    "azure sql":                (8,   25),
    "cosmos db":                (3,   10),
    "azure cosmos db":          (3,   10),
    "cloud spanner":            (3,   10),

    # NoSQL / document
    "dynamodb":                 (2,    8),
    "amazon dynamodb":          (2,    8),
    "firestore":                (4,   12),

    # Caches — hit path (replaces DB latency when cache is in architecture)
    "elasticache":              (0.5,  2),
    "elasticache redis":        (0.5,  2),
    "redis":                    (0.5,  2),
    "azure cache for redis":    (0.5,  2),
    "memorystore":              (0.5,  2),
    "memorystore for redis":    (0.5,  2),
}

# Documented service SLAs (monthly uptime percentage → fraction).
# Where a service has tiered SLAs we use the Multi-AZ / HA tier.
_SLA: dict[str, float] = {
    # AWS
    "ec2":                      0.9999,
    "ecs fargate":              0.9999,
    "ecs":                      0.9999,
    "eks":                      0.9999,
    "lambda":                   0.9995,
    "aws lambda":               0.9995,
    "alb":                      0.9999,
    "application load balancer":0.9999,
    "nlb":                      0.9999,
    "api gateway":              0.9999,
    "cloudfront":               0.9999,
    "rds":                      0.9995,
    "aurora":                   0.9999,
    "aurora serverless":        0.9999,
    "dynamodb":                 0.99999,
    "elasticache":              0.9999,
    "elasticache redis":        0.9999,
    "sqs":                      0.9999,
    "sns":                      0.9999,
    "kms":                      0.9999,

    # Azure
    "aks":                      0.9999,
    "azure container apps":     0.9999,
    "azure functions":          0.9995,
    "azure app service":        0.9995,
    "application gateway":      0.9999,
    "azure load balancer":      0.9999,
    "azure front door":         0.9999,
    "azure cdn":                0.9999,
    "azure api management":     0.9999,
    "azure database for postgresql": 0.9995,
    "azure sql":                0.9999,
    "cosmos db":                0.99999,
    "azure cosmos db":          0.99999,
    "azure cache for redis":    0.9999,
    "azure service bus":        0.9999,
    "azure event hubs":         0.9999,
    "azure key vault":          0.9999,

    # GCP
    "gke":                      0.9999,
    "cloud run":                0.9999,
    "cloud functions":          0.9995,
    "app engine":               0.9999,
    "cloud load balancing":     0.9999,
    "cloud sql":                0.9995,
    "cloud spanner":            0.99999,
    "firestore":                0.9999,
    "memorystore":              0.9999,
    "memorystore for redis":    0.9999,
    "cloud pub/sub":            0.9999,
    "cloud armor":              0.9999,
    "secret manager":           0.9999,
    "cloud kms":                0.9999,
    "cloud cdn":                0.9999,
}

# Max requests-per-second per single unit (instance/task/node).
# Used for throughput ceiling estimation.
_RPS_PER_UNIT: dict[str, int] = {
    "ecs fargate":              500,
    "ecs":                      500,
    "fargate":                  500,
    "eks":                      800,
    "aks":                      800,
    "gke":                      800,
    "ec2":                      300,
    "azure container apps":     500,
    "cloud run":                600,
    "azure app service":        200,
    "app engine":               300,
    "lambda":                   1000,   # per concurrent invocation
    "aws lambda":               1000,
    "azure functions":          800,
    "cloud functions":          800,
    "aurora":                   3000,   # DB reads/sec per node (with connection pooling)
    "aurora serverless":        2000,
    "dynamodb":                 40000,  # provisioned throughput (scalable)
    "cosmos db":                10000,
    "azure cosmos db":          10000,
    "cloud spanner":            2000,   # per node
    "firestore":                10000,
    "elasticache":              100000, # Redis — almost never the bottleneck
    "azure cache for redis":    100000,
    "memorystore":              100000,
}

# Services that carry requests synchronously (on the critical path).
# Messaging, monitoring, and security services are async and not on the hot path.
_ASYNC_LAYERS = {"messaging", "monitoring", "security"}

# Services that act as a cache and, when present, replace DB latency with cache latency.
_CACHE_KEYWORDS = {"elasticache", "redis", "memorystore", "azure cache for redis"}


def _match(name: str, table: dict) -> float | None:
    """Return the best match for `name` in `table` (case-insensitive substring)."""
    nl = name.lower()
    # Exact match first
    if nl in table:
        return table[nl]
    # Longest prefix/substring match
    best_key, best_val = None, None
    for key, val in table.items():
        if key in nl or nl in key:
            if best_key is None or len(key) > len(best_key):
                best_key, best_val = key, val
    return best_val


def _services_on_critical_path(architecture: dict) -> list[str]:
    """Return services that sit on the synchronous request path."""
    layers = architecture.get("layers", {})
    services = []
    for layer_name, svcs in layers.items():
        if layer_name in _ASYNC_LAYERS:
            continue
        services.extend(svcs)
    return services


def _has_cache(services: list[str]) -> bool:
    return any(
        any(ck in svc.lower() for ck in _CACHE_KEYWORDS)
        for svc in services
    )


def _compute_services(services: list[str]) -> list[str]:
    """Return services that look like compute (not DB, cache, CDN, or LB)."""
    db_hints  = {"rds", "aurora", "dynamo", "sql", "cosmos", "spanner", "firestore",
                 "mongo", "cassandra", "bigtable", "redshift"}
    cdn_hints = {"cloudfront", "cdn", "front door"}
    lb_hints  = {"load balancer", "alb", "nlb", "gateway"}
    cache_hints = _CACHE_KEYWORDS

    result = []
    for svc in services:
        sl = svc.lower()
        if any(h in sl for h in db_hints | cdn_hints | lb_hints | cache_hints):
            continue
        result.append(svc)
    return result


def estimate_performance(architecture: dict, requirements: dict) -> dict:
    """Estimate latency, throughput, and availability for a recommended architecture.

    Returns a dict with:
        p50_ms          — estimated median response time
        p95_ms          — estimated 95th-percentile response time
        max_rps         — estimated peak requests-per-second capacity
        availability    — estimated uptime fraction (e.g. 0.9994)
        availability_pct — formatted string ("99.94%")
        notes           — list of plain-English observations
    """
    services    = _services_on_critical_path(architecture)
    has_cache   = _has_cache(services)
    notes: list[str] = []

    # Latency — walk the critical path and sum contributions
    p50_total = 0.0
    p95_total = 0.0
    has_serverless = False
    db_replaced_by_cache = False

    for svc in services:
        sl = svc.lower()

        # Skip caches in the latency sum if they're replacing DB latency
        is_cache = any(ck in sl for ck in _CACHE_KEYWORDS)
        is_db    = any(h in sl for h in {"rds", "aurora", "dynamo", "sql", "cosmos",
                                          "spanner", "firestore", "bigtable", "redshift"})

        if is_db and has_cache and not db_replaced_by_cache:
            # Model a 70% cache hit rate: weighted average of cache and DB latency
            cache_p50, cache_p95 = 0.5, 2.0
            db_lat = _match(svc, _LATENCY_MS)
            if db_lat:
                db_p50, db_p95 = db_lat
                p50_total += 0.70 * cache_p50 + 0.30 * db_p50
                p95_total += 0.70 * cache_p95 + 0.30 * db_p95
                db_replaced_by_cache = True
                notes.append(
                    f"Cache hit rate modeled at 70% — effective DB latency reduced "
                    f"from ~{db_p95:.0f}ms p95 to ~{0.70*cache_p95+0.30*db_p95:.0f}ms p95."
                )
            continue

        if is_cache:
            continue  # already accounted for above

        lat = _match(svc, _LATENCY_MS)
        if lat:
            p50, p95 = lat
            p50_total += p50
            p95_total += p95

        # Flag serverless cold-start risk
        if any(kw in sl for kw in ("lambda", "azure functions", "cloud functions")):
            has_serverless = True

    if has_serverless:
        notes.append(
            "Serverless compute (Lambda/Functions) can add 200–500 ms to p95 for "
            "infrequently invoked endpoints (cold starts). Set provisioned concurrency / "
            "min-instances to keep warm if latency SLO is strict."
        )

    # Multi-region adds geographic latency
    if requirements.get("requires_multi_region"):
        p50_total += 40
        p95_total += 60
        notes.append("Multi-region routing adds ~40–60 ms for cross-region failover paths.")

    p50_ms = round(p50_total, 1)
    p95_ms = round(p95_total, 1)

    # Throughput — find the primary compute service, multiply by instance count
    compute_svcs = _compute_services(services)
    max_rps = None
    for svc in compute_svcs:
        rps = _match(svc, _RPS_PER_UNIT)
        if rps:
            # Reuse the scale multiplier logic from cost_calculator
            try:
                from pipeline.cost_calculator import _compute_multiplier
                units = max(1, _compute_multiplier(requirements))
            except Exception:
                units = 1
            candidate = rps * units
            if max_rps is None or candidate < max_rps:
                max_rps = candidate  # bottleneck = minimum across compute services

    if max_rps is None:
        max_rps = 500  # conservative fallback

    # Availability — multiply SLAs of critical-path services
    availability = 1.0
    for svc in services:
        sla = _match(svc, _SLA)
        if sla:
            availability *= sla

    # Multi-AZ / redundant deploys improve availability slightly
    multi_az = any(kw in str(requirements.get("constraints", [])).lower()
                   for kw in ("multi-az", "high availability", "ha", "redundan"))
    if multi_az:
        # Two independent instances: P(both down) = (1-SLA)^2, so availability improves
        downtime = 1 - availability
        availability = 1 - (downtime ** 2)
        notes.append("Multi-AZ redundancy modeled — availability uplifted via parallel failure probability.")

    availability = round(min(availability, 0.99999), 6)
    nines = _nines_label(availability)
    avail_pct = f"{availability * 100:.4f}%"

    return {
        "p50_ms":           p50_ms,
        "p95_ms":           p95_ms,
        "max_rps":          max_rps,
        "availability":     availability,
        "availability_pct": avail_pct,
        "nines":            nines,
        "notes":            notes,
    }


def _nines_label(availability: float) -> str:
    downtime_min_per_month = (1 - availability) * 30 * 24 * 60
    if downtime_min_per_month < 1:
        return f"~{downtime_min_per_month*60:.0f} seconds/month downtime"
    elif downtime_min_per_month < 60:
        return f"~{downtime_min_per_month:.0f} minutes/month downtime"
    else:
        return f"~{downtime_min_per_month/60:.1f} hours/month downtime"
