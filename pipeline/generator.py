# pipeline/generator.py
#
# Two LLM calls:
#   1. generate_architecture() — architecture recommendation + trade-offs
#   2. generate_terraform()    — Terraform HCL for the recommended services
#
# Model routing (env-controlled):
#   VLLM_BASE_URL set  → Modal vLLM endpoint (Priyanka1218/cloud-architect-llama)
#   FINETUNE_MODEL set → local HuggingFace pipeline
#   neither            → OpenAI GPT-4o-mini

import json
import logging
from config import FINETUNE_MODEL, VLLM_BASE_URL

try:
    from langfuse.decorators import observe, langfuse_context
    _LANGFUSE_AVAILABLE = True
except ImportError:
    def observe(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator if args and callable(args[0]) else decorator
    class _NoopCtx:
        def update_current_observation(self, **kwargs): pass
    langfuse_context = _NoopCtx()
    _LANGFUSE_AVAILABLE = False

log = logging.getLogger(__name__)

_hf_pipeline = None


def _get_hf_pipeline():
    global _hf_pipeline
    if _hf_pipeline is not None:
        return _hf_pipeline
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
        model_path = "models/cloud-architect-merged" if FINETUNE_MODEL == "local" else "Priyanka1218/cloud-architect-llama"
        log.info(f"Loading fine-tuned model: {model_path}")
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            device_map="auto",
        )
        _hf_pipeline = pipeline(
            "text-generation", model=model, tokenizer=tokenizer,
            max_new_tokens=2048, temperature=0.3, do_sample=True, return_full_text=False,
        )
        log.info("Fine-tuned model loaded.")
    except Exception as e:
        log.error(f"Failed to load fine-tuned model: {e}. Falling back to GPT-4o-mini.")
        _hf_pipeline = None
    return _hf_pipeline


