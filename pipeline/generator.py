# pipeline/generator.py
#
# Two LLM calls using retrieved RAG context:
#   1. generate_architecture() → architecture recommendation + trade-offs
#   2. generate_terraform()    → Terraform HCL for the recommended services
#
# Uses the fine-tuned LLaMA 3.1 8B model (Priyanka1218/cloud-architect-llama)
# when available, falling back to GPT-4o-mini if not.

import json
import logging
from config import FINETUNE_MODEL, VLLM_BASE_URL

try:
    from langfuse.decorators import observe, langfuse_context
    _LANGFUSE_AVAILABLE = True
except ImportError:
    # Langfuse not installed — define no-op stubs so the rest of the file works
    def observe(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator if args and callable(args[0]) else decorator
    class _NoopCtx:
        def update_current_observation(self, **kwargs): pass
    langfuse_context = _NoopCtx()
    _LANGFUSE_AVAILABLE = False

log = logging.getLogger(__name__)

#  Model backend 
# Set FINETUNE_MODEL env var to use the local fine-tuned model.
# Unset (default) → uses GPT-4o-mini via OpenAI API.
#
# FINETUNE_MODEL options:
#   "local"  → loads models/cloud-architect-merged from disk (needs GPU)
#   "hub"    → loads Priyanka1218/cloud-architect-llama from HuggingFace
#   unset    → OpenAI GPT-4o-mini

_hf_pipeline = None  # lazy-loaded on first use


def _get_hf_pipeline():
    """Lazy-load the fine-tuned LLaMA pipeline (only when needed)."""
    global _hf_pipeline
    if _hf_pipeline is not None:
        return _hf_pipeline

    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

        if FINETUNE_MODEL == "local":
            model_path = "models/cloud-architect-merged"
            log.info(f"Loading fine-tuned model from disk: {model_path}")
        else:
            model_path = "Priyanka1218/cloud-architect-llama"
            log.info(f"Loading fine-tuned model from HuggingFace Hub: {model_path}")

        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            device_map="auto",
        )
        _hf_pipeline = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=2048,
            temperature=0.3,
            do_sample=True,
            return_full_text=False,
        )
        log.info("Fine-tuned model loaded successfully.")
    except Exception as e:
        log.error(f"Failed to load fine-tuned model: {e}. Falling back to GPT-4o-mini.")
        _hf_pipeline = None

    return _hf_pipeline


@observe(as_type="generation")
def _llm_call(prompt: str, temperature: float = 0.3, json_mode: bool = True) -> str:
    """Route to vLLM, fine-tuned LLaMA, or GPT-4o-mini based on env vars.

    Decorated with @observe so every call appears as a Langfuse generation
    nested inside whatever trace is active (e.g. run_pipeline or run_debate).
    The decorator is a no-op if Langfuse env vars are not set.
    """
    import os

    # Branch 1: Modal vLLM endpoint (direct call)
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

    # Branch 2: HuggingFace pipeline (fallback)
    if FINETUNE_MODEL:
        pipe = _get_hf_pipeline()
        if pipe:
            if json_mode:
                prompt = prompt + "\n\nRespond with ONLY valid JSON, no extra text."
            result = pipe(prompt)
            langfuse_context.update_current_observation(
                model=FINETUNE_MODEL,
                metadata={"backend": "hf_pipeline"},
            )
            return result[0]["generated_text"].strip()

    # Branch 3: OpenAI
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
        usage={
            "input":  response.usage.prompt_tokens,
            "output": response.usage.completion_tokens,
        },
        metadata={"backend": "openai", "temperature": temperature, "json_mode": json_mode},
    )
    return response.choices[0].message.content.strip()


