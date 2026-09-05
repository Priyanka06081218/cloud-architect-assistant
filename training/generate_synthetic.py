# training/generate_synthetic.py
#
# Fast synthetic training data generator.
# Generates (query, response) pairs directly via GPT-4o-mini —
# no RAG retrieval, no ChromaDB needed. ~5-8 seconds per pair.
#
# Strategy:
#   Phase 1: Run real pipeline on 250 queries  → 250 gold-quality pairs
#   Phase 2: Run THIS script for remaining N   → synthetic pairs (same format)
#   Result:  Combine both into pairs.jsonl for fine-tuning
#
#
# Cost estimate (GPT-4o-mini):
#   ~$0.003 per pair → 10,000 pairs ≈ $30 total
#
# Time estimate:
#   ~6s per pair → 10,000 pairs ≈ 17 hours
#   With 4 concurrent workers: ~4-5 hours
#
# Run:
#   python -m training.generate_synthetic --count 9750 --workers 4
#   (generates remaining pairs to reach 10k total)

import json
import time
import os
import sys
import logging
import argparse
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI
from config import OPENAI_API_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

client = OpenAI(api_key=OPENAI_API_KEY)

OUTPUT_DIR  = "data/finetune"
PAIRS_FILE  = f"{OUTPUT_DIR}/pairs.jsonl"
FAILED_FILE = f"{OUTPUT_DIR}/failed_synthetic.jsonl"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Teaches GPT the exact output format we want, with a concrete example.
# This is what the fine-tuned model will learn to replicate.

SYSTEM_PROMPT = """You are a senior AWS Solutions Architect generating training data.

For each cloud architecture query, respond with ONLY valid JSON in exactly this structure:
{
  "scenario_summary": "one sentence summary of what the client needs",
  "architecture": {
    "layers": {
      "edge":       ["list of CDN/edge services, or empty list"],
      "networking": ["load balancers, API gateway, or empty list"],
      "compute":    ["ECS, Lambda, EC2, EKS, etc."],
      "database":   ["RDS, DynamoDB, Aurora, ElastiCache, etc."],
      "messaging":  ["SQS, SNS, Kinesis if needed, or empty list"],
      "monitoring": ["CloudWatch, X-Ray, etc."]
    },
    "reasoning": "2-3 paragraphs explaining service choices covering scalability, reliability, and cost"
  },
  "trade_offs": [
    {
      "decision": "Service A vs Service B",
      "chose": "Service A",
      "reason": "why Service A fits this use case",
      "when_to_switch": "specific conditions where Service B would be better"
    }
  ],
  "cost": {
    "monthly_breakdown": [
      {"service": "Service Name", "monthly_usd": 10.0, "unit": "description"}
    ],
    "total_monthly_usd": 100.0,
    "spike_estimate_usd": 135.0,
    "optimization": "one concrete cost saving tip"
  },
  "terraform": "# complete Terraform HCL code as a string",
  "diagram": "graph TD\\n    User([User])\\n    ..."
}

Rules:
- Use exact AWS service names (e.g. "Amazon CloudFront", "AWS Lambda", "Amazon DynamoDB")
- Include 2-4 trade_offs covering compute, database, and networking decisions
- Cost estimates should be realistic us-east-1 on-demand monthly prices
- Terraform must include VPC, security groups, and all recommended services
- Diagram must be valid Mermaid flowchart syntax
- Respond ONLY with the JSON object, no markdown fences or extra text"""

# Large pool of diverse queries for synthetic generation.
# We'll randomly sample from these to generate 10k unique pairs.

QUERY_TEMPLATES = [
    # Scale variants
    "Design an AWS architecture for a {app_type} with {scale} {unit}.",
    "Build a {adjective} AWS architecture for a {app_type} serving {scale} {unit}.",
    "Create a cost-effective AWS architecture for a {app_type} handling {scale} {unit}.",
    "Design a production-ready AWS architecture for a {app_type} with {scale} {unit} and {constraint}.",
    "I need an AWS architecture for a {app_type}. Expected scale: {scale} {unit}. Priority: {priority}.",

    # Direct scenarios
    "Design an AWS architecture for {scenario}.",
    "Build a {adjective} AWS infrastructure for {scenario}.",
    "What AWS services should I use for {scenario}?",
    "Create a {constraint} AWS architecture for {scenario}.",
    "Recommend an AWS architecture for {scenario} with {priority} as the main priority.",
]

APP_TYPES = [
    "e-commerce platform", "social media app", "video streaming service",
    "mobile banking app", "SaaS dashboard", "healthcare portal", "food delivery app",
    "ride-sharing platform", "online learning platform", "real estate listing site",
    "gaming backend", "IoT sensor platform", "analytics dashboard", "CRM system",
    "API marketplace", "content management system", "logistics platform",
    "telemedicine app", "HR management system", "supply chain tracker",
    "financial trading platform", "crypto exchange", "news aggregator",
    "music streaming service", "podcast platform", "event ticketing system",
    "job board", "hotel booking platform", "insurance portal", "legal document system",
]

SCALES = [
    "1k", "5k", "10k", "50k", "100k", "500k", "1M", "5M", "10M",
    "100", "500", "2k", "20k", "200k", "2M",
]

UNITS = [
    "daily active users", "concurrent users", "monthly active users",
    "requests per second", "transactions per day", "API calls per hour",
    "events per minute", "records per day", "messages per day",
]