@observe(as_type="generation")
def _llm_call(prompt: str, temperature: float = 0.3, json_mode: bool = True) -> str:
    import os

    if VLLM_BASE_URL:
        import requests as _req
        model_name = FINETUNE_MODEL or "cloud-architect-llama"
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt + ("\n\nRespond with ONLY valid JSON, no extra text." if json_mode else "")}],
            "temperature": temperature,
            "max_tokens": 1024,
        }
        resp = _req.post(VLLM_BASE_URL, json=payload, timeout=120)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        langfuse_context.update_current_observation(
            model=model_name,
            metadata={"backend": "vllm", "temperature": temperature, "json_mode": json_mode},
        )
        return content

    if FINETUNE_MODEL:
        pipe = _get_hf_pipeline()
        if pipe:
            if json_mode:
                prompt = prompt + "\n\nRespond with ONLY valid JSON, no extra text."
            result = pipe(prompt)
            langfuse_context.update_current_observation(
                model=FINETUNE_MODEL, metadata={"backend": "hf_pipeline"},
            )
            return result[0]["generated_text"].strip()

    from openai import OpenAI
    from config import OPENAI_API_KEY
    client = OpenAI(api_key=OPENAI_API_KEY)
    kwargs = dict(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    langfuse_context.update_current_observation(
        model="gpt-4o-mini",
        usage={"input": response.usage.prompt_tokens, "output": response.usage.completion_tokens},
        metadata={"backend": "openai", "temperature": temperature, "json_mode": json_mode},
    )
    return response.choices[0].message.content.strip()


def _build_compute_rules(requirements: dict) -> str:
    """Hard engineering limits that rule out specific compute choices.
    These are not style preferences — they're limits like Lambda's 15-min timeout
    or lack of GPU support that make certain services technically inappropriate.
    """
    cloud    = requirements.get("cloud_provider", "aws").lower()
    rules    = []
    raw      = requirements.get("raw_query", "").lower()
    scale    = str(requirements.get("scale", "")).lower()
    wtype    = str(requirements.get("workload_type", "")).lower()
    constr   = " ".join(requirements.get("constraints", [])).lower()
    combined = raw + " " + scale + " " + wtype + " " + constr

    latency_triggers  = ["sub-10ms", "sub-50ms", "<10ms", "<50ms", "10ms", "50ms",
                         "no cold start", "always warm", "ultra-low latency"]
    long_job_triggers = ["hour", "hours", "etl", "fine-tun", "training", "batch processing",
                         "500gb", "1tb", "large dataset", "nightly", "weekly job"]
    gpu_triggers      = ["gpu", "cuda", "fine-tun", "llm training", "model training",
                         "deep learning", "neural network training"]
    high_tps_triggers = ["50,000 transactions", "50000 transactions", "50k transactions",
                         "100,000 tps", "100k tps", "high-frequency", "hft"]
    multiregion_triggers = ["multi-region", "active-active", "global", "failover",
                            "disaster recovery", "rto", "multi region"]

    if cloud == "aws":
        if any(t in combined for t in latency_triggers):
            rules.append(
                "DO NOT use AWS Lambda — cold starts (50–500 ms) violate the stated latency requirement. "
                "Use ECS Fargate, EKS, or EC2 with auto-scaling instead."
            )
        if any(t in combined for t in long_job_triggers):
            rules.append(
                "DO NOT use AWS Lambda for long-running workloads — maximum execution time is 15 minutes. "
                "Use AWS Batch, ECS tasks, EMR, Glue, or SageMaker Training Jobs instead."
            )
        if any(t in combined for t in gpu_triggers):
            rules.append(
                "DO NOT use AWS Lambda — no GPU support. "
                "Use EC2 P/G instances, SageMaker Training Jobs, or AWS Batch with GPU instances."
            )
        if any(t in combined for t in high_tps_triggers):
            rules.append(
                "DO NOT use AWS Lambda as primary compute above ~5,000 TPS. "
                "Use ECS Fargate or EKS with horizontal auto-scaling."
            )
        if any(t in combined for t in multiregion_triggers):
            rules.append(
                "REQUIRED for multi-region: include Route 53 with health-check routing, "
                "Aurora Global Database or DynamoDB Global Tables for cross-region data."
            )
        compliance_map = {
            "hipaa":   "AWS KMS, AWS CloudTrail, Amazon GuardDuty, VPC with private subnets",
            "pci":     "AWS KMS, AWS WAF, AWS CloudTrail, Amazon GuardDuty, VPC with private subnets",
            "pci-dss": "AWS KMS, AWS WAF, AWS CloudTrail, Amazon GuardDuty, VPC with private subnets",
            "soc2":    "AWS CloudTrail, Amazon GuardDuty, AWS Config, VPC",
            "soc 2":   "AWS CloudTrail, Amazon GuardDuty, AWS Config, VPC",
            "gdpr":    "AWS KMS, AWS CloudTrail, VPC, region-specific deployments in EU",
        }

    elif cloud == "azure":
        if any(t in combined for t in latency_triggers):
            rules.append(
                "DO NOT use Azure Functions for sub-50 ms latency — cold starts can reach 1–3 seconds. "
                "Use Azure Container Apps (always-on) or AKS instead."
            )
        if any(t in combined for t in long_job_triggers):
            rules.append(
                "DO NOT use Azure Functions for long-running jobs — default timeout is 5 minutes (max 60 min on Premium). "
                "Use Azure Container Apps Jobs, Azure Batch, or Azure Machine Learning pipelines instead."
            )
        if any(t in combined for t in gpu_triggers):
            rules.append(
                "DO NOT use Azure Functions — no GPU support. "
                "Use Azure Virtual Machines (NC/NV series) or Azure Machine Learning compute clusters."
            )
        if any(t in combined for t in high_tps_triggers):
            rules.append(
                "DO NOT use Azure Functions as primary compute above ~5,000 TPS. "
                "Use Azure Container Apps or AKS with KEDA-based auto-scaling."
            )
        if any(t in combined for t in multiregion_triggers):
            rules.append(
                "REQUIRED for multi-region: include Azure Traffic Manager or Azure Front Door for global routing, "
                "Azure Cosmos DB (multi-region writes) or Azure Database for PostgreSQL with geo-replication."
            )
        compliance_map = {
            "hipaa":   "Azure Key Vault, Azure Monitor (Activity Logs), Microsoft Defender for Cloud, Azure Virtual Network",
            "pci":     "Azure Key Vault, Azure WAF, Azure Monitor, Microsoft Defender for Cloud, Azure Virtual Network",
            "pci-dss": "Azure Key Vault, Azure WAF, Azure Monitor, Microsoft Defender for Cloud, Azure Virtual Network",
            "soc2":    "Azure Monitor, Microsoft Defender for Cloud, Azure Policy, Azure Virtual Network",
            "gdpr":    "Azure Key Vault, Azure Monitor, Azure Virtual Network, EU region deployments",
        }

    else:  # gcp
        if any(t in combined for t in latency_triggers):
            rules.append(
                "DO NOT use Cloud Functions for sub-50 ms latency — cold starts can reach 1–2 seconds. "
                "Use Cloud Run (min-instances=1) or GKE instead."
            )
        if any(t in combined for t in long_job_triggers):
            rules.append(
                "DO NOT use Cloud Functions for long-running jobs — maximum timeout is 60 minutes. "
                "Use Cloud Run Jobs, Cloud Batch, or Vertex AI Pipelines instead."
            )
        if any(t in combined for t in gpu_triggers):
            rules.append(
                "DO NOT use Cloud Functions — no GPU support. "
                "Use Compute Engine (A2/N1 GPU instances) or Vertex AI Training."
            )
        if any(t in combined for t in high_tps_triggers):
            rules.append(
                "DO NOT use Cloud Functions as primary compute above ~5,000 TPS. "
                "Use Cloud Run with concurrency tuning or GKE with Horizontal Pod Autoscaler."
            )
        if any(t in combined for t in multiregion_triggers):
            rules.append(
                "REQUIRED for multi-region: include Cloud Load Balancing (global) with Cloud CDN, "
                "Cloud Spanner or Firestore for globally distributed data."
            )
        if any(t in combined for t in ["iot", "connected device", "smart city", "sensor data",
                                        "device telemetry", "million device"]):
            rules.append(
                "REQUIRED for IoT: include Pub/Sub (device ingestion), Dataflow (stream processing), "
                "and Bigtable (time-series storage)."
            )
        compliance_map = {
            "hipaa":   "Cloud KMS, Secret Manager, Cloud Audit Logs, Security Command Center, VPC Network",
            "pci":     "Cloud KMS, Secret Manager, Cloud Armor (WAF), Cloud Audit Logs, Security Command Center, VPC Network",
            "pci-dss": "Cloud KMS, Secret Manager, Cloud Armor (WAF), Cloud Audit Logs, Security Command Center, VPC Network",
            "soc2":    "Secret Manager, Cloud Audit Logs, Security Command Center, VPC Network, Cloud Asset Inventory",
            "gdpr":    "Cloud KMS, Secret Manager, Cloud Audit Logs, VPC Network, EU region deployments",
        }

    for standard, required_svcs in compliance_map.items():
        if standard in combined:
            rules.append(
                f"REQUIRED for {standard.upper()} compliance: include {required_svcs}. "
                f"The reasoning MUST explicitly mention {standard.upper()}."
            )

    if not rules:
        rules.append(
            "No hard compute constraints detected — choose services based on "
            "cost, scalability, and operational simplicity."
        )

    return "\n".join(f"  {r}" for r in rules)


def _build_service_hints(requirements: dict) -> str:
    """Positive inclusion hints: services that evaluation data shows are
    systematically omitted for a given workload type and cloud.

    Driven by the extractor's structured output (workload_type, compliance_requirements,
    scale, requires_realtime, budget_cap_usd) — not raw keyword matching on the query.
    """
    cloud      = requirements.get("cloud_provider", "aws").lower()
    wtype      = str(requirements.get("workload_type", "")).lower()
    scale      = str(requirements.get("scale", "")).lower()
    compliance = [s.lower() for s in requirements.get("compliance_requirements", [])]
    constraints = " ".join(requirements.get("constraints", [])).lower()
    budget     = requirements.get("budget_cap_usd")

    # Derived flags — trust the extractor's interpretation rather than re-parsing raw text
    is_high_scale  = any(x in scale for x in ["500k", "million", "high", "concurrent", "large"])
    is_ml          = any(x in wtype for x in ["ml", "machine learning", "ai", "llm", "inference", "training", "model"])
    is_data        = any(x in wtype for x in ["data pipeline", "etl", "analytics", "warehouse", "streaming", "iot", "telemetry", "ingestion"])
    is_web         = any(x in wtype for x in ["web", "e-commerce", "ecommerce", "cms", "frontend", "portal"])
    is_static      = any(x in wtype for x in ["static", "jamstack"]) or "static" in constraints
    is_api         = any(x in wtype for x in ["api", "rest", "microservice", "backend"])
    is_gaming      = any(x in wtype for x in ["gaming", "game", "leaderboard"])
    is_serverless  = any(x in wtype for x in ["serverless", "event-driven", "function"])
    is_llm         = any(x in wtype for x in ["llm", "chatbot", "language model", "gpt", "generative ai", "openai"])
    has_compliance = bool(compliance) or any(x in constraints for x in ["security", "zero-trust", "enterprise", "regulated"])

    hints = []

    if budget and budget < 100:
        hints.append(
            f"BUDGET CONSTRAINT: ~${int(budget)}/month — use fully managed serverless services. "
            "No Kubernetes, no container orchestration, no multiple load balancers unless required."
        )

    if cloud == "azure":
        if has_compliance:
            hints.append("INCLUDE Microsoft Entra ID in 'security' (identity, SSO, MFA).")
            hints.append("INCLUDE Azure Key Vault in 'security' (secrets, certificates, encryption keys).")
            hints.append("INCLUDE Microsoft Defender for Cloud in 'security' (threat protection, compliance posture).")

        if is_llm:
            hints.append("INCLUDE Azure OpenAI Service in 'compute' for LLM inference (GPT-4, embeddings).")

        if is_ml and not is_llm:
            hints.append("INCLUDE Azure Machine Learning in 'compute' for model training and MLOps.")

        if is_static:
            hints.append(
                "STATIC SITE: Use Azure Blob Storage (static hosting) + Azure CDN ONLY. "
                "No App Service, AKS, VMs, or load balancers."
            )
        elif is_web:
            hints.append("INCLUDE Azure CDN in 'edge'. Use Azure Front Door only for multi-region global routing.")
            hints.append("INCLUDE Azure App Service in 'compute' for the web application.")

        if is_serverless and not is_web:
            hints.append("INCLUDE Azure Functions in 'compute' for serverless event-driven processing.")

        if is_high_scale or is_gaming:
            hints.append("INCLUDE AKS in 'compute' for container orchestration at high scale.")
            hints.append("INCLUDE Azure Cache for Redis in 'database' for low-latency caching and sessions.")

        if is_data:
            hints.append("INCLUDE Azure Event Hubs in 'messaging' for high-throughput data ingestion.")
            hints.append("INCLUDE Azure Data Lake Storage Gen2 in 'database' for scalable data lake storage.")
            hints.append("INCLUDE Azure Data Factory in 'compute' for ETL/ELT orchestration.")

        if is_data or is_ml or is_high_scale:
            hints.append(
                "INCLUDE Azure Blob Storage in 'database' or 'storage' for object storage "
                "(model artifacts, raw data, backups). Use 'Azure Blob Storage' — "
                "not ADLS Gen2 unless hierarchical namespace is explicitly required."
            )

        if is_api or has_compliance or is_llm:
            hints.append("INCLUDE Azure API Management in 'networking' for API gateway and rate limiting.")

    elif cloud == "gcp":
        if has_compliance:
            hints.append(
                "REQUIRED: Cloud Secret Manager MUST appear in 'security' "
                "(API keys, database passwords, TLS certificates)."
            )
            hints.append("INCLUDE Cloud Armor in 'security' for WAF rules and DDoS protection.")

        if is_static:
            hints.append(
                "STATIC SITE: Use Cloud Storage (GCS static hosting) + Cloud CDN ONLY. "
                "No Cloud Run, Cloud SQL, App Engine, or GKE."
            )
        elif is_web:
            hints.append("INCLUDE Cloud Run in 'compute' as the primary managed container platform.")
            hints.append("INCLUDE Cloud SQL (PostgreSQL or MySQL) in 'database'.")

        if is_ml:
            hints.append("INCLUDE Vertex AI in 'compute' for model training, deployment, and inference.")
            hints.append("INCLUDE Cloud Storage in 'database' for training data and model artifacts.")

        if is_serverless and not is_web:
            hints.append("INCLUDE Firestore in 'database' for serverless NoSQL document storage.")

        if is_high_scale or is_gaming:
            hints.append("INCLUDE GKE in 'compute' for container orchestration at high scale.")
            hints.append("INCLUDE Memorystore for Redis in 'database' for low-latency caching.")

        if is_data:
            hints.append("INCLUDE Cloud Storage in 'storage' for data lake and raw data ingestion.")
            hints.append("INCLUDE Dataflow in 'compute' for managed Apache Beam streaming and batch pipelines.")

    return "\n".join(f"  {h}" for h in hints) if hints else ""


def _cloud_display_name(requirements: dict) -> str:
    cloud = requirements.get("cloud_provider", "aws").lower()
    return {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}.get(cloud, "AWS")


def _networking_anchor(requirements: dict) -> str:
    cloud = requirements.get("cloud_provider", "aws").lower()
    return {"aws": "VPC", "azure": "Azure Virtual Network", "gcp": "VPC Network"}.get(cloud, "VPC")


def _cloud_service_examples(cloud: str) -> dict:
    """Per-cloud service vocabulary injected into the prompt JSON template.
    Anchors the LLM to the correct service names — without this, it tends to
    default to AWS names even when generating Azure or GCP architectures.
    """
    examples = {
        "AWS": {
            "compute":    "ECS Fargate, AWS Lambda, EC2 Auto Scaling, EKS",
            "database":   "Amazon RDS (Aurora), Amazon DynamoDB, Amazon ElastiCache",
            "messaging":  "Amazon SQS, Amazon SNS, Amazon Kinesis Data Streams",
            "monitoring": "Amazon CloudWatch, AWS X-Ray, AWS CloudTrail",
            "security":   "AWS KMS, AWS WAF, Amazon GuardDuty, AWS CloudTrail, IAM roles, AWS Shield",
        },
        "Azure": {
            "compute":    "Azure Container Apps, Azure Functions, AKS, Azure App Service",
            "database":   "Azure Database for PostgreSQL, Azure Cosmos DB, Azure Cache for Redis",
            "messaging":  "Azure Service Bus, Azure Event Hubs, Azure Event Grid",
            "monitoring": "Azure Monitor, Azure Application Insights, Azure Log Analytics",
            "security":   "Azure Key Vault, Azure WAF, Microsoft Defender for Cloud, Microsoft Entra ID, Azure DDoS Protection",
        },
        "GCP": {
            "compute":    "Cloud Run, Google Kubernetes Engine (GKE), Cloud Functions, Compute Engine",
            "database":   "Cloud SQL (PostgreSQL), Cloud Spanner, Firestore, Memorystore for Redis",
            "messaging":  "Cloud Pub/Sub, Dataflow, Cloud Tasks",
            "monitoring": "Cloud Monitoring, Cloud Logging, Cloud Trace",
            "security":   "Cloud KMS, Cloud Armor, Secret Manager, Security Command Center, VPC Service Controls",
        },
    }
    return examples.get(cloud, examples["AWS"])


def generate_architecture(requirements: dict, arch_context: str, tradeoff_context: str) -> dict:
    arch_context     = arch_context[:2000] if arch_context else ""
    tradeoff_context = tradeoff_context[:1500] if tradeoff_context else ""

    compute_rules = _build_compute_rules(requirements)
    hints_raw     = _build_service_hints(requirements)
    service_hints_block = (
        "SERVICE INCLUSION HINTS — strongly prefer these specific services:\n" + hints_raw + "\n"
    ) if hints_raw else ""

    cloud        = _cloud_display_name(requirements)
    net_anchor   = _networking_anchor(requirements)
    svc_examples = _cloud_service_examples(cloud)

    prompt = f"""
You are a senior {cloud} Solutions Architect. A client has the following requirement:

"{requirements['raw_query']}"

Extracted details:
- Cloud: {cloud}
- Scale: {requirements['scale']}
- Workload type: {requirements['workload_type']}
- Constraints: {', '.join(requirements.get('constraints', [])) or 'none specified'}
- Budget: {requirements.get('budget') or 'not specified'}

CRITICAL: You MUST recommend ONLY {cloud} services. Every service name must be a real {cloud} service.

ARCHITECTURE INVARIANT:
  {net_anchor} (with public and private subnets) MUST appear in the "networking" layer.

COMPUTE SELECTION RULES:
{compute_rules}
{service_hints_block}Use the context below from {cloud} documentation and architecture guides to inform your recommendation.

CONTEXT:
{arch_context}

TRADE-OFF CONTEXT:
{tradeoff_context}

Return ONLY valid JSON in exactly this structure:
{{
  "scenario_summary": "one sentence summary of what the client needs",
  "architecture": {{
    "layers": {{
      "edge":       ["list of {cloud} edge/CDN services"],
      "networking": ["load balancers, API gateway, {net_anchor}"],
      "compute":    ["{svc_examples['compute']} — use {cloud}-native services only"],
      "database":   ["{svc_examples['database']} — use {cloud}-native services only"],
      "messaging":  ["{svc_examples['messaging']} if needed"],
      "monitoring": ["{svc_examples['monitoring']}"],
      "security":   ["{svc_examples['security']} — required whenever compliance or security controls apply"]
    }},
    "reasoning": "2-3 paragraphs explaining why these {cloud} services were chosen, covering scalability, reliability, cost, and compliance (name the standard explicitly if applicable)"
  }},
  "trade_offs": [
    {{
      "decision":       "Service A vs Service B",
      "chose":          "Service A",
      "reason":         "why Service A fits better for this use case",
      "when_to_switch": "specific conditions where Service B would be better"
    }}
  ]
}}

Include 2-4 trade_offs covering the most important decisions (compute, database, networking).
If compliance rules above require specific security services, they MUST appear in the "security" layer.
All services in every layer MUST be {cloud} services — no cross-cloud contamination.
"""

    result = json.loads(_llm_call(prompt, temperature=0.3, json_mode=True))

    # Guarantee the networking anchor appears — the LLM sometimes omits it.
    layers     = result.get("architecture", {}).get("layers", {})
    networking = layers.get("networking", [])
    anchor     = _networking_anchor(requirements)
    if not any("vpc" in s.lower() for s in networking):
        layers["networking"] = [anchor] + networking

    return result


def generate_terraform(architecture: dict, terraform_context: str, provider=None) -> str:
    all_services = []
    for layer_services in architecture.get("layers", {}).values():
        all_services.extend(layer_services)

    if provider and provider.provider_id == "azure":
        cloud_name    = "Azure"
        provider_hint = provider.terraform_provider
        network_note  = "Include an Azure Virtual Network with public and private subnets."
    elif provider and provider.provider_id == "gcp":
        cloud_name    = "GCP"
        provider_hint = provider.terraform_provider
        network_note  = "Include a VPC Network with public and private subnets."
    else:
        cloud_name    = "AWS"
        provider_hint = 'provider "aws" { region = var.aws_region }'
        network_note  = "Include a VPC with public and private subnets."

    context_block = f"\nTERRAFORM REFERENCE EXAMPLES:\n{terraform_context}" if terraform_context else ""

    prompt = f"""
You are a Terraform expert. Generate production-ready Terraform HCL for these {cloud_name} services:
{', '.join(all_services)}

Provider block to use:
{provider_hint}
{context_block}

Requirements:
- Use variables for configurable values (region, instance types, names)
- {network_note}
- Add security groups / network security groups with least-privilege rules
- Add meaningful comments explaining each resource
- Use Terraform best practices (tags, outputs, data sources)
- Use only {cloud_name}-native resources and the correct Terraform provider

Return ONLY valid Terraform HCL code. No explanations, no markdown fences.
"""

    return _llm_call(prompt, temperature=0.2, json_mode=False)


if __name__ == "__main__":
    from pipeline.extractor import extract_requirements
    from pipeline.retriever import retrieve_for_architecture, retrieve_for_tradeoffs

    query        = "Design an AWS architecture for an e-commerce app with 100k concurrent users"
    requirements = extract_requirements(query)
    arch_context     = retrieve_for_architecture(requirements)
    tradeoff_context = retrieve_for_tradeoffs(requirements)
    result = generate_architecture(requirements, arch_context, tradeoff_context)
    print(json.dumps(result, indent=2))