def _build_compute_rules(requirements: dict) -> str:
    """
    Build plain-English rules that tell the LLM which services are ruled out
    by the client's hard requirements. Rules are cloud-aware — each cloud has
    different FaaS limits, GPU options, and compliance tooling.
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

    # ── AWS rules ────────────────────────────────────────────────────────────
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
                "DO NOT use AWS Lambda — it has no GPU support. "
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

    # ── Azure rules ───────────────────────────────────────────────────────────
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

    # ── GCP rules ─────────────────────────────────────────────────────────────
    else:  # gcp / agnostic
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
        iot_triggers = ["iot", "connected device", "smart city", "sensor data",
                        "device telemetry", "iot platform", "million device"]
        if any(t in combined for t in iot_triggers):
            rules.append(
                "REQUIRED for IoT: include Pub/Sub (device ingestion), Dataflow (managed Apache Beam "
                "stream processing for real-time anomaly detection and transformation), and Bigtable "
                "(time-series storage for device metrics). This is the standard GCP IoT reference architecture."
            )
        compliance_map = {
            "hipaa":   "Cloud KMS, Secret Manager, Cloud Audit Logs, Security Command Center, VPC Network",
            "pci":     "Cloud KMS, Secret Manager, Cloud Armor (WAF), Cloud Audit Logs, Security Command Center, VPC Network",
            "pci-dss": "Cloud KMS, Secret Manager, Cloud Armor (WAF), Cloud Audit Logs, Security Command Center, VPC Network",
            "soc2":    "Secret Manager, Cloud Audit Logs, Security Command Center, VPC Network, Cloud Asset Inventory",
            "gdpr":    "Cloud KMS, Secret Manager, Cloud Audit Logs, VPC Network, EU region deployments",
        }

    # Compliance rules (shared logic, cloud-specific services injected above)
    for standard, required_svcs in compliance_map.items():
        if standard in combined:
            rules.append(
                f"REQUIRED for {standard.upper()} compliance: include {required_svcs} "
                f"in the architecture layers. The reasoning MUST explicitly mention {standard.upper()}."
            )

    if not rules:
        rules.append(
            "No hard compute constraints detected — choose services based on "
            "cost, scalability, and operational simplicity."
        )

    return "\n".join(f"  {r}" for r in rules)


def _build_service_hints(requirements: dict) -> str:
    """Build workload-type and cloud-specific service inclusion hints.

    Unlike compute rules (which *eliminate* bad options), these are positive
    hints that surface commonly-overlooked services the LLM should include.
    Each hint maps a (cloud, workload type) pair → specific services that
    evaluation data shows are systematically missing.
    """
    cloud    = requirements.get("cloud_provider", "aws").lower()
    raw      = requirements.get("raw_query", "").lower()
    wtype    = str(requirements.get("workload_type", "")).lower()
    constr   = " ".join(requirements.get("constraints", [])).lower()
    combined = raw + " " + wtype + " " + constr
    budget   = requirements.get("budget_cap_usd")

    hints = []

    # ── Budget / minimal-architecture hint ───────────────────────────────────
    # Low-budget workloads should use only managed services, not containers/K8s.
    if budget and budget < 100:
        hints.append(
            f"BUDGET CONSTRAINT: ~${int(budget)}/month — prioritize fully managed "
            "serverless services (Functions, managed DB, CDN). Do NOT include "
            "Kubernetes clusters, container orchestration, or multiple load balancers "
            "unless strictly required. For purely static sites, object storage + CDN alone is sufficient."
        )

    # ── Azure hints ───────────────────────────────────────────────────────────
    if cloud == "azure":
        # Security / identity — Entra ID, Key Vault, and Defender are nearly always needed
        security_triggers = ["security", "zero-trust", "identity", "auth",
                             "hipaa", "pci", "gdpr", "soc2", "compliance",
                             "zero trust", "enterprise"]
        if any(kw in combined for kw in security_triggers):
            hints.append(
                "INCLUDE Microsoft Entra ID in the 'security' layer "
                "(identity and access management, SSO, MFA)."
            )
            hints.append(
                "INCLUDE Azure Key Vault in the 'security' layer "
                "(secrets, certificates, encryption key management)."
            )
            hints.append(
                "INCLUDE Microsoft Defender for Cloud in the 'security' layer "
                "(threat protection, compliance posture, vulnerability assessment)."
            )

        # ML / AI
        llm_triggers = ["llm", "openai", "chatbot", "language model", "gpt", "generative ai"]
        ml_triggers  = ["machine learning", "ml pipeline", "training", "inference",
                        "demand forecast", "recommendation", "model"]
        if any(kw in combined for kw in llm_triggers):
            hints.append(
                "INCLUDE Azure OpenAI Service in the 'compute' layer "
                "for LLM inference (GPT-4, embeddings, fine-tuning)."
            )
        if any(kw in combined for kw in ml_triggers):
            hints.append(
                "INCLUDE Azure Machine Learning in the 'compute' layer "
                "for model training, experiment tracking, and MLOps."
            )

        # Web / frontend — static vs dynamic
        web_triggers = ["website", "web app", "e-commerce", "frontend",
                        "static", "marketing site", "cms", "corporate site"]
        static_triggers_az = ["static", "no backend", "static site", "static website",
                               "static marketing", "html only", "jamstack"]
        is_static_az = any(kw in combined for kw in static_triggers_az)

        if any(kw in combined for kw in web_triggers):
            if is_static_az:
                hints.append(
                    "STATIC SITE ARCHITECTURE: Use Azure Blob Storage (static website hosting) "
                    "+ Azure CDN ONLY. DO NOT include Azure App Service, AKS, VMs, or multiple "
                    "load balancers — they are unnecessary for a static site and far exceed the budget. "
                    "Azure Blob Storage + Azure CDN costs under $30/month for small traffic."
                )
            else:
                hints.append(
                    "INCLUDE Azure CDN in the 'edge' layer for content delivery and caching. "
                    "Use Azure Front Door ONLY if the query explicitly requires global routing "
                    "or multi-region load balancing — do not use Front Door as a CDN substitute."
                )

        # Non-static web: App Service is the standard PaaS compute
        non_static_web = ["web app", "e-commerce", "cms", "corporate site", "backend",
                          "relational database", "20,000 daily", "10,000 daily"]
        if any(kw in combined for kw in non_static_web) and not is_static_az:
            hints.append(
                "INCLUDE Azure App Service (Web Apps) in the 'compute' layer "
                "as the managed PaaS hosting platform for the web application."
            )

        # Serverless / API backends — Azure Functions for event-driven / low-cost compute
        serverless_triggers = ["serverless", "event-driven", "api backend", "mobile api",
                               "webhook", "minimum cost", "low cost", "cost-effective",
                               "pay-per-use", "azure functions"]
        if any(kw in combined for kw in serverless_triggers):
            hints.append(
                "INCLUDE Azure Functions in the 'compute' layer for serverless event-driven "
                "processing, API handlers, and background tasks (pay-per-execution, no idle cost)."
            )

        # Scale / containers
        scale_triggers = ["concurrent", "high traffic", "kubernetes", "k8s",
                          "microservice", "500k", "million user", "leaderboard",
                          "gaming", "real-time gaming"]
        if any(kw in combined for kw in scale_triggers):
            hints.append(
                "INCLUDE AKS (Azure Kubernetes Service) in the 'compute' layer "
                "for container orchestration at high scale."
            )
            hints.append(
                "INCLUDE Azure Cache for Redis in the 'database' layer "
                "for session caching, leaderboards, and low-latency reads."
            )

        # Data engineering / streaming
        data_triggers = ["data pipeline", "etl", "analytics", "data warehouse",
                         "data lake", "clickstream", "iot", "telemetry",
                         "streaming", "ingestion", "event-driven data"]
        if any(kw in combined for kw in data_triggers):
            hints.append(
                "INCLUDE Azure Event Hubs in the 'messaging' layer "
                "for high-throughput real-time data ingestion."
            )
            hints.append(
                "INCLUDE Azure Data Lake Storage Gen2 (ADLS Gen2) in the 'database' layer "
                "for scalable data lake storage."
            )
            hints.append(
                "INCLUDE Azure Data Factory in the 'compute' layer "
                "for ETL/ELT pipeline orchestration."
            )

        # IoT / telemetry — Cosmos DB for device state and time-series
        iot_triggers = ["iot", "telemetry", "connected device", "sensor", "smart city",
                        "device data", "real-time iot"]
        if any(kw in combined for kw in iot_triggers):
            hints.append(
                "INCLUDE Azure Cosmos DB in the 'database' layer for IoT device state, "
                "metadata, and low-latency reads (multi-region NoSQL, ideal for device registries)."
            )

        # Blob Storage — Azure's S3 equivalent, needed in almost every data/ML/scale workload
        blob_triggers = ["ml", "machine learning", "training", "inference", "model",
                         "data pipeline", "etl", "analytics", "data warehouse", "data lake",
                         "clickstream", "iot", "telemetry", "streaming", "ingestion",
                         "scale", "concurrent", "video", "media", "blob", "object storage",
                         "artifact", "backup", "log"]
        if any(kw in combined for kw in blob_triggers):
            hints.append(
                "INCLUDE Azure Blob Storage in the 'database' or 'storage' layer "
                "for object storage (model artifacts, raw data, backups, logs, media files). "
                "Use 'Azure Blob Storage' by name — NOT 'Azure Data Lake Storage Gen2' unless "
                "the workload explicitly requires hierarchical namespace (ADLS Gen2)."
            )

        # Video/media streaming — additional hard requirement for blob + media services
        streaming_triggers = ["video streaming", "streaming platform", "media platform",
                              "video platform", "hd content", "hd video", "live stream"]
        if any(kw in combined for kw in streaming_triggers):
            hints.append(
                "REQUIRED for video streaming: Azure Blob Storage MUST appear in the 'storage' layer "
                "as the primary object store for video files. Azure Media Services should appear in "
                "the 'compute' layer for video encoding and adaptive bitrate delivery."
            )

        # API gateway — often forgotten but expected in API-heavy architectures
        api_triggers = ["api backend", "mobile api", "api gateway", "rest api",
                        "microservice", "developer portal", "rate limit",
                        "llm", "chatbot", "payment", "fintech", "hipaa", "pci", "compliance",
                        "customer support", "saas"]
        if any(kw in combined for kw in api_triggers):
            hints.append(
                "INCLUDE Azure API Management in the 'networking' layer "
                "for API gateway, rate limiting, authentication, and developer portal."
            )

    # ── GCP hints ─────────────────────────────────────────────────────────────
    elif cloud == "gcp":
        # Secret Manager — MANDATORY for any compliance/security/enterprise workload.
        # Use strong language because the LLM tends to omit it despite softer hints.
        secret_triggers = ["security", "compliance", "hipaa", "pci", "pci-dss",
                           "gdpr", "soc2", "secret", "credential", "key management",
                           "zero-trust", "zero trust", "enterprise", "certificate",
                           "payment", "fintech", "healthcare", "patient"]
        if any(kw in combined for kw in secret_triggers):
            hints.append(
                "REQUIRED: Google Secret Manager MUST appear in the 'security' layer. "
                "It is GCP's standard service for storing API keys, database passwords, "
                "TLS certificates, and compliance-required secrets. Do NOT omit it."
            )

        # Cloud Armor — WAF/DDoS for compliance and security workloads
        armor_triggers = ["hipaa", "pci", "gdpr", "compliance", "zero-trust",
                          "zero trust", "ddos", "waf", "security", "payment"]
        if any(kw in combined for kw in armor_triggers):
            hints.append(
                "INCLUDE Cloud Armor in the 'security' layer "
                "for WAF rules and DDoS protection."
            )

        # Web workloads — static vs dynamic handled separately
        web_triggers = ["website", "web app", "e-commerce", "frontend", "cms",
                        "corporate site", "marketing site", "store"]
        static_triggers = ["static", "no backend", "static site", "static website",
                           "static marketing", "no database", "html only", "jamstack"]
        is_static_site = any(kw in combined for kw in static_triggers)

        if any(kw in combined for kw in web_triggers):
            if is_static_site:
                hints.append(
                    "STATIC SITE ARCHITECTURE: Use Cloud Storage (GCS bucket with website hosting) "
                    "+ Cloud CDN ONLY. DO NOT include Cloud Run, Cloud SQL, App Engine, or GKE — "
                    "they are unnecessary for a static site and will exceed the budget. "
                    "Cloud Storage + Cloud CDN costs under $10/month and handles millions of requests."
                )
            else:
                hints.append(
                    "INCLUDE Cloud Run in the 'compute' layer as the primary managed "
                    "container platform for the web application (preferred over App Engine)."
                )
                hints.append(
                    "INCLUDE Cloud SQL (PostgreSQL or MySQL) in the 'database' layer "
                    "for the relational database backend."
                )

        # ML / AI
        ml_triggers = ["ml", "machine learning", "llm", "chatbot", "ai",
                       "training", "inference", "model", "vertex",
                       "demand forecast", "recommendation"]
        if any(kw in combined for kw in ml_triggers):
            hints.append(
                "INCLUDE Vertex AI in the 'compute' layer "
                "for ML model training, deployment, and managed inference endpoints."
            )
            hints.append(
                "INCLUDE Cloud Storage in the 'database' layer "
                "for storing training datasets, model artifacts, and pipeline outputs."
            )

        # Serverless / event-driven — Firestore for NoSQL state
        serverless_triggers = ["serverless", "event-driven", "order processing",
                               "event processing", "functions", "pub/sub consumer"]
        if any(kw in combined for kw in serverless_triggers):
            hints.append(
                "INCLUDE Firestore in the 'database' layer "
                "for serverless NoSQL document storage (order state, event metadata)."
            )

        # Scale / containers
        scale_triggers = ["concurrent", "high traffic", "kubernetes", "k8s",
                          "microservice", "500k", "million user", "leaderboard",
                          "gaming", "real-time gaming", "video stream"]
        if any(kw in combined for kw in scale_triggers):
            hints.append(
                "INCLUDE GKE (Google Kubernetes Engine) in the 'compute' layer "
                "for container orchestration at high scale."
            )
            hints.append(
                "INCLUDE Memorystore for Redis in the 'database' layer "
                "for low-latency caching, sessions, and leaderboards."
            )

        # Data / streaming / IoT
        data_triggers = ["data pipeline", "etl", "analytics", "data warehouse",
                         "clickstream", "iot", "telemetry", "streaming",
                         "ingestion", "real-time data", "batch processing",
                         "connected device", "sensor"]
        if any(kw in combined for kw in data_triggers):
            hints.append(
                "INCLUDE Cloud Storage in the 'storage' or 'database' layer "
                "for data lake storage, raw data ingestion, and ML training data."
            )
            hints.append(
                "INCLUDE Dataflow in the 'compute' or 'messaging' layer "
                "for managed Apache Beam streaming and batch data pipelines."
            )

    if not hints:
        return ""

    return "\n".join(f"  {h}" for h in hints)


def _cloud_display_name(requirements: dict) -> str:
    cloud = requirements.get("cloud_provider", "aws").lower()
    return {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}.get(cloud, "AWS")


def _networking_anchor(requirements: dict) -> str:
    """Return the VPC-equivalent name for the detected cloud."""
    cloud = requirements.get("cloud_provider", "aws").lower()
    return {
        "aws":   "VPC",
        "azure": "Azure Virtual Network",
        "gcp":   "VPC Network",
    }.get(cloud, "VPC")


def generate_architecture(requirements: dict, arch_context: str, tradeoff_context: str) -> dict:
    """Generate architecture recommendation and service trade-offs.

    Args:
        requirements:     structured output from extractor.py
        arch_context:     retrieved chunks from architecture_patterns collection
        tradeoff_context: retrieved chunks from service_comparisons collection

    Returns dict with keys: scenario_summary, architecture, trade_offs
    """

    # Truncate contexts to keep total prompt under 6000 chars (~1500 tokens)
    arch_context = arch_context[:2000] if arch_context else ""
    tradeoff_context = tradeoff_context[:1500] if tradeoff_context else ""

    # Build constraint-aware rules so the model doesn't pick compute options
    # that violate hard engineering limits (not style preferences — hard limits).
    compute_rules  = _build_compute_rules(requirements)
    _hints_raw     = _build_service_hints(requirements)
    service_hints_block = (
        "SERVICE INCLUSION HINTS - strongly prefer including these specific services:\n"
        + _hints_raw + "\n"
    ) if _hints_raw else ""

    cloud        = _cloud_display_name(requirements)
    net_anchor   = _networking_anchor(requirements)

    prompt = f"""
