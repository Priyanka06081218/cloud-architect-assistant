# pipeline/agents.py
#
# Multi-agent architecture debate system.
#
# Three specialized agents each propose an architecture from their perspective:
#   - Cost Agent:        minimizes monthly spend, prefers serverless/spot
#   - Reliability Agent: maximizes uptime, prefers multi-AZ/redundancy
#   - Security Agent:    enforces least-privilege, encryption, compliance
#
# A Moderator agent reads all three proposals and synthesizes a final
# recommendation that explicitly resolves the conflicts between them.

import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import VLLM_BASE_URL, FINETUNE_MODEL

try:
    from langfuse.decorators import observe, langfuse_context
    _LANGFUSE_AVAILABLE = True
except ImportError:
    def observe(*args, **kwargs):
        def decorator(fn): return fn
        return decorator if args and callable(args[0]) else decorator
    class _NoopCtx:
        def update_current_observation(self, **kwargs): pass
    langfuse_context = _NoopCtx()
    _LANGFUSE_AVAILABLE = False


@observe(as_type="generation")
def _llm_call_modal(messages: list, temperature: float = 0.4) -> str:
    payload = {
        "model": FINETUNE_MODEL or "cloud-architect-llama",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 1024,
    }
    resp = requests.post(VLLM_BASE_URL, json=payload, timeout=120)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()
    langfuse_context.update_current_observation(
        model=payload["model"],
        metadata={"backend": "vllm", "temperature": temperature},
    )
    return content


_CLOUD_HINTS = {
    "aws": {
        "name": "AWS",
        "cost_tips": (
            "- Prefer Lambda over ECS/EC2 whenever feasible\n"
            "- Use Spot Instances for batch workloads\n"
            "- Choose DynamoDB on-demand over RDS when possible\n"
            "- Avoid NAT Gateways (use VPC endpoints instead)\n"
            "- Use S3 + CloudFront instead of expensive managed services\n"
            "- Prefer Aurora Serverless v2 over provisioned RDS\n"
            "- Mention Reserved Instance or Savings Plan opportunities"
        ),
        "reliability_tips": (
            "- Always multi-AZ for RDS, ElastiCache, and ECS\n"
            "- Use Aurora over RDS for automatic failover\n"
            "- Prefer ECS or EKS over Lambda for predictable, long-running workloads\n"
            "- Add ElastiCache in front of every hot-path database\n"
            "- Use ALB with health checks and Auto Scaling Groups\n"
            "- Add CloudWatch alarms, X-Ray tracing, and automated runbooks\n"
            "- Design for graceful degradation -- every service needs a fallback"
        ),
        "security_tips": (
            "- All data encrypted at rest (AWS KMS) and in transit (TLS 1.3)\n"
            "- VPC with private subnets -- nothing public except ALB/CloudFront\n"
            "- AWS WAF in front of all public endpoints\n"
            "- IAM roles with least-privilege (no wildcard actions or resources)\n"
            "- Secrets in AWS Secrets Manager, never in environment variables\n"
            "- CloudTrail + GuardDuty + Security Hub enabled\n"
            "- VPC Flow Logs and S3 access logging enabled"
        ),
        "moderator_title": "Principal AWS Solutions Architect",
        "example_conflict": "cost agent wants Lambda, reliability agent wants ECS",
    },
    "azure": {
        "name": "Azure",
        "cost_tips": (
            "- Prefer Azure Functions (Consumption plan) over Container Apps/AKS when feasible\n"
            "- Use Azure Spot VMs for batch workloads\n"
            "- Choose Azure Cosmos DB serverless over provisioned throughput when possible\n"
            "- Use Azure CDN + Blob Storage instead of expensive managed services\n"
            "- Prefer Azure SQL Serverless over provisioned DTU tiers\n"
            "- Mention Azure Reserved VM Instances or Azure Hybrid Benefit savings"
        ),
        "reliability_tips": (
            "- Always deploy across Availability Zones for VMs, AKS, and Azure SQL\n"
            "- Use Azure SQL Business Critical or Geo-Replication for automatic failover\n"
            "- Prefer Azure Kubernetes Service or Container Apps over Functions for predictable workloads\n"
            "- Add Azure Cache for Redis in front of every hot-path database\n"
            "- Use Azure Application Gateway or Azure Front Door with health probes\n"
            "- Add Azure Monitor alerts, Application Insights tracing, and runbooks\n"
            "- Design for graceful degradation -- every service needs a fallback"
        ),
        "security_tips": (
            "- All data encrypted at rest (Azure Key Vault / customer-managed keys) and in transit (TLS 1.3)\n"
            "- VNet with private subnets -- nothing public except Application Gateway/Azure Front Door\n"
            "- Azure WAF (Web Application Firewall) policy on all public endpoints\n"
            "- Azure RBAC with least-privilege (no Owner/Contributor wildcards at subscription scope)\n"
            "- Secrets in Azure Key Vault, never in environment variables or app settings\n"
            "- Microsoft Defender for Cloud + Azure Monitor + Sentinel enabled\n"
            "- NSG Flow Logs and Storage diagnostic logging enabled"
        ),
        "moderator_title": "Principal Azure Solutions Architect",
        "example_conflict": "cost agent wants Azure Functions, reliability agent wants AKS",
    },
    "gcp": {
        "name": "GCP",
        "cost_tips": (
            "- Prefer Cloud Functions or Cloud Run (pay-per-request) over GKE when feasible\n"
            "- Use Spot / Preemptible VMs for batch workloads\n"
            "- Choose Firestore or Bigtable over Cloud SQL when schema flexibility allows\n"
            "- Use Cloud Storage + Cloud CDN instead of expensive managed services\n"
            "- Prefer Cloud SQL with automatic storage increase over large provisioned instances\n"
            "- Mention Committed Use Discounts (CUDs) and Sustained Use Discounts"
        ),
        "reliability_tips": (
            "- Always deploy across multiple GCP zones for GCE, GKE, and Cloud SQL\n"
            "- Use Cloud Spanner or Cloud SQL HA with automatic failover for critical databases\n"
            "- Prefer GKE (Autopilot) or Cloud Run over Cloud Functions for predictable, long-running workloads\n"
            "- Add Memorystore for Redis in front of every hot-path database\n"
            "- Use Cloud Load Balancing with health checks and managed instance groups\n"
            "- Add Cloud Monitoring alerts, Cloud Trace, and automated runbooks via Cloud Workflows\n"
            "- Design for graceful degradation -- every service needs a fallback"
        ),
        "security_tips": (
            "- All data encrypted at rest (Cloud KMS / CMEK) and in transit (TLS 1.3)\n"
            "- VPC with private subnets -- nothing public except Cloud Load Balancer / Cloud Armor\n"
            "- Cloud Armor WAF policies on all public-facing load balancers\n"
            "- IAM with least-privilege (predefined roles, no primitive Owner/Editor bindings)\n"
            "- Secrets in Secret Manager, never in environment variables\n"
            "- Cloud Audit Logs + Security Command Center + VPC Service Controls enabled\n"
            "- VPC Flow Logs and Cloud Storage access logging enabled"
        ),
        "moderator_title": "Principal GCP Solutions Architect",
        "example_conflict": "cost agent wants Cloud Functions, reliability agent wants GKE",
    },
}


