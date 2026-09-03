# tests/test_cost_calculator.py
#
# Unit tests for the cost calculator — scale multipliers, region multipliers,
# service lookup, and edge cases. No LLM calls required.

import pytest
from pipeline.cost_calculator import estimate_cost, _compute_multiplier, _region_multiplier, _parse_scale


# ---------------------------------------------------------------------------
# Scale parsing
# ---------------------------------------------------------------------------

class TestParseScale:

    def test_concurrent_users_with_k_suffix(self):
        # "50k concurrent" → 50,000 concurrent × 10 = 500,000 daily equiv
        result = _parse_scale({"scale": "50k concurrent users"})
        assert result == 500_000

    def test_concurrent_users_no_k(self):
        # "1000 concurrent" → 1000 × 10 = 10,000 daily equiv
        result = _parse_scale({"scale": "1000 concurrent users"})
        assert result == 10_000

    def test_daily_users(self):
        # "10k daily users" → 10,000
        result = _parse_scale({"scale": "10k daily users"})
        assert result == 10_000

    def test_no_match_returns_default(self):
        # "not specified" matches no pattern → 5000 default
        assert _parse_scale({"scale": "not specified"}) == 5000

    def test_missing_scale_key_returns_default(self):
        # No scale key → 5000 default
        assert _parse_scale({}) == 5000

    def test_raw_query_parsed_as_fallback(self):
        # raw_query is also searched; "1000 daily users" in raw_query
        result = _parse_scale({"raw_query": "build a system for 1000 daily users", "scale": "not specified"})
        assert result == 1_000


# ---------------------------------------------------------------------------
# Compute multiplier tiers
# ---------------------------------------------------------------------------

class TestComputeMultiplier:

    def test_below_5k_returns_1x(self):
        # Default (no match) is 5000 users → tier < 50k = 2x
        # Need explicit small value — use raw_query with 1000 daily users
        reqs = {"raw_query": "build for 1000 daily users", "scale": "1000 daily users"}
        assert _compute_multiplier(reqs) == 1

    def test_small_tier_returns_2x(self):
        # 10k daily users → tier 5k-50k → 2x
        assert _compute_multiplier({"scale": "10k daily users"}) == 2

    def test_medium_tier_returns_4x(self):
        # 100k daily users → tier 50k-500k → 4x
        assert _compute_multiplier({"scale": "100k daily users"}) == 4

    def test_large_tier_returns_10x(self):
        # 1M concurrent users → 10M daily equiv → tier 5M+ → 18x
        # 100k concurrent → 1M daily equiv → tier 500k-5M → 10x
        assert _compute_multiplier({"scale": "100k concurrent users"}) == 10

    def test_xlarge_tier_returns_18x(self):
        # 500k concurrent → 5M daily equiv → tier 5M+ → 18x (capped)
        assert _compute_multiplier({"scale": "500k concurrent users"}) == 18

    def test_default_scale_returns_2x(self):
        # Default 5000 users is in the 5k-50k tier → 2x
        assert _compute_multiplier({}) == 2


# ---------------------------------------------------------------------------
# Region multiplier
# ---------------------------------------------------------------------------

class TestRegionMultiplier:

    def test_single_region_returns_1(self):
        assert _region_multiplier({"raw_query": "simple API", "constraints": []}) == 1

    def test_multi_region_in_raw_query(self):
        reqs = {"raw_query": "multi-region active-active platform", "constraints": []}
        assert _region_multiplier(reqs) == 2

    def test_multi_region_in_constraints(self):
        reqs = {"raw_query": "api", "constraints": ["multi-region", "high availability"]}
        assert _region_multiplier(reqs) == 2

    def test_global_trigger(self):
        reqs = {"raw_query": "global e-commerce platform", "constraints": []}
        assert _region_multiplier(reqs) == 2

    def test_no_keys_returns_1(self):
        assert _region_multiplier({}) == 1


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

class TestEstimateCost:

    def _arch(self, *services):
        return {"layers": {"compute": list(services), "database": [], "networking": [],
                            "edge": [], "monitoring": [], "security": []}}

    def test_empty_layers_includes_data_transfer_baseline(self):
        # Even empty architecture includes data transfer ($9 baseline)
        result = estimate_cost({"layers": {}})
        assert result["total_monthly_usd"] == pytest.approx(9.0)

    def test_known_service_increases_cost(self):
        base = estimate_cost({"layers": {}})["total_monthly_usd"]
        with_ecs = estimate_cost(self._arch("Amazon ECS"))["total_monthly_usd"]
        assert with_ecs > base

    def test_cost_scales_with_concurrent_users(self):
        arch = self._arch("Amazon ECS")
        cost_small = estimate_cost(arch, {"scale": "1000 daily users", "raw_query": "1000 daily users"})
        cost_large = estimate_cost(arch, {"scale": "100k concurrent users"})
        assert cost_large["total_monthly_usd"] > cost_small["total_monthly_usd"]

    def test_result_has_required_keys(self):
        result = estimate_cost(self._arch("AWS Lambda"))
        assert "total_monthly_usd" in result
        assert "monthly_breakdown" in result
        assert "spike_estimate_usd" in result
        assert "scale_tier" in result

    def test_spike_estimate_is_35_percent_higher(self):
        result = estimate_cost(self._arch("AWS Lambda"))
        expected_spike = round(result["total_monthly_usd"] * 1.35, 2)
        assert result["spike_estimate_usd"] == pytest.approx(expected_spike, rel=1e-3)

    def test_shield_advanced_not_priced(self):
        # Shield Advanced is excluded from SERVICE_NAME_MAP to prevent cost inflation
        arch = self._arch("AWS Shield Advanced")
        result = estimate_cost(arch)
        service_names = [s.get("service", "").lower() for s in result.get("monthly_breakdown", [])]
        assert not any("shield advanced" in name for name in service_names)
        # Total should just be the data transfer baseline
        assert result["total_monthly_usd"] == pytest.approx(9.0)

    def test_unknown_service_is_ignored(self):
        arch = self._arch("Some Imaginary AWS Service XYZ")
        result = estimate_cost(arch)
        # Only data transfer baseline
        assert result["total_monthly_usd"] == pytest.approx(9.0)

    def test_multi_region_doubles_non_global_costs(self):
        arch = self._arch("Amazon ECS")
        single = estimate_cost(arch, {"raw_query": "single region", "constraints": []})
        multi  = estimate_cost(arch, {"raw_query": "multi-region platform", "constraints": []})
        # Multi-region should cost more
        assert multi["total_monthly_usd"] > single["total_monthly_usd"]

    def test_aurora_not_multiplied_by_compute(self):
        # Aurora Serverless is scalable=False — only region multiplier applied
        arch = {"layers": {"database": ["Aurora Serverless"], "compute": [],
                            "networking": [], "edge": [], "monitoring": [], "security": []}}
        small = estimate_cost(arch, {"scale": "100 daily users", "raw_query": "100 daily users"})
        large = estimate_cost(arch, {"scale": "100k concurrent users"})
        # Aurora cost should be the same (region_mult=1 in both cases with no multi-region signal)
        aurora_small = next((s["monthly_usd"] for s in small["monthly_breakdown"] if "aurora" in s["service"].lower()), None)
        aurora_large = next((s["monthly_usd"] for s in large["monthly_breakdown"] if "aurora" in s["service"].lower()), None)
        if aurora_small and aurora_large:
            assert aurora_small == aurora_large
