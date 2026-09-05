# training/collect_finetune_data.py
#
# Generates Alpaca-style fine-tuning pairs by running the RAG pipeline
# on a large set of curated queries and saving (instruction, response) pairs.
#
# Output: data/finetune/pairs.jsonl
#         Each line: {"instruction": "...", "input": "", "response": "..."}
#
# Run:
#   python -m training.collect_finetune_data
#
# Tips:
#   - Uses the existing GPT-4o-mini pipeline — each query costs ~$0.01
#   - 500 queries ≈ $5 total, ~7 hours at 45s/query (run overnight)
#   - Resume-safe: skips queries already saved in pairs.jsonl
#   - Failed queries are logged to data/finetune/failed.jsonl for retry

import json
import time
import logging
import os
import sys

# Add project root to path so imports work when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.pipeline import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


OUTPUT_DIR   = "data/finetune"
PAIRS_FILE   = f"{OUTPUT_DIR}/pairs.jsonl"
FAILED_FILE  = f"{OUTPUT_DIR}/failed.jsonl"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 500 diverse queries covering all major AWS architecture patterns.
# Grouped by theme for variety in the training set.

QUERIES = [
    #  Web & API workloads 
    "Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday.",
    "I need a serverless API for a mobile app with 50k daily active users. Keep costs minimal.",
    "Design a scalable REST API backend for a SaaS product with 10k business customers.",
    "Build a high-availability web application architecture for a news site with 5M monthly visitors.",
    "Design an AWS architecture for a real-time ride-sharing app like Uber with global users.",
    "Create an architecture for a social media platform handling 1M posts per day.",
    "Design a multi-tenant SaaS architecture on AWS for a B2B analytics product.",
    "Build an AWS architecture for an online marketplace with buyer/seller workflows.",
    "Design a low-latency API for a financial trading platform with sub-10ms response requirements.",
    "Create an architecture for a job board website with full-text search and resume uploads.",
    "Design AWS infrastructure for a real-time sports score tracking app with 500k concurrent viewers.",
    "Build a scalable architecture for an online food delivery platform.",
    "Design an AWS architecture for a hotel booking platform with dynamic pricing.",
    "Create a high-performance architecture for a CDN-backed media streaming website.",
    "Design an architecture for a real-time multiplayer browser game.",

    #  Data & Analytics 
    "Design a HIPAA-compliant data pipeline on AWS for processing patient health records in real time.",
    "Build a real-time analytics pipeline for processing 100GB of clickstream data per day.",
    "Design a data lake architecture on AWS for a retail company with petabytes of historical data.",
    "Create a batch ETL pipeline on AWS to process nightly financial transaction data.",
    "Design a machine learning feature store on AWS for a recommendation system.",
    "Build a real-time fraud detection pipeline on AWS processing 10k transactions per second.",
    "Design a data warehouse on AWS for a company migrating from on-premise Teradata.",
    "Create an IoT data ingestion pipeline for 100k connected devices sending sensor data.",
    "Design a log aggregation and analysis pipeline for a microservices platform.",
    "Build a real-time leaderboard system on AWS for a gaming platform.",
    "Design a customer 360 data platform on AWS aggregating data from 20 different sources.",
    "Create a data pipeline for training machine learning models on user behavior data.",
    "Design a CDC (change data capture) pipeline from RDS to a Redshift data warehouse.",
    "Build a real-time recommendation engine backend on AWS.",
    "Design a time-series data platform for monitoring industrial equipment.",

    #  Microservices & Containers 
    "Design a microservices architecture on AWS EKS for a fintech application.",
    "Migrate a monolithic e-commerce application to microservices on AWS.",
    "Design a service mesh architecture on EKS with Istio for a payment platform.",
    "Build a container-based CI/CD pipeline architecture on AWS.",
    "Design a blue/green deployment architecture on ECS for zero-downtime releases.",
    "Create an event-driven microservices architecture on AWS using SQS and Lambda.",
    "Design a saga pattern implementation on AWS for distributed transactions.",
    "Build a canary deployment architecture on EKS for a high-traffic API.",
    "Design a sidecar proxy pattern on ECS for a service mesh.",
    "Create an AWS architecture for running 200 microservices with independent scaling.",

    #  Serverless 
    "Design a fully serverless architecture for a document processing pipeline.",
    "Build a serverless image resizing and CDN delivery pipeline on AWS.",
    "Design a serverless GraphQL API backend for a React Native mobile app.",
    "Create a serverless scheduled job architecture for nightly report generation.",
    "Design a serverless webhook processing system handling 1M events per day.",
    "Build a serverless ML inference pipeline for real-time predictions.",
    "Design an event-driven serverless architecture for an order fulfillment system.",
    "Create a serverless architecture for a PDF generation and email delivery service.",
    "Design a serverless backend for a single-page application with Auth0 integration.",
    "Build a serverless data transformation pipeline for a marketing analytics platform.",

    #  Databases & Storage 
    "Design a multi-region active-active database architecture for a global application.",
    "Build a caching strategy on AWS for a high-read database with 100k QPS.",
    "Design a database sharding architecture on AWS RDS for horizontal scaling.",
    "Create a CQRS pattern implementation on AWS with separate read/write databases.",
    "Design a document storage and retrieval system for a legal tech platform.",
    "Build an object storage architecture for a media company with 10PB of video files.",
    "Design a search infrastructure using OpenSearch for an e-commerce catalog with 5M SKUs.",
    "Create a graph database architecture on AWS for a social network.",
    "Design a time-series database architecture for a metrics collection platform.",
    "Build a global key-value store architecture on AWS for session management.",

    #  Security & Compliance 
    "Design a PCI-DSS compliant payment processing architecture on AWS.",
    "Build a SOC 2 compliant SaaS architecture on AWS with full audit logging.",
    "Design a zero-trust network architecture on AWS for a financial institution.",
    "Create a secrets management architecture on AWS using Vault and KMS.",
    "Design a GDPR-compliant data platform with right-to-deletion support on AWS.",
    "Build a DDoS protection architecture for a high-profile government website.",
    "Design an AWS architecture with end-to-end encryption for a healthcare portal.",
    "Create a WAF and bot protection architecture for an e-commerce platform.",
    "Design an IAM governance architecture for a large enterprise with 50 teams.",
    "Build a VPN and private connectivity architecture for a hybrid cloud setup.",

    #  Cost Optimization 
    "Design a cost-optimized architecture for a startup with a $500/month AWS budget.",
    "Optimize an existing AWS architecture that costs $50k/month — reduce by 40%.",
    "Design a spot instance strategy for a batch processing workload.",
    "Build a multi-tier storage lifecycle architecture to minimize S3 costs.",
    "Design an auto-scaling architecture to minimize compute costs during off-peak hours.",
    "Create a serverless-first architecture to keep costs under $100/month for a side project.",
    "Design a reserved instance strategy for a stable production workload.",
    "Build a Graviton-based compute architecture for 30% cost savings.",
    "Design a cost allocation and tagging strategy for a multi-team AWS account.",
    "Create a FinOps dashboard architecture for real-time AWS cost visibility.",

    #  High Availability & Disaster Recovery 
    "Design a multi-region failover architecture with RPO of 1 minute and RTO of 5 minutes.",
    "Build an active-passive disaster recovery architecture for a banking application.",
    "Design a chaos engineering platform on AWS for testing resilience.",
    "Create a backup and restore architecture for a database with 10TB of critical data.",
    "Design a circuit breaker pattern implementation on AWS for microservices.",
    "Build a multi-AZ high availability architecture for a 99.99% SLA requirement.",
    "Design a self-healing infrastructure architecture using AWS Auto Scaling and health checks.",
    "Create an architecture for gradual traffic migration during a major database migration.",
    "Design a warm standby DR architecture for a mission-critical ERP system.",
    "Build an architecture for handling AWS region outages with automatic failover.",

    #  AI/ML Workloads 
    "Design an ML training infrastructure on AWS for fine-tuning large language models.",
    "Build a real-time ML inference architecture serving 10k predictions per second.",
    "Design a feature store and model registry architecture on AWS SageMaker.",
    "Create an A/B testing infrastructure for comparing ML model versions in production.",
    "Design a computer vision pipeline on AWS for processing security camera footage.",
    "Build an NLP document classification pipeline for processing legal contracts.",
    "Design a recommendation system architecture on AWS for a streaming platform.",
    "Create a real-time anomaly detection system on AWS for network traffic.",
    "Design a distributed model training architecture on AWS with GPU clusters.",
    "Build an MLOps platform on AWS for automated model training and deployment.",

    #  DevOps & Platform Engineering 
    "Design a complete CI/CD platform on AWS for 100 development teams.",
    "Build a developer platform on AWS with self-service infrastructure provisioning.",
    "Design a GitOps architecture on EKS using ArgoCD for application deployments.",
    "Create an infrastructure as code governance architecture using AWS Service Catalog.",
    "Design a centralized logging and observability platform for a microservices system.",
    "Build a distributed tracing architecture on AWS for debugging production issues.",
    "Design a chaos engineering platform on AWS with automated fault injection.",
    "Create an AWS landing zone architecture for a 200-account enterprise organization.",
    "Design a secrets rotation architecture for zero-downtime credential management.",
    "Build a compliance-as-code platform on AWS with automated policy enforcement.",

    #  Messaging & Event Streaming 
    "Design a real-time event streaming architecture for a logistics tracking system.",
    "Build a pub/sub messaging architecture for a notification system with 10M users.",
    "Design a Kafka-based event bus on AWS MSK for decoupling microservices.",
    "Create a dead letter queue and retry architecture for reliable message processing.",
    "Design an event sourcing pattern on AWS with Kinesis and DynamoDB.",
    "Build a CQRS event-driven architecture on AWS for a banking ledger.",
    "Design a fan-out messaging pattern on AWS for a multi-channel notification system.",
    "Create a message deduplication architecture for exactly-once processing.",
    "Design a priority queue architecture on AWS for a job scheduling system.",
    "Build a real-time chat infrastructure on AWS supporting 1M concurrent connections.",

    #  Edge & Global 
    "Design a global multi-region architecture for a gaming company with players in 50 countries.",
    "Build a low-latency edge computing architecture using Lambda@Edge and CloudFront.",
    "Design a CDN strategy for a video platform serving 4K content to global users.",
    "Create an anycast routing architecture on AWS for global API distribution.",
    "Design a multi-CDN failover architecture for a high-traffic media website.",
    "Build an AWS architecture for a live streaming platform with 1M concurrent viewers.",
    "Design an edge caching strategy for a mobile app with offline-first requirements.",
    "Create an architecture for serving personalized content at the CDN edge.",
    "Design a global DNS failover architecture with Route 53 health checks.",
    "Build a latency-based routing architecture for a globally distributed API.",

    #  Migration & Hybrid 
    "Design a lift-and-shift migration architecture for a 100-server on-premise datacenter.",
    "Build a hybrid cloud architecture connecting on-premise SAP to AWS services.",
    "Design a database migration architecture from Oracle to Aurora PostgreSQL.",
    "Create a phased migration plan from a monolith to microservices on AWS.",
    "Design a hybrid DNS architecture for a company with partial AWS migration.",
    "Build an AWS Direct Connect architecture for a financial institution.",
    "Design a mainframe modernization architecture using AWS services.",
    "Create a VMware to EKS migration architecture.",
    "Design a Windows Server workload migration to AWS with AD integration.",
    "Build a legacy Oracle Data Warehouse migration to Redshift architecture.",

    #  Industry-specific 
    "Design an AWS architecture for a digital banking platform with 2M customers.",
    "Build a telemedicine platform architecture on AWS with video consultations.",
    "Design an AWS architecture for an e-learning platform with video courses and 500k students.",
    "Create a supply chain management architecture on AWS with real-time inventory tracking.",
    "Design an AWS architecture for a smart city IoT platform with 1M sensors.",
    "Build a real estate listing platform architecture with map-based search.",
    "Design an AWS architecture for a legal document management system with e-signatures.",
    "Create an HR platform architecture on AWS with payroll processing.",
    "Design an AWS architecture for a ride-hailing driver dispatch system.",
    "Build a fleet management architecture on AWS with GPS tracking.",
    "Design an AWS architecture for a cryptocurrency exchange with real-time order books.",
    "Create a clinical trial data management platform architecture on AWS.",
    "Design an AWS architecture for a media production company with 4K video editing.",
    "Build a government benefits portal architecture on AWS handling 10M citizens.",
    "Design an AWS architecture for a logistics company with last-mile delivery tracking.",

    #  Networking deep dives 
    "Design a hub-and-spoke VPC architecture for a large enterprise.",
    "Build a transit gateway architecture connecting 50 VPCs across 3 AWS accounts.",
    "Design a private API architecture using VPC endpoints and PrivateLink.",
    "Create a network segmentation architecture for PCI compliance on AWS.",
    "Design a BGP-based multi-path routing architecture on AWS Direct Connect.",
    "Build a software-defined networking architecture on AWS with Cisco CSR.",
    "Design a micro-segmentation architecture using AWS security groups and NACLs.",
    "Create an IPv6 migration architecture for an existing IPv4-only AWS deployment.",
    "Design an SD-WAN to AWS integration architecture for a retail chain.",
    "Build a network monitoring and packet inspection architecture on AWS.",

    #  Performance & Scale 
    "Design an AWS architecture to handle 1 million API requests per second.",
    "Build a read replica strategy for a PostgreSQL database with 50k read QPS.",
    "Design a horizontal scaling architecture for a stateful WebSocket server.",
    "Create a connection pooling architecture for Lambda functions accessing RDS.",
    "Design an architecture for a Black Friday flash sale surviving 10x normal traffic.",
    "Build a pre-warming strategy for Lambda and Aurora Serverless for burst traffic.",
    "Design a global rate limiting architecture across multiple API Gateway regions.",
    "Create a thundering herd prevention architecture using exponential backoff.",
    "Design a bulk data import architecture handling 100GB CSV uploads.",
    "Build a distributed locking architecture on AWS for concurrent job scheduling.",

    #  Observability 
    "Design a full observability stack on AWS with metrics, logs, and traces.",
    "Build a centralized SIEM architecture on AWS for security event monitoring.",
    "Design an application performance monitoring architecture using X-Ray and CloudWatch.",
    "Create a real-time alerting architecture for SLO/SLA breach detection.",
    "Design a synthetic monitoring architecture for proactive availability testing.",
    "Build a log analytics platform on AWS for petabyte-scale log ingestion.",
    "Design a cost anomaly detection architecture using AWS Cost Explorer and SNS.",
    "Create a distributed tracing architecture across 50 microservices.",
    "Design a custom metrics pipeline from application code to CloudWatch dashboards.",
    "Build a runbook automation architecture using Systems Manager and Lambda.",

    #  Storage specializations 
    "Design a tiered storage architecture for a backup system with 7-year retention.",
    "Build a content management architecture for a media company with 100TB of assets.",
    "Design a distributed file system architecture on AWS for HPC workloads.",
    "Create an archive and retrieval architecture using S3 Glacier for compliance.",
    "Design a shared file storage architecture on AWS EFS for containerized apps.",
    "Build a versioned artifact storage architecture for a software build system.",
    "Design a cross-region replication architecture for S3 with consistency guarantees.",
    "Create a data governance architecture with automated classification and tagging.",
    "Design a NAS replacement architecture on AWS for a media production studio.",
    "Build a delta lake architecture on S3 for ACID transactions on big data.",

    #  Auth & Identity 
    "Design an identity and access management architecture for a multi-cloud enterprise.",
    "Build a federated SSO architecture on AWS connecting Okta and multiple SaaS apps.",
    "Design a CIAM architecture for a consumer app with 10M users.",
    "Create a delegated administration architecture using AWS Organizations and SCPs.",
    "Design an API key management architecture for a public developer API.",
    "Build an OAuth 2.0 authorization server architecture on AWS.",
    "Design a passwordless authentication architecture using magic links and WebAuthn.",
    "Create a machine-to-machine authentication architecture for microservices.",
    "Design a privileged access management architecture on AWS for production systems.",
    "Build an audit trail architecture for all user actions in a financial application.",

    #  Batch & HPC 
    "Design a genomics data processing pipeline on AWS handling terabytes of DNA sequences.",
    "Build a financial Monte Carlo simulation architecture on AWS using Spot instances.",
    "Design a video transcoding pipeline on AWS for a streaming platform.",
    "Create an image batch processing architecture for a satellite imagery company.",
    "Design an HPC cluster architecture on AWS for computational fluid dynamics.",
    "Build a distributed rendering architecture on AWS for a visual effects studio.",
    "Design a large-scale data migration architecture moving 1PB from on-premise to AWS.",
    "Create an nightly batch reconciliation architecture for a payment processor.",
    "Design a parallel simulation architecture on AWS Batch for drug discovery.",
    "Build a distributed ETL architecture processing 50TB of data daily.",

    #  Cost tradeoffs & budget scenarios 
    "Design the cheapest possible architecture for a startup MVP with 1k daily users.",
    "Compare ECS Fargate vs EC2 for a containerized API with variable traffic.",
    "Design an architecture choosing between RDS Multi-AZ vs Aurora for high availability.",
    "Compare API Gateway vs ALB for routing traffic to Lambda functions.",
    "Design an architecture deciding between DynamoDB vs MongoDB Atlas for a document store.",
    "Compare Lambda vs ECS for a long-running video processing workload.",
    "Design an architecture comparing Kinesis vs SQS for event streaming.",
    "Compare ElastiCache Redis vs DynamoDB DAX for database caching.",
    "Design an architecture comparing CloudFront vs ALB for web application delivery.",
    "Compare Aurora Serverless v2 vs RDS Provisioned for variable database workloads.",
]



def load_done() -> set[str]:
    """Return set of queries already saved (for resume support)."""
    done = set()
    if os.path.exists(PAIRS_FILE):
        with open(PAIRS_FILE) as f:
            for line in f:
                try:
                    pair = json.loads(line)
                    done.add(pair["instruction"])
                except Exception:
                    pass
    return done


def load_failed() -> set[str]:
    """Return set of queries that previously failed."""
    failed = set()
    if os.path.exists(FAILED_FILE):
        with open(FAILED_FILE) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    failed.add(rec["query"])
                except Exception:
                    pass
    return failed


def save_pair(query: str, response: dict):
    """Save one (instruction, response) pair to JSONL."""
    # The "response" field is the full JSON pipeline output, serialized as string.
    # This teaches the model both the reasoning and the structured output format.
    pair = {
        "instruction": query,
        "input":       "",
        "response":    json.dumps(response, indent=2),
    }
    with open(PAIRS_FILE, "a") as f:
        f.write(json.dumps(pair) + "\n")


def save_failed(query: str, error: str):
    """Log a failed query for later retry."""
    with open(FAILED_FILE, "a") as f:
        f.write(json.dumps({"query": query, "error": error}) + "\n")



def collect(queries: list[str], delay_seconds: float = 2.0):
    """Run the pipeline on each query and save the pair.

    Args:
        queries:       list of natural language queries
        delay_seconds: pause between queries (rate limiting)
    """
    done   = load_done()
    failed = load_failed()

    todo = [q for q in queries if q not in done and q not in failed]
    log.info(f"Total queries: {len(queries)}")
    log.info(f"Already done:  {len(done)}")
    log.info(f"Previously failed: {len(failed)}")
    log.info(f"To process:    {len(todo)}")

    for i, query in enumerate(todo, 1):
        log.info(f"\n[{i}/{len(todo)}] {query[:80]}...")
        start = time.time()

        try:
            response = run_pipeline(query)
            elapsed  = round(time.time() - start, 1)
            save_pair(query, response)
            log.info(f"  Saved in {elapsed}s  |  total pairs: {len(done) + i}")

        except Exception as e:
            log.error(f"  Failed: {e}")
            save_failed(query, str(e))

        # Small pause to avoid hammering the OpenAI API
        if i < len(todo):
            time.sleep(delay_seconds)

    total_done = len(load_done())
    log.info(f"\nDone. Total pairs collected: {total_done}")
    log.info(f"Output: {PAIRS_FILE}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Collect fine-tuning data for the cloud architect assistant.")
    parser.add_argument("--limit",  type=int, default=None,
                        help="Max number of queries to process (default: all)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry previously failed queries")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds to wait between queries (default: 2)")
    args = parser.parse_args()

    queries = QUERIES
    if args.retry_failed:
        failed = list(load_failed())
        log.info(f"Retrying {len(failed)} failed queries")
        queries = failed + [q for q in QUERIES if q not in set(failed)]

    if args.limit:
        # Only process the first N todo queries
        done = load_done()
        failed_set = load_failed()
        todo = [q for q in queries if q not in done and q not in failed_set][:args.limit]
        queries_to_run = list(done) + todo  # keep done ones in list for proper counting
        # Actually just pass todo directly
        collect(todo, delay_seconds=args.delay)
    else:
        collect(queries, delay_seconds=args.delay)
