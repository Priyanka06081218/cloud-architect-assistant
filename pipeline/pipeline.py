# pipeline/pipeline.py
#
# Orchestrates all pipeline steps into a single function.
#
# Flow:
#   user query
#     → extract requirements
#     → retrieve RAG context (3 collections in parallel)
#     → generate architecture + trade-offs (LLM call 1)
#     → estimate cost (pricing table, no LLM)
#     → generate terraform (LLM call 2)
#     → generate diagram (no LLM, pure logic)
#     → return full structured JSON response

import json
from pipeline.extractor          import extract_requirements
from pipeline.retriever          import retrieve_for_architecture, retrieve_for_tradeoffs, retrieve_for_terraform
from pipeline.generator          import generate_architecture, generate_terraform
from pipeline.cost_calculator    import estimate_cost
from pipeline.diagram            import generate_mermaid
from pipeline.constraint_engine  import validate_constraints
from pipeline.cloud_providers    import get_provider
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

    # Step 4: Estimate costs — pass requirements so the calculator can apply
    # scale-aware multipliers (number of instances scales with user load).
    print("[4/6] Estimating costs...")
    cost = estimate_cost(architecture, requirements, provider=provider)

    # Step 4b: Validate constraints — check the recommendation against the
    # user's stated constraints (budget, compliance, availability, latency,
    # multi-region). This is deterministic — no LLM involved.
    print("[4b] Validating constraints...")
    violations = validate_constraints(requirements, architecture, cost)

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

    # Assemble final response
    response = {
        "scenario_summary":      arch_result.get("scenario_summary", ""),
        "cloud_provider":        provider.name,
        "architecture":          architecture,
        "trade_offs":            arch_result.get("trade_offs", []),
        "cost":                  cost,
        "constraint_violations": [v.to_dict() for v in violations],
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
