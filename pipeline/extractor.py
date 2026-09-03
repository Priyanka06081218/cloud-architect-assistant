# pipeline/extractor.py
#
# Parses a natural language query into structured requirements.
# Every other step in the pipeline reads from this output.
#
# Example input:
#   "An e-commerce app needs to handle 500k concurrent users with low latency"
#
# Example output:
#   {
#     "scale":         "500k concurrent users",
#     "workload_type": "e-commerce web application",
#     "constraints":   ["low latency", "high availability"],
#     "budget":        None,
#     "raw_query":     "An e-commerce app needs to handle..."
#   }

import json
import re
from pipeline.generator import _llm_call

# Explicit cloud keywords — checked AFTER the LLM extraction as a deterministic
# override.  Prevents the LLM from defaulting to "aws" when the query says "on Azure"
# or "on GCP".  More specific terms come first so "gke" doesn't shadow "google cloud".
_CLOUD_KEYWORDS = {
    "azure": [
        "on azure", "in azure", "using azure", "azure architecture",
        "azure functions", "azure kubernetes", "cosmos db", "aks",
        "service bus", "event hub", "azure sql", "azure openai",
        "azure machine learning", "azure devops", "microsoft azure",
        "azure monitor", "azure blob", "azure container",
    ],
    "gcp": [
        "on gcp", "in gcp", "using gcp", "gcp architecture",
        "google cloud", "google cloud platform", "cloud run", "gke",
        "bigquery", "pub/sub", "cloud spanner", "vertex ai",
        "cloud functions", "firestore", "cloud storage", "dataflow",
        "google kubernetes engine", "cloud bigtable", "memorystore",
    ],
    "aws": [
        "on aws", "in aws", "using aws", "aws architecture",
        "amazon web services", "ec2 ", "aws lambda", "dynamodb",
        "s3 bucket", "cloudfront", "elasticache", "rds ", "fargate",
        "kinesis", "amazon ecs", "amazon eks",
    ],
}


def _override_cloud_from_keywords(query: str) -> str | None:
    """Deterministically detect cloud from explicit keywords in the query.

    Returns "aws" | "azure" | "gcp" if found, else None (let LLM result stand).
    Checked after LLM extraction to correct cases where the LLM defaults to "aws"
    even when the query says "on Azure" or "on GCP".
    """
    q = query.lower()
    for cloud, keywords in _CLOUD_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return cloud
    return None


def extract_requirements(user_query: str) -> dict:
    """Parse a natural language query into structured requirements."""

    prompt = f"""You are parsing a cloud architecture request. Extract the following fields from the query.
Return ONLY valid JSON, nothing else.

Fields to extract:
- scale: expected load (users, requests, data volume). Use "not specified" if missing.
- workload_type: type of application (e.g. "e-commerce web app", "data pipeline", "REST API")
- constraints: list of requirements like HIPAA, multi-region, low latency, cost-sensitive. Empty list if none.
- budget: monthly budget if mentioned (e.g. "$500/month"). null if not mentioned.
- budget_cap_usd: extract the numeric monthly budget limit as a float. null if not mentioned.
  Examples: "under $500/month" → 500.0, "budget: $1,200" → 1200.0, not mentioned → null
- compliance_requirements: list of compliance standards explicitly required.
  Only include: "hipaa", "soc2", "pci-dss", "gdpr", "fedramp". Empty list if none mentioned.
- requires_multi_region: true if the query explicitly asks for multi-region, cross-region, or geographic redundancy. false otherwise.
- requires_realtime: true if the query mentions real-time, sub-100ms, low latency, or streaming. false otherwise.
- min_availability_percent: extract numeric SLA if mentioned (e.g. "99.99% uptime" → 99.99). null if not mentioned.
- cloud_provider: which cloud the user wants. One of "aws", "azure", "gcp", "agnostic".
  "aws" if they mention AWS, Amazon, or no preference. "azure" if they mention Azure or Microsoft cloud.
  "gcp" if they mention GCP, Google Cloud, or BigQuery. "agnostic" only if they explicitly say multi-cloud or cloud-agnostic.

Query: {user_query}

Return JSON only:
{{
  "scale": "...",
  "workload_type": "...",
  "constraints": [],
  "budget": null,
  "budget_cap_usd": null,
  "compliance_requirements": [],
  "requires_multi_region": false,
  "requires_realtime": false,
  "min_availability_percent": null,
  "cloud_provider": "aws"
}}"""

    raw = _llm_call(prompt, temperature=0, json_mode=True)

    match = re.search(r'\{.*\}', raw, re.DOTALL)
    parsed = json.loads(match.group() if match else raw)

    parsed["raw_query"] = user_query

    # Deterministic override: if the query explicitly names a cloud, trust that
    # over the LLM — the LLM template defaults to "aws" and can misclassify
    # queries like "Build an event-driven order processor on Azure...".
    detected = _override_cloud_from_keywords(user_query)
    if detected:
        parsed["cloud_provider"] = detected

    return parsed


if __name__ == "__main__":
    test_query = "Design an AWS architecture for a healthcare app with 10,000 daily users. Must be HIPAA compliant and stay under $1,000/month."
    result = extract_requirements(test_query)
    print(json.dumps(result, indent=2))