# pipeline/evaluator.py
#
# Scores each candidate architecture on four dimensions:
#   cost         — lower monthly cost is better
#   latency      — lower p95 latency is better
#   availability — higher uptime is better
#   constraints  — fewer/lower-severity violations is better
#
# All dimensions are normalized to [0, 100] so they can be compared across
# candidates. The composite score is NOT a single weighted sum — instead,
# we return the raw scores and let pareto.py find the Pareto frontier.
# This avoids the pretense that there's one correct set of weights.

from __future__ import annotations
from pipeline.cost_calculator    import estimate_cost
from pipeline.performance_model  import estimate_performance
from pipeline.constraint_engine  import validate_constraints
from pipeline.cloud_providers    import get_provider


def evaluate(architecture: dict, requirements: dict) -> dict:
    """Score one candidate architecture.

    Returns:
        {
            "cost":         {...}    # from estimate_cost
            "performance":  {...}    # from estimate_performance
            "violations":   [...]   # from validate_constraints
            "scores": {
                "cost_score":         float,  # 0=cheapest seen, 100=expensive
                "latency_score":      float,  # 0=fastest p95, 100=slowest
                "availability_score": float,  # 0=least available, 100=most
                "constraint_score":   float,  # 0=many violations, 100=none
                "composite":          float,  # equal-weight average (informational)
            }
        }
    """
    cloud    = requirements.get("cloud_provider", "aws").lower()
    provider = get_provider(cloud)

    cost       = estimate_cost(architecture, requirements, provider=provider)
    perf       = estimate_performance(architecture, requirements)
    violations = validate_constraints(requirements, architecture, cost)

    # Raw values used for Pareto comparison
    monthly_usd  = cost.get("total_monthly_usd", 0) or 0
    p95_ms       = perf.get("p95_ms", 999)
    availability = perf.get("availability", 0.99)

    # Constraint severity → numeric penalty
    sev_weight = {"critical": 30, "high": 15, "medium": 5, "low": 1}
    constraint_penalty = sum(
        sev_weight.get(v.severity, 0) for v in violations
    )

    return {
        "cost":        cost,
        "performance": perf,
        "violations":  [v.to_dict() for v in violations],
        "_raw": {
            "monthly_usd":         monthly_usd,
            "p95_ms":              p95_ms,
            "availability":        availability,
            "constraint_penalty":  constraint_penalty,
        },
    }


def score_relative(candidates: list[dict]) -> list[dict]:
    """Add normalized [0,100] scores to each candidate relative to the candidate set.

    Each item in `candidates` must have an "evaluation" key from evaluate().
    Mutates each dict in-place (adds "scores" key) and returns the list.
    """
    if not candidates:
        return candidates

    evaluations  = [c["evaluation"] for c in candidates]
    costs        = [e["_raw"]["monthly_usd"]        for e in evaluations]
    latencies    = [e["_raw"]["p95_ms"]             for e in evaluations]
    availabilities = [e["_raw"]["availability"]     for e in evaluations]
    penalties    = [e["_raw"]["constraint_penalty"] for e in evaluations]

    min_cost, max_cost           = min(costs), max(costs)
    min_lat,  max_lat            = min(latencies), max(latencies)
    min_avail, max_avail         = min(availabilities), max(availabilities)
    max_penalty                  = max(penalties) or 1

    def norm_inverted(val, lo, hi):
        """0 = worst (hi), 100 = best (lo). Equal when lo == hi."""
        if hi == lo:
            return 100.0
        return 100 * (1 - (val - lo) / (hi - lo))

    def norm_forward(val, lo, hi):
        """0 = worst (lo), 100 = best (hi). Equal when lo == hi."""
        if hi == lo:
            return 100.0
        return 100 * (val - lo) / (hi - lo)

    for c in candidates:
        r = c["evaluation"]["_raw"]
        cost_score         = norm_inverted(r["monthly_usd"],        min_cost,  max_cost)
        latency_score      = norm_inverted(r["p95_ms"],             min_lat,   max_lat)
        availability_score = norm_forward( r["availability"],       min_avail, max_avail)
        constraint_score   = norm_inverted(r["constraint_penalty"], 0,         max_penalty)
        composite = (cost_score + latency_score + availability_score + constraint_score) / 4

        c["scores"] = {
            "cost_score":         round(cost_score,         1),
            "latency_score":      round(latency_score,      1),
            "availability_score": round(availability_score, 1),
            "constraint_score":   round(constraint_score,   1),
            "composite":          round(composite,           1),
        }

    return candidates


def find_pareto(candidates_with_scores: list[dict]) -> list[int]:
    """Return indices of Pareto-optimal candidates (cost, latency, availability).

    A candidate is Pareto-optimal if no other candidate is strictly better on
    all three dimensions simultaneously.
    """
    raws = [c["evaluation"]["_raw"] for c in candidates_with_scores]
    pareto_indices = []

    for i, ri in enumerate(raws):
        dominated = False
        for j, rj in enumerate(raws):
            if i == j:
                continue
            # j dominates i if j is at least as good on all dimensions and strictly
            # better on at least one
            j_better_cost  = rj["monthly_usd"]   <= ri["monthly_usd"]
            j_better_lat   = rj["p95_ms"]         <= ri["p95_ms"]
            j_better_avail = rj["availability"]   >= ri["availability"]
            j_better_constr = rj["constraint_penalty"] <= ri["constraint_penalty"]
            j_strictly_better = (
                rj["monthly_usd"]          < ri["monthly_usd"]   or
                rj["p95_ms"]               < ri["p95_ms"]        or
                rj["availability"]         > ri["availability"]   or
                rj["constraint_penalty"]   < ri["constraint_penalty"]
            )
            if j_better_cost and j_better_lat and j_better_avail and j_better_constr and j_strictly_better:
                dominated = True
                break
        if not dominated:
            pareto_indices.append(i)

    return pareto_indices
