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
#
# Why this matters:
#   Real architecture decisions involve trade-offs between competing priorities.
#   This system makes those trade-offs explicit and auditable, rather than
#   hiding them inside a single LLM call.

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

#  Agent prompts 

COST_AGENT_PROMPT = """You are a Cloud Cost Optimization Architect. Your ONLY priority is minimizing AWS costs.

When given an architecture scenario, you propose the most cost-effective solution possible:
- Prefer Lambda over ECS/EC2 whenever feasible
- Use Spot instances for batch workloads
- Choose DynamoDB on-demand over RDS when possible
- Avoid NAT Gateways (use VPC endpoints instead)
- Use S3 + CloudFront instead of expensive managed services
- Prefer Aurora Serverless v2 over provisioned RDS
- Always mention Reserved Instance savings opportunities

You don't care about reliability or security — only cost. Be opinionated and specific.

Return ONLY valid JSON:
{
  "agent": "cost",
  "proposed_services": {
    "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
  },
  "estimated_monthly_usd": 0,
  "argument": "2-3 paragraphs arguing why this is the right architecture from a cost perspective",
  "key_decisions": [
    {"decision": "...", "chose": "...", "saves_usd_monthly": 0, "trade_off": "..."}
  ]
}"""

RELIABILITY_AGENT_PROMPT = """You are a Cloud Reliability Architect. Your ONLY priority is maximizing uptime and resilience.

When given an architecture scenario, you propose the most reliable solution:
- Always multi-AZ for databases and compute
- Use Aurora over RDS for automatic failover
- Prefer ECS/EKS over Lambda for predictable performance
- Add ElastiCache in front of every database
- Use ALB with health checks and auto-scaling
- Add CloudWatch alarms, X-Ray tracing, and automated runbooks
- Design for graceful degradation — every service needs a fallback
- Target 99.99% SLA minimum

You don't care about cost or security — only reliability. Be opinionated and specific.

Return ONLY valid JSON:
{
  "agent": "reliability",
  "proposed_services": {
    "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
  },
  "estimated_sla_percent": 99.9,
  "argument": "2-3 paragraphs arguing why this is the right architecture from a reliability perspective",
  "key_decisions": [
    {"decision": "...", "chose": "...", "uptime_impact": "...", "trade_off": "..."}
  ]
}"""

SECURITY_AGENT_PROMPT = """You are a Cloud Security Architect. Your ONLY priority is security, compliance, and least-privilege access.

When given an architecture scenario, you propose the most secure solution:
- All data encrypted at rest (KMS) and in transit (TLS 1.3)
- VPC with private subnets — nothing public-facing except ALB/CloudFront
- WAF in front of all public endpoints
- IAM roles with least-privilege (no wildcards)
- Secrets in AWS Secrets Manager, never in env vars
- CloudTrail + GuardDuty + Security Hub enabled
- VPC Flow Logs and S3 access logging
- Network segmentation with security groups as firewalls

You don't care about cost or reliability — only security. Be opinionated and specific.

Return ONLY valid JSON:
{
  "agent": "security",
  "proposed_services": {
    "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
  },
  "compliance_level": "e.g. HIPAA-ready / PCI-DSS / SOC2",
  "argument": "2-3 paragraphs arguing why this is the right architecture from a security perspective",
  "key_decisions": [
    {"decision": "...", "chose": "...", "risk_mitigated": "...", "trade_off": "..."}
  ]
}"""

MODERATOR_PROMPT = """You are a Principal AWS Solutions Architect moderating a debate between three specialist agents.

You have received three architecture proposals for the same scenario:
1. Cost Agent — optimized purely for minimum spend
2. Reliability Agent — optimized purely for maximum uptime
3. Security Agent — optimized purely for maximum security

Your job is to synthesize these into ONE final, balanced recommendation that:
- Picks the best ideas from each agent
- Explicitly resolves conflicts between them (e.g. cost agent wants Lambda, reliability wants ECS)
- Explains WHICH agent "won" each key decision and WHY
- Produces a realistic architecture that a real company would actually deploy

Return ONLY valid JSON:
{
  "final_architecture": {
    "layers": {
      "edge": [], "networking": [], "compute": [], "database": [], "messaging": [], "monitoring": []
    },
    "reasoning": "2-3 paragraphs explaining the synthesized recommendation"
  },
  "debate_summary": [
    {
      "topic": "what was debated (e.g. Compute layer)",
      "cost_argued": "what cost agent wanted",
      "reliability_argued": "what reliability agent wanted",
      "security_argued": "what security agent wanted",
      "winner": "cost | reliability | security | compromise",
      "final_decision": "what was chosen",
      "rationale": "why"
    }
  ],
  "scores": {
    "cost_influence_pct": 0,
    "reliability_influence_pct": 0,
    "security_influence_pct": 0
  }
}"""


#  Agent runner 

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

def run_moderator(query: str, cost: dict, reliability: dict, security: dict) -> dict:
    """Run the moderator agent to synthesize the three proposals."""
    context = f"""
SCENARIO: {query}
COST AGENT PROPOSAL:
{json.dumps(cost, indent=2)}
RELIABILITY AGENT PROPOSAL:
{json.dumps(reliability, indent=2)}
SECURITY AGENT PROPOSAL:
{json.dumps(security, indent=2)}
"""
    try:
        messages = [
            {"role": "system", "content": MODERATOR_PROMPT},
            {"role": "user",   "content": context},
        ]
        content = _llm_call_modal(messages, temperature=0.3)
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)}


#  Main debate orchestrator 

@observe(name="multi_agent_debate")
def run_debate(user_query: str) -> dict:
    """Run the full multi-agent debate for a cloud architecture query.

    Runs the 3 specialist agents in parallel, then passes all proposals
    to the moderator for synthesis.

    Args:
        user_query: natural language cloud architecture scenario

    Returns:
        Full debate result with individual proposals + synthesized final architecture
    """
    print(f"\n[Debate] Query: {user_query[:80]}...")
    print("[Debate] Running 3 agents in parallel...")

    # Run the 3 specialist agents concurrently
    agents = [
        ("cost",        COST_AGENT_PROMPT),
        ("reliability", RELIABILITY_AGENT_PROMPT),
        ("security",    SECURITY_AGENT_PROMPT),
    ]

    proposals = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(run_agent, prompt, user_query, name): name
            for name, prompt in agents
        }
        for future in as_completed(futures):
            name = futures[future]
            proposals[name] = future.result()
            print(f"  {name.capitalize()} agent done")

    # Run the moderator
    print("[Debate] Moderator synthesizing...")
    synthesis = run_moderator(
        user_query,
        proposals["cost"],
        proposals["reliability"],
        proposals["security"],
    )
    print("[Debate] Done.")

    return {
        "query":       user_query,
        "proposals": {
            "cost":        proposals["cost"],
            "reliability": proposals["reliability"],
            "security":    proposals["security"],
        },
        "synthesis":   synthesis,
    }


if __name__ == "__main__":
    result = run_debate(
        "Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday."
    )
    print(json.dumps(result, indent=2))
