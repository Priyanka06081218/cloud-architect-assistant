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

    # Step 1: Extract structured requirements from the query
    print("[1/6] Extracting requirements...")
    requirements = extract_requirements(user_query)

    # If the caller explicitly specified a cloud, honour it — don't let the
    # extractor's auto-detection override an API-level cloud_provider param.
    if cloud_provider:
        requirements["cloud_provider"] = cloud_provider.lower()

    # Resolve cloud provider early — used by cost estimation and diagram labels
    provider = get_provider(requirements.get("cloud_provider", "aws"))
    print(f"      Cloud: {provider.name}")

    # Step 2: Retrieve relevant context from ChromaDB.
    # The retriever queries cloud-specific collections:
    #   architecture_patterns       → AWS
    #   architecture_patterns_azure → Azure
    #   architecture_patterns_gcp   → GCP
    # If a cloud-specific collection is empty (data not yet collected),
    # the retriever returns "" and the LLM falls back to its training knowledge.
    print("[2/6] Retrieving context from vector DB...")
    arch_context     = retrieve_for_architecture(requirements)
    tradeoff_context = retrieve_for_tradeoffs(requirements)
    if arch_context:
        print(f"      RAG context retrieved for {provider.name}")
    else:
        print(f"      No RAG context for {provider.name} — LLM will use training knowledge")

    # Step 3: Generate architecture recommendation + trade-offs (LLM call 1)
    print("[3/6] Generating architecture recommendation...")
    arch_result = generate_architecture(requirements, arch_context, tradeoff_context)

    architecture = arch_result.get("architecture", {})

    # Step 4: Generate and evaluate candidate architectures.
    # The LLM produced one architecture. We generate 2-4 variants by swapping
    # compute/database choices, evaluate all on cost + latency + availability +
    # constraints, and find the Pareto-optimal set.
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

    # Step 5: Generate Terraform (LLM call 2, uses terraform_examples collection)
    print("[5/6] Generating Terraform...")
    all_services     = []
    for layer_svcs in architecture.get("layers", {}).values():
        all_services.extend(layer_svcs)

    terraform_context = retrieve_for_terraform(all_services, cloud_provider=requirements.get("cloud_provider", "aws"))
    terraform         = generate_terraform(architecture, terraform_context, provider=provider)

    # Step 6: Generate Mermaid diagram (no LLM)
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
    # End-to-end test — run this to verify the full pipeline works
    test_queries = [
        "Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday.",
        "I need a serverless API for a mobile app with 50,000 daily active users. Keep costs minimal.",
        "Design a HIPAA-compliant data pipeline on AWS for processing patient health records in real time.",
    ]

    for query in test_queries:
        print("\n" + "=" * 70)
        result = run_pipeline(query)
        print(f"\nScenario: {result['scenario_summary']}")
        print(f"Services: {result['architecture'].get('layers', {})}")
        print(f"Total cost: ${result['cost']['total_monthly_usd']}/month")
        print(f"Trade-offs: {len(result['trade_offs'])} decisions")
        print(f"Terraform lines: {len(result['terraform'].splitlines())}")
        print(f"Diagram nodes: {result['diagram'].count('-->')}")
