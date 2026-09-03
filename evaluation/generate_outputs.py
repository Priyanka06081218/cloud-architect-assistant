#!/usr/bin/env python3
# evaluation/generate_outputs.py
#
# Run the pipeline on every golden set scenario and save raw outputs.
# Run this ONCE when:
#   - the golden set changes
#   - the pipeline code changes (prompts, retriever, generator)
#
# After this, run run_eval.py (free, instant) to score the saved outputs.
#
# Usage:
#   cd ~/Documents/cloud-architect-assistant
#   python -m evaluation.generate_outputs              # AWS (default)
#   python -m evaluation.generate_outputs --cloud azure
#   python -m evaluation.generate_outputs --cloud gcp
#   python -m evaluation.generate_outputs --cloud all  # AWS + Azure + GCP
#
# Outputs:
#   evaluation/results/pipeline_outputs.json         (AWS)
#   evaluation/results/pipeline_outputs_azure.json   (Azure)
#   evaluation/results/pipeline_outputs_gcp.json     (GCP)
#
# Cost: ~$0.10–$0.30 per scenario (OpenAI API calls)
# Time: ~2–3 minutes per scenario (LLM calls)
# Total for 20 scenarios: ~$2–6, ~40–60 minutes

import json
import os
import sys
import time
import argparse
import traceback
from datetime import datetime
from pathlib import Path

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.pipeline import run_pipeline

EVAL_DIR    = Path(__file__).parent
RESULTS_DIR = EVAL_DIR / "results"

GOLDEN_SET_MAP = {
    "aws":   EVAL_DIR / "golden_set.json",
    "azure": EVAL_DIR / "golden_set_azure.json",
    "gcp":   EVAL_DIR / "golden_set_gcp.json",
}

OUTPUT_MAP = {
    "aws":   RESULTS_DIR / "pipeline_outputs.json",
    "azure": RESULTS_DIR / "pipeline_outputs_azure.json",
    "gcp":   RESULTS_DIR / "pipeline_outputs_gcp.json",
}


def run_for_cloud(cloud: str):
    golden_path = GOLDEN_SET_MAP[cloud]
    output_path = OUTPUT_MAP[cloud]

    if not golden_path.exists():
        print(f"ERROR: Golden set not found: {golden_path}")
        return

    with open(golden_path) as f:
        scenarios = json.load(f)

    # Resume support: if output file exists, skip already-completed scenarios
    existing = {}
    if output_path.exists():
        with open(output_path) as f:
            existing = json.load(f)
        print(f"Resuming: {len(existing)} scenarios already done, "
              f"{len(scenarios) - len(existing)} remaining.\n")

    results = dict(existing)

    for i, scenario in enumerate(scenarios):
        sid = scenario["id"]
        if sid in results:
            print(f"[{i+1}/{len(scenarios)}] {sid} — skipped (already done)")
            continue

        print(f"[{i+1}/{len(scenarios)}] {sid} — running pipeline...")
        print(f"  Query: {scenario['query'][:80]}...")

        start = time.time()
        try:
            output  = run_pipeline(scenario["query"])
            elapsed = round(time.time() - start, 1)
            results[sid] = {
                "scenario_id":  sid,
                "query":        scenario["query"],
                "elapsed_s":    elapsed,
                "generated_at": datetime.utcnow().isoformat(),
                **output,
            }
            cost = output.get("cost", {}).get("total_monthly_usd", "?")
            svcs = [s for layer in output.get("architecture", {}).get("layers", {}).values() for s in layer]
            print(f"  Done in {elapsed}s — cost: ${cost}/mo — "
                  f"services: {', '.join(svcs[:5])}{'...' if len(svcs) > 5 else ''}")

        except Exception as e:
            elapsed = round(time.time() - start, 1)
            print(f"  ERROR after {elapsed}s: {e}")
            results[sid] = {
                "scenario_id":  sid,
                "query":        scenario["query"],
                "elapsed_s":    elapsed,
                "generated_at": datetime.utcnow().isoformat(),
                "error":        str(e),
                "traceback":    traceback.format_exc(),
            }

        # Save after every scenario so progress isn't lost
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

        # Respect rate limits
        if i < len(scenarios) - 1:
            time.sleep(2)

    total  = len(scenarios)
    done   = sum(1 for v in results.values() if "error" not in v)
    failed = total - done
    print(f"\n{'='*60}")
    print(f"  [{cloud.upper()}] Complete: {done}/{total} succeeded, {failed} failed")
    print(f"  Output: {output_path}")
    print(f"{'='*60}")
    print(f"\nNext step: python -m evaluation.run_eval --cloud {cloud}")


def main():
    parser = argparse.ArgumentParser(
        description="Run the pipeline on golden set scenarios and save outputs."
    )
    parser.add_argument(
        "--cloud",
        choices=["aws", "azure", "gcp", "all"],
        default="aws",
        help="Which cloud's golden set to run (default: aws)",
    )
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)

    clouds = ["aws", "azure", "gcp"] if args.cloud == "all" else [args.cloud]

    for cloud in clouds:
        print(f"\n{'='*60}")
        print(f"  Generating outputs for: {cloud.upper()}")
        print(f"{'='*60}\n")
        run_for_cloud(cloud)


if __name__ == "__main__":
    main()
