#!/usr/bin/env python3
# evaluation/run_eval.py
#
# Score saved pipeline outputs against the golden set.
# Free to run — no LLM calls, no API costs.
# Run after generate_outputs.py has saved pipeline_outputs.json.
#
# Usage:
#   cd ~/Documents/cloud-architect-assistant
#   python -m evaluation.run_eval                    # AWS (default)
#   python -m evaluation.run_eval --cloud azure
#   python -m evaluation.run_eval --cloud gcp
#   python -m evaluation.run_eval --cloud all        # score all three
#
#   # Use custom output file (e.g. after a pipeline change):
#   python -m evaluation.run_eval --cloud azure --outputs evaluation/results/pipeline_outputs_azure_v2.json
#
# Outputs:
#   evaluation/results/eval_report_<cloud>_<timestamp>.json   (full per-scenario results)
#   Prints summary table to stdout

import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.scorers import score_scenario

EVAL_DIR    = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"

GOLDEN_SET_MAP = {
    "aws":   EVAL_DIR / "golden_set.json",
    "azure": EVAL_DIR / "golden_set_azure.json",
    "gcp":   EVAL_DIR / "golden_set_gcp.json",
}

DEFAULT_OUTPUT_MAP = {
    "aws":   RESULTS_DIR / "pipeline_outputs.json",
    "azure": RESULTS_DIR / "pipeline_outputs_azure.json",
    "gcp":   RESULTS_DIR / "pipeline_outputs_gcp.json",
}


def load_data(cloud: str, outputs_path: Path):
    golden_path = GOLDEN_SET_MAP[cloud]
    if not golden_path.exists():
        print(f"ERROR: Golden set not found: {golden_path}")
        sys.exit(1)

    with open(golden_path) as f:
        scenarios = {s["id"]: s for s in json.load(f)}

    if not outputs_path.exists():
        print(f"ERROR: {outputs_path} not found.")
        print(f"Run 'python -m evaluation.generate_outputs --cloud {cloud}' first.")
        sys.exit(1)

    with open(outputs_path) as f:
        outputs = json.load(f)

    return scenarios, outputs


def run_evaluation(scenarios: dict, outputs: dict) -> list[dict]:
    results = []
    for sid, scenario in scenarios.items():
        if sid not in outputs:
            results.append({
                "id": sid, "category": scenario["category"],
                "difficulty": scenario["difficulty"],
                "error": "not in outputs (run generate_outputs.py)",
                "passed": False, "overall_score": 0.0,
            })
            continue
        result = score_scenario(scenario, outputs[sid])
        results.append(result)
    return results


