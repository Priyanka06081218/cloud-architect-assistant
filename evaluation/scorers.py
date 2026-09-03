# evaluation/scorers.py
#
# Scoring functions for the golden set evaluation.
#
# Design principles:
#   - Cost and availability: calculable from pipeline output → scored precisely
#   - Latency: pipeline outputs an estimate, not a measurement → noted in report
#   - Service matching: substring match (case-insensitive), not exact match
#     ("Aurora MySQL" matches "Aurora", "ECS Fargate" matches "ECS" and "Fargate")
#   - Multiple valid architectures exist → we score what MUST be present,
#     not penalize for valid alternatives

from typing import Optional


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
    """
    Returns True if `expected` appears as a substring of any actual service name.
    Case-insensitive.
    Examples:
      "RDS"         matches "Amazon RDS", "Aurora MySQL (RDS)", "RDS Multi-AZ"
      "ElastiCache" matches "ElastiCache Redis", "Amazon ElastiCache"
      "Fargate"     matches "ECS Fargate", "AWS Fargate"
    """
    expected_lower = expected.lower()
    return any(expected_lower in svc.lower() for svc in actual_services)


# ---------------------------------------------------------------------------
# Score 1: Service completeness
# What fraction of expected_services appear in the generated architecture?
# ---------------------------------------------------------------------------

def score_service_completeness(
    expected_services: list[str],
    actual_services: list[str],
) -> dict:
    """
    Returns:
        score: float 0.0–1.0
        matched: services found
        missing: services not found
    """
    if not expected_services:
        return {"score": 1.0, "matched": [], "missing": [], "note": "no expected services defined"}

    matched = [s for s in expected_services if _service_match(s, actual_services)]
    missing = [s for s in expected_services if not _service_match(s, actual_services)]

    return {
        "score": len(matched) / len(expected_services),
        "matched": matched,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Score 2: Forbidden service violations
# Did the system recommend any service that should NOT appear?
# ---------------------------------------------------------------------------

def score_forbidden_violations(
    forbidden_services: list[str],
    actual_services: list[str],
) -> dict:
    """
    Returns:
        violations: list of forbidden services that appeared
        passed: True if no violations
    """
    violations = [s for s in forbidden_services if _service_match(s, actual_services)]
    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "violation_count": len(violations),
    }


# ---------------------------------------------------------------------------
# Score 3: Cost range check
# Does the estimated monthly cost fall within the expected range?
# ---------------------------------------------------------------------------

def score_cost_range(
    expected_range: Optional[list],
    actual_cost_usd: Optional[float],
) -> dict:
    """
    Returns:
        passed: bool
        actual: float
        expected_range: [min, max]
        note: explanation
    """
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
# Score 4: Compliance mention check
# For compliance-tagged scenarios, does the reasoning mention the standard?
# ---------------------------------------------------------------------------

COMPLIANCE_KEYWORDS = {
    "HIPAA":   ["hipaa", "phi", "health insurance", "protected health"],
    "PCI-DSS": ["pci", "pci-dss", "cardholder", "payment card"],
    "SOC2":    ["soc 2", "soc2", "soc type", "trust service"],
    "GDPR":    ["gdpr", "data residency", "eu regulation", "general data protection"],
}

def score_compliance_mention(
    required_compliance: list[str],
    reasoning: str,
) -> dict:
    """
    Returns:
        score: fraction of required compliance standards mentioned
        found: list of standards mentioned
        missing: list of standards not mentioned
    """
    if not required_compliance:
        return {"score": 1.0, "found": [], "missing": [], "note": "no compliance required"}

    reasoning_lower = reasoning.lower()
    found = []
    missing = []

    for standard in required_compliance:
        keywords = COMPLIANCE_KEYWORDS.get(standard, [standard.lower()])
        if any(kw in reasoning_lower for kw in keywords):
            found.append(standard)
        else:
            missing.append(standard)

    return {
        "score": len(found) / len(required_compliance),
        "found": found,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Aggregate: score one scenario
# ---------------------------------------------------------------------------

def score_scenario(scenario: dict, pipeline_output: dict) -> dict:
    """
    Run all scorers against one scenario's pipeline output.
    Returns a dict with scores for each dimension and an overall pass/fail.
    """
    if pipeline_output.get("error"):
        return {
            "id": scenario["id"],
            "error": pipeline_output["error"],
            "passed": False,
            "overall_score": 0.0,
        }

    architecture = pipeline_output.get("architecture", {})
    cost_info    = pipeline_output.get("cost", {})
    reasoning    = architecture.get("reasoning", "") + " " + pipeline_output.get("scenario_summary", "")

    actual_services  = extract_services(architecture)
    actual_cost      = cost_info.get("total_monthly_usd")

    completeness = score_service_completeness(
        scenario.get("expected_services", []),
        actual_services,
    )
    forbidden = score_forbidden_violations(
        scenario.get("forbidden_services", []),
        actual_services,
    )
    cost = score_cost_range(
        scenario.get("expected_cost_range"),
        actual_cost,
    )
    compliance = score_compliance_mention(
        scenario.get("expected_constraints", {}).get("compliance", []),
        reasoning,
    )

    # Overall score: weighted average
    # Forbidden violations are critical — any violation caps score at 0.5
    weights = {"completeness": 0.40, "compliance": 0.30, "cost": 0.30}
    weighted_score = (
        completeness["score"] * weights["completeness"]
        + compliance["score"] * weights["compliance"]
        + (1.0 if cost["passed"] else 0.0) * weights["cost"]
        if cost["passed"] is not None
        else completeness["score"] * 0.50 + compliance["score"] * 0.50
    )

    if not forbidden["passed"]:
        weighted_score = min(weighted_score, 0.5)

    return {
        "id":             scenario["id"],
        "category":       scenario["category"],
        "difficulty":     scenario["difficulty"],
        "actual_services": actual_services,
        "completeness":   completeness,
        "forbidden":      forbidden,
        "cost":           cost,
        "compliance":     compliance,
        "overall_score":  round(weighted_score, 3),
        "passed":         weighted_score >= 0.7 and forbidden["passed"],
    }