def _detect_cloud(query: str) -> str:
    """Detect cloud provider from query text. Returns 'aws', 'azure', or 'gcp'."""
    q = query.lower()
    if "azure" in q or "microsoft cloud" in q:
        return "azure"
    if "gcp" in q or "google cloud" in q or "gke" in q or "bigquery" in q:
        return "gcp"
    return "aws"   # default


def _build_cost_prompt(hints: dict) -> str:
    return f"""You are a Cloud Cost Optimization Architect. Your ONLY priority is minimizing {hints['name']} costs.

When given an architecture scenario, propose the most cost-effective {hints['name']} solution:
{hints['cost_tips']}

You don't care about reliability or security -- only cost. Be opinionated and use ONLY {hints['name']} services.

Return ONLY valid JSON:
{{
  "agent": "cost",
  "proposed_services": {{
    "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
  }},
  "estimated_monthly_usd": 0,
  "argument": "2-3 paragraphs arguing why this is the right {hints['name']} architecture from a cost perspective",
  "key_decisions": [
    {{"decision": "...", "chose": "...", "saves_usd_monthly": 0, "trade_off": "..."}}
  ]
}}"""


def _build_reliability_prompt(hints: dict) -> str:
    return f"""You are a Cloud Reliability Architect. Your ONLY priority is maximizing uptime and resilience.

When given an architecture scenario, propose the most reliable {hints['name']} solution:
{hints['reliability_tips']}
- Target 99.99% SLA minimum

You don't care about cost or security -- only reliability. Be opinionated and use ONLY {hints['name']} services.

Return ONLY valid JSON:
{{
  "agent": "reliability",
  "proposed_services": {{
    "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
  }},
  "estimated_sla_percent": 99.99,
  "argument": "2-3 paragraphs arguing why this is the right {hints['name']} architecture from a reliability perspective",
  "key_decisions": [
    {{"decision": "...", "chose": "...", "uptime_impact": "...", "trade_off": "..."}}
  ]
}}"""


def _build_security_prompt(hints: dict) -> str:
    return f"""You are a Cloud Security Architect. Your ONLY priority is security, compliance, and least-privilege access.

When given an architecture scenario, propose the most secure {hints['name']} solution:
{hints['security_tips']}

You don't care about cost or reliability -- only security. Be opinionated and use ONLY {hints['name']} services.

Return ONLY valid JSON:
{{
  "agent": "security",
  "proposed_services": {{
    "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
  }},
  "compliance_level": "e.g. HIPAA-ready / PCI-DSS / SOC2",
  "argument": "2-3 paragraphs arguing why this is the right {hints['name']} architecture from a security perspective",
  "key_decisions": [
    {{"decision": "...", "chose": "...", "risk_mitigated": "...", "trade_off": "..."}}
  ]
}}"""