ADJECTIVES = [
    "highly available", "cost-optimized", "serverless", "containerized",
    "auto-scaling", "fault-tolerant", "globally distributed", "multi-region",
    "HIPAA-compliant", "PCI-DSS compliant", "zero-downtime", "event-driven",
]

CONSTRAINTS = [
    "99.99% availability SLA", "sub-100ms latency", "HIPAA compliance",
    "PCI-DSS compliance", "GDPR compliance", "minimal operational overhead",
    "a $200/month budget", "zero-downtime deployments", "multi-region failover",
    "SOC 2 compliance", "end-to-end encryption", "a serverless-first approach",
]

PRIORITIES = [
    "cost optimization", "scalability", "reliability", "security",
    "developer experience", "operational simplicity", "global performance",
    "low latency", "high throughput",
]

SCENARIOS = [
    "processing real-time sensor data from 100k IoT devices",
    "a HIPAA-compliant patient records system",
    "a real-time fraud detection system processing 10k TPS",
    "a globally distributed CDN for 4K video content",
    "a microservices migration from a monolith Rails app",
    "a machine learning model serving 50k predictions per second",
    "a data lake ingesting 10TB of logs per day",
    "a multi-tenant B2B SaaS platform with per-customer data isolation",
    "a Blue/Green deployment pipeline for a critical payment service",
    "a real-time leaderboard for a mobile game with 2M players",
    "a document processing pipeline handling 1M PDFs per day",
    "a chat application supporting 500k concurrent WebSocket connections",
    "an event-driven order fulfillment system for an e-commerce platform",
    "a genomics data analysis pipeline processing terabytes of DNA sequences",
    "a financial reconciliation batch job running nightly on 50GB datasets",
    "a recommendation engine serving personalized results in under 50ms",
    "a CI/CD platform serving 500 engineering teams",
    "a real-time bidding platform for programmatic advertising",
    "a video transcoding pipeline for user-uploaded content",
    "a distributed tracing system for a 200-service microservices platform",
]


def generate_query() -> str:
    """Generate a random, unique query from templates and word banks."""
    template = random.choice(QUERY_TEMPLATES)

    query = template.format(
        app_type=random.choice(APP_TYPES),
        scale=random.choice(SCALES),
        unit=random.choice(UNITS),
        adjective=random.choice(ADJECTIVES),
        constraint=random.choice(CONSTRAINTS),
        priority=random.choice(PRIORITIES),
        scenario=random.choice(SCENARIOS),
    )
    return query


def generate_pair(query: str) -> dict | None:
    """Call GPT-4o-mini directly to generate a (query, response) pair.

    Returns the pair dict, or None on failure.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": query},
            ],
            temperature=0.7,          # higher than pipeline for variety
            response_format={"type": "json_object"},
            timeout=60,
        )
        content = response.choices[0].message.content
        parsed  = json.loads(content)

        return {
            "instruction": query,
            "input":       "",
            "response":    json.dumps(parsed, indent=2),
        }
    except Exception as e:
        log.warning(f"Failed: {query[:60]}... → {e}")
        return None


def load_done_queries() -> set[str]:
    """Return set of instruction strings already in pairs.jsonl."""
    done = set()
    if os.path.exists(PAIRS_FILE):
        with open(PAIRS_FILE) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["instruction"])
                except Exception:
                    pass
    return done


def save_pair(pair: dict):
    with open(PAIRS_FILE, "a") as f:
        f.write(json.dumps(pair) + "\n")


def save_failed(query: str, error: str):
    with open(FAILED_FILE, "a") as f:
        f.write(json.dumps({"query": query, "error": error}) + "\n")



def run(target_count: int, workers: int):
    done       = load_done_queries()
    current    = len(done)
    needed     = target_count - current

    if needed <= 0:
        log.info(f"Already have {current} pairs — target of {target_count} reached.")
        return

    log.info(f"Currently have {current} pairs. Need {needed} more to reach {target_count}.")
    log.info(f"Running with {workers} concurrent workers.")
    log.info(f"Estimated time: {needed * 7 // workers // 60} minutes")
    log.info(f"Estimated cost: ~${needed * 0.003:.2f}")

    generated = 0
    failed    = 0
    start     = time.time()

    # Generate queries — more than needed to account for failures
    queries = [generate_query() for _ in range(needed + needed // 10)]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(generate_pair, q): q for q in queries}

        for future in as_completed(futures):
            if generated >= needed:
                # Cancel remaining futures
                for f in futures:
                    f.cancel()
                break

            query  = futures[future]
            result = future.result()

            if result:
                save_pair(result)
                generated += 1

                if generated % 50 == 0:
                    elapsed   = time.time() - start
                    rate      = generated / elapsed
                    remaining = (needed - generated) / rate if rate > 0 else 0
                    log.info(
                        f"Progress: {current + generated}/{target_count} pairs "
                        f"| {rate:.1f}/s "
                        f"| ETA: {remaining/60:.0f} min"
                    )
            else:
                failed += 1
                save_failed(query, "generation failed")

    total = len(load_done_queries())
    elapsed = time.time() - start
    log.info(f"\nDone in {elapsed/60:.1f} min")
    log.info(f"Generated: {generated}  Failed: {failed}  Total pairs: {total}")
    log.info(f"Output: {PAIRS_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic fine-tuning pairs.")
    parser.add_argument("--target",  type=int, default=10_000,
                        help="Target total pairs including existing ones (default: 10000)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Concurrent API workers (default: 4)")
    args = parser.parse_args()

    run(target_count=args.target, workers=args.workers)
