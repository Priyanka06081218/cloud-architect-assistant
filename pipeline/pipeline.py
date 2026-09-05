# pipeline/pipeline.py
#
# Full pipeline orchestration.
#
# Flow:
#   user query
#     → extract structured requirements           (extractor.py)
#     → retrieve RAG context from ChromaDB        (retriever.py)
#     → generate primary architecture + LLM call  (generator.py)
#     → IR extraction → candidate variants        (ir.py, candidates.py)
#     → evaluate each: cost + latency + avail     (evaluator.py)
#     → Pareto frontier across candidates         (evaluator.find_pareto)
#     → generate Terraform                        (generator.py, LLM call 2)
#     → generate Mermaid diagram                  (diagram.py)
#     → return primary + alternatives + scores

import json
from pipeline.extractor          import extract_requirements
from pipeline.retriever          import retrieve_for_architecture, retrieve_for_tradeoffs, retrieve_for_terraform
from pipeline.generator          import generate_architecture, generate_terraform
from pipeline.cost_calculator    import estimate_cost
from pipeline.diagram            import generate_mermaid
from pipeline.constraint_engine  import validate_constraints
from pipeline.cloud_providers    import get_provider
from pipeline.performance_model  import estimate_performance
from pipeline.candidates         import generate_candidates
from pipeline.evaluator          import evaluate, score_relative, find_pareto
from pipeline.observability      import log_langfuse_status

try:
    from langfuse.decorators import observe
except ImportError:
    def observe(*args, **kwargs):
        def decorator(fn): return fn
        return decorator if args and callable(args[0]) else decorator


@observe(name="cloud_architect_pipeline")
def run_pipeline(user_query: str, cloud_provider: str | None = None) -> dict:
    """Run the full RAG pipeline for a given user query.

    Args:
        user_query:     natural language cloud architecture request
        cloud_provider: optional explicit cloud override ('aws', 'azure', 'gcp').
                        If omitted, the cloud is auto-detected from the query text.

    Returns:
        Full structured response with all 6 output sections.
    """

    print(f"\n[Pipeline] Query: {user_query[:80]}...")

    print("[1/6] Extracting requirements...")
    requirements = extract_requirements(user_query)

    # If the caller explicitly specified a cloud, honour it — don't let the
    # extractor's auto-detection override an API-level cloud_provider param.
    if cloud_provider:
        requirements["cloud_provider"] = cloud_provider.lower()

    # Resolve cloud provider early — used by cost estimation and diagram labels
    provider = get_provider(requirements.get("cloud_provider", "aws"))
    print(f"      Cloud: {provider.name}")

    # If a cloud-specific collection is empty, the retriever returns "" and the LLM
    # falls back to its training knowledge — no hard failure.
    print("[2/6] Retrieving context from vector DB...")
    arch_context     = retrieve_for_architecture(requirements)
    tradeoff_context = retrieve_for_tradeoffs(requirements)
    if arch_context:
        print(f"      RAG context retrieved for {provider.name}")
    else:
        print(f"      No RAG context for {provider.name} — LLM will use training knowledge")

    print("[3/6] Generating architecture recommendation...")
    arch_result = generate_architecture(requirements, arch_context, tradeoff_context)

    architecture = arch_result.get("architecture", {})

    print("[4/6] Evaluating candidate architectures...")
    raw_candidates = generate_candidates(architecture, requirements)

    evaluated = []
    for cand in raw_candidates:
        ev = evaluate(cand["architecture"], requirements)
        evaluated.append({**cand, "evaluation": ev})

    score_relative(evaluated)  # adds "scores" key to each, normalized across the set

    pareto_indices = find_pareto(evaluated)
    primary_eval   = evaluated[0]["evaluation"]  # LLM-recommended candidate

    cost        = primary_eval["cost"]
    performance = primary_eval["performance"]
    violations  = primary_eval["violations"]     # already dicts

    alternatives = [
        {
            "label":       e["label"],
            "change":      e["change"],
            "is_primary":  e["is_primary"],
            "is_pareto":   i in pareto_indices,
            "cost":        e["evaluation"]["cost"],
            "performance": e["evaluation"]["performance"],
            "scores":      e["scores"],
            "architecture": e["architecture"],
        }
        for i, e in enumerate(evaluated)
    ]

    print("[5/6] Generating Terraform...")
    all_services     = []
    for layer_svcs in architecture.get("layers", {}).values():
        all_services.extend(layer_svcs)

    terraform_context = retrieve_for_terraform(all_services, cloud_provider=requirements.get("cloud_provider", "aws"))
    terraform         = generate_terraform(architecture, terraform_context, provider=provider)

    print("[6/6] Generating architecture diagram...")
    diagram = generate_mermaid(architecture)

    response = {
        "scenario_summary":      arch_result.get("scenario_summary", ""),
        "cloud_provider":        provider.name,
        "architecture":          architecture,
        "trade_offs":            arch_result.get("trade_offs", []),
        "cost":                  cost,
        "performance":           performance,
        "constraint_violations": violations,
        "alternatives":          alternatives,
        "pareto_indices":        pareto_indices,
        "terraform":             terraform,
        "diagram":               diagram,
    }

    print("[Pipeline] Done.")
    return response


if __name__ == "__main__":
    # End-to-end smoke test — one query per cloud to catch regressions in any provider.
    test_cases = [
        ("AWS",   "Design an e-commerce platform on AWS for 100k concurrent users with 99.99% availability.", "aws"),
        ("Azure", "Build a HIPAA-compliant patient records system on Azure with encryption and audit logging.", "azure"),
        ("GCP",   "Design a real-time IoT data pipeline on GCP for 10,000 sensors with sub-5s query latency.", "gcp"),
    ]

    for label, query, cloud in test_cases:
        print("\n" + "=" * 70)
        print(f"[{label}] {query[:70]}...")
        result = run_pipeline(query, cloud_provider=cloud)
        print(f"  Cloud:      {result['cloud_provider']}")
        print(f"  Scenario:   {result['scenario_summary'][:80]}")
        print(f"  Cost:       ${result['cost']['total_monthly_usd']}/month")
        print(f"  Services:   {sum(len(v) for v in result['architecture'].get('layers', {}).values())} across {len(result['architecture'].get('layers', {}))} layers")
        print(f"  Trade-offs: {len(result['trade_offs'])}")
        print(f"  Violations: {len(result['constraint_violations'])}")
        print(f"  Terraform:  {len(result['terraform'].splitlines())} lines")