You are a senior {cloud} Solutions Architect. A client has the following requirement:

"{requirements['raw_query']}"

Extracted details:
- Cloud: {cloud}
- Scale: {requirements['scale']}
- Workload type: {requirements['workload_type']}
- Constraints: {', '.join(requirements.get('constraints', [])) or 'none specified'}
- Budget: {requirements.get('budget') or 'not specified'}

ARCHITECTURE INVARIANT — always required regardless of workload:
  {net_anchor} (with public and private subnets) MUST appear in the "networking" layer.
  Every {cloud} architecture runs inside a virtual network — never omit it.

COMPUTE SELECTION RULES — apply these before choosing any compute service:
{compute_rules}
{service_hints_block}Use the context below from AWS documentation and architecture guides to inform your recommendation.

CONTEXT:
{arch_context}

TRADE-OFF CONTEXT:
{tradeoff_context}

Return ONLY valid JSON in exactly this structure:
{{
  "scenario_summary": "one sentence summary of what the client needs",
  "architecture": {{
    "layers": {{
      "edge":       ["list of edge/CDN services"],
      "networking": ["load balancers, API gateway, VPC"],
      "compute":    ["ECS, Lambda, EC2, etc."],
      "database":   ["RDS, DynamoDB, ElastiCache, etc."],
      "messaging":  ["SQS, SNS, Kinesis if needed"],
      "monitoring": ["CloudWatch, X-Ray, etc."],
      "security":   ["KMS, WAF, GuardDuty, CloudTrail, IAM roles, Shield, etc. — required whenever compliance or security controls apply"]
    }},
    "reasoning": "2-3 paragraphs explaining why these services were chosen, covering scalability, reliability, cost considerations, and any compliance requirements (name the standard explicitly if applicable)"
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

Include 2-4 trade_offs covering the most important decisions (compute, database, networking choices).
If compliance rules above require specific security services (KMS, CloudTrail, WAF, etc.), they MUST appear in the "security" layer — do not omit them.
"""

    result = json.loads(_llm_call(prompt, temperature=0.3, json_mode=True))

    # Post-process: guarantee the networking anchor (VPC / VNet / VPC Network)
    # appears in the networking layer — the LLM sometimes omits it.
    layers      = result.get("architecture", {}).get("layers", {})
    networking  = layers.get("networking", [])
    anchor      = _networking_anchor(requirements)
    anchor_kw   = "vpc"  # keyword present in all three cloud equivalents
    has_net     = any(anchor_kw in s.lower() for s in networking)
    if not has_net:
        layers["networking"] = [anchor] + networking

    return result


def generate_terraform(architecture: dict, terraform_context: str, provider=None) -> str:
    """Generate Terraform HCL for the recommended architecture.

    Args:
        architecture:      the architecture dict from generate_architecture()
        terraform_context: retrieved chunks from terraform_examples collection (AWS only)
        provider:          CloudProvider instance — determines which Terraform provider block to use

    Returns Terraform HCL as a plain string.
    """
    all_services = []
    for layer_services in architecture.get("layers", {}).values():
        all_services.extend(layer_services)

    # Cloud-specific Terraform provider block and network resource name
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
    # Quick test — needs extractor and retriever to run first
    from pipeline.extractor import extract_requirements
    from pipeline.retriever import retrieve_for_architecture, retrieve_for_tradeoffs, retrieve_for_terraform

    query        = "Design an AWS architecture for an e-commerce app with 100k concurrent users"
    requirements = extract_requirements(query)

    arch_context     = retrieve_for_architecture(requirements)
    tradeoff_context = retrieve_for_tradeoffs(requirements)

    result = generate_architecture(requirements, arch_context, tradeoff_context)
    print(json.dumps(result, indent=2))