def print_report(results: list[dict], cloud: str):
    total   = len(results)
    passed  = sum(1 for r in results if r.get("passed"))
    errored = sum(1 for r in results if r.get("error") and "not in outputs" not in r.get("error", ""))
    avg_score = sum(r.get("overall_score", 0) for r in results) / total if total else 0

    categories = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in categories:
            categories[cat] = {"total": 0, "passed": 0, "scores": []}
        categories[cat]["total"] += 1
        if r.get("passed"):
            categories[cat]["passed"] += 1
        categories[cat]["scores"].append(r.get("overall_score", 0))

    scored = [r for r in results if not r.get("error")]
    avg_completeness = (
        sum(r["completeness"]["score"] for r in scored) / len(scored) if scored else 0
    )
    avg_compliance = (
        sum(r["compliance"]["score"] for r in scored) / len(scored) if scored else 0
    )
    cost_checked   = [r for r in scored if r["cost"]["passed"] is not None]
    cost_pass_rate = (
        sum(1 for r in cost_checked if r["cost"]["passed"]) / len(cost_checked)
        if cost_checked else None
    )
    forbidden_violations = sum(r["forbidden"]["violation_count"] for r in scored)

    cloud_label = cloud.upper()
    print(f"\n{'='*65}")
    print(f"  Cloud Architect Evaluation Report — {cloud_label}")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*65}")
    print(f"  Scenarios scored:      {total}")
    print(f"  Passed (score ≥ 0.70): {passed}/{total}  ({100*passed//total if total else 0}%)")
    print(f"  Pipeline errors:       {errored}")
    print(f"  Overall avg score:     {avg_score:.3f}")
    print(f"")
    print(f"  Dimension breakdown:")
    print(f"    Service completeness:    {avg_completeness:.1%}  (required services present)")
    print(f"    Compliance mentions:     {avg_compliance:.1%}  (standard named in reasoning)")
    if cost_pass_rate is not None:
        print(f"    Cost range pass rate:    {cost_pass_rate:.1%}  (estimate within expected range)")
    print(f"    Forbidden violations:    {forbidden_violations}     (critical failures)")
    print(f"")
    print(f"  By category:")
    for cat, data in sorted(categories.items()):
        cat_avg = sum(data["scores"]) / len(data["scores"])
        print(f"    {cat:<20} {data['passed']}/{data['total']} passed   avg {cat_avg:.3f}")
    print(f"")

    print(f"  Per-scenario results:")
    print(f"  {'ID':<28} {'Cat':<16} {'Diff':<8} {'Score':<7} {'Pass':<6} {'Issues'}")
    print(f"  {'-'*28} {'-'*16} {'-'*8} {'-'*7} {'-'*6} {'-'*30}")
    for r in sorted(results, key=lambda x: x.get("overall_score", 0)):
        issues = []
        if r.get("error"):
            issues.append(r["error"][:30])
        else:
            if r.get("completeness", {}).get("missing"):
                issues.append(f"missing: {', '.join(r['completeness']['missing'])}")
            if r.get("forbidden", {}).get("violations"):
                issues.append(f"FORBIDDEN: {', '.join(r['forbidden']['violations'])}")
            if r.get("compliance", {}).get("missing"):
                issues.append(f"no mention: {', '.join(r['compliance']['missing'])}")
            if r.get("cost", {}).get("passed") is False:
                issues.append(r["cost"].get("note", "cost out of range"))

        passed_str = "PASS" if r.get("passed") else "FAIL"
        score_str  = f"{r.get('overall_score', 0):.3f}"
        issue_str  = " | ".join(issues)[:50] if issues else "—"
        print(f"  {r['id']:<28} {r.get('category','?'):<16} {r.get('difficulty','?'):<8} "
              f"{score_str:<7} {passed_str:<6} {issue_str}")

    print(f"{'='*65}\n")


def save_report(results: list[dict], cloud: str, outputs_path: Path) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = RESULTS_DIR / f"eval_report_{cloud}_{timestamp}.json"

    report = {
        "cloud":        cloud,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outputs_file": str(outputs_path),
        "total":        len(results),
        "passed":       sum(1 for r in results if r.get("passed")),
        "avg_score":    sum(r.get("overall_score", 0) for r in results) / len(results) if results else 0,
        "results":      results,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Report saved: {report_path}")
    return report_path


def score_cloud(cloud: str, outputs_path: Path | None = None):
    if outputs_path is None:
        outputs_path = DEFAULT_OUTPUT_MAP[cloud]
    scenarios, outputs = load_data(cloud, outputs_path)
    results = run_evaluation(scenarios, outputs)
    print_report(results, cloud)
    save_report(results, cloud, outputs_path)


def main():
    parser = argparse.ArgumentParser(description="Score pipeline outputs against the golden set")
    parser.add_argument(
        "--cloud",
        choices=["aws", "azure", "gcp", "all"],
        default="aws",
        help="Which cloud to score (default: aws)",
    )
    parser.add_argument(
        "--outputs",
        type=Path,
        default=None,
        help="Path to pipeline_outputs file (overrides default for the chosen cloud)",
    )
    args = parser.parse_args()

    clouds = ["aws", "azure", "gcp"] if args.cloud == "all" else [args.cloud]

    # --outputs only makes sense for a single cloud
    if args.outputs and len(clouds) > 1:
        print("ERROR: --outputs can only be used with a single --cloud, not 'all'.")
        sys.exit(1)

    for cloud in clouds:
        score_cloud(cloud, args.outputs)


if __name__ == "__main__":
    main()