def _build_moderator_prompt(hints: dict) -> str:
    return f"""You are a {hints['moderator_title']} moderating a debate between three specialist agents.

You have received three {hints['name']} architecture proposals for the same scenario:
1. Cost Agent -- optimized purely for minimum spend
2. Reliability Agent -- optimized purely for maximum uptime
3. Security Agent -- optimized purely for maximum security

Synthesize these into ONE final balanced {hints['name']} recommendation that:
- Picks the best ideas from each agent
- Resolves conflicts explicitly (e.g. {hints['example_conflict']})
- Explains WHICH agent won each key decision and WHY
- Uses ONLY {hints['name']} services -- never mix in AWS/Azure/GCP services from another cloud
- Produces a realistic architecture a real company would deploy on {hints['name']}

Return ONLY valid JSON:
{{
  "final_architecture": {{
    "layers": {{
      "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
    }},
    "reasoning": "2-3 paragraphs explaining the synthesized recommendation"
  }},
  "debate_summary": [
    {{
      "topic": "what was debated (e.g. Compute layer)",
      "cost_argued": "what cost agent wanted",
      "reliability_argued": "what reliability agent wanted",
      "security_argued": "what security agent wanted",
      "winner": "cost | reliability | security | compromise",
      "final_decision": "what was chosen",
      "rationale": "why"
    }}
  ],
  "scores": {{
    "cost_influence_pct": 0,
    "reliability_influence_pct": 0,
    "security_influence_pct": 0
  }}
}}\""""



def run_agent(system_prompt: str, user_query: str, agent_name: str) -> dict:
    """Run a single agent and return its parsed JSON proposal."""
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_query},
        ]
        content = _llm_call_modal(messages, temperature=0.4)
        return json.loads(content)
    except Exception as e:
        return {
            "agent":    agent_name,
            "error":    str(e),
            "argument": f"{agent_name} agent failed: {e}",
        }

def run_moderator(query: str, cost: dict, reliability: dict, security: dict, cloud_provider: str = "aws") -> dict:
    """Run the moderator agent to synthesize the three proposals."""
    hints = _CLOUD_HINTS.get(cloud_provider, _CLOUD_HINTS["aws"])
    context = f"""
SCENARIO: {query}
CLOUD PROVIDER: {hints['name']}

COST AGENT PROPOSAL:
{json.dumps(cost, indent=2)}
RELIABILITY AGENT PROPOSAL:
{json.dumps(reliability, indent=2)}
SECURITY AGENT PROPOSAL:
{json.dumps(security, indent=2)}
"""
    try:
        messages = [
            {"role": "system", "content": _build_moderator_prompt(hints)},
            {"role": "user",   "content": context},
        ]
        content = _llm_call_modal(messages, temperature=0.3)
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}



@observe(name="multi_agent_debate")
def run_debate(user_query: str, cloud_provider: str | None = None) -> dict:
    """Run the full multi-agent debate for a cloud architecture query.

    Runs the 3 specialist agents in parallel using cloud-specific prompts,
    then passes all proposals to the moderator for synthesis.

    Args:
        user_query:     natural language cloud architecture scenario
        cloud_provider: 'aws', 'azure', or 'gcp'. Auto-detected from query if None.

    Returns:
        Full debate result with individual proposals + synthesized final architecture
    """
    if not cloud_provider:
        cloud_provider = _detect_cloud(user_query)

    hints = _CLOUD_HINTS.get(cloud_provider, _CLOUD_HINTS["aws"])
    print(f"\n[Debate] Query: {user_query[:80]}... | Cloud: {hints['name']}")
    print("[Debate] Running 3 agents in parallel...")

    agent_configs = [
        ("cost",        _build_cost_prompt(hints)),
        ("reliability", _build_reliability_prompt(hints)),
        ("security",    _build_security_prompt(hints)),
    ]

    proposals = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_agent, prompt, user_query, name): name
            for name, prompt in agent_configs
        }
        for future in as_completed(futures):
            name = futures[future]
            proposals[name] = future.result()
            print(f"  {name.capitalize()} agent done")

    print("[Debate] Moderator synthesizing...")
    synthesis = run_moderator(
        user_query,
        proposals["cost"],
        proposals["reliability"],
        proposals["security"],
        cloud_provider=cloud_provider,
    )
    print("[Debate] Done.")

    return {
        "query":         user_query,
        "cloud_provider": hints["name"],
        "proposals": {
            "cost":        proposals["cost"],
            "reliability": proposals["reliability"],
            "security":    proposals["security"],
        },
        "synthesis": synthesis,
    }


if __name__ == "__main__":
    result = run_debate(
        "Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday."
    )
    print(json.dumps(result, indent=2))
