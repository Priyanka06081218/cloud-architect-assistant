# Cloud Architecture Assistant

An AI-powered tool that takes a plain-English description of a system and returns a production-ready AWS architecture — including which services to use, why, how much it costs, the Terraform code to build it, and a diagram to visualize it.

**Live API:** https://cloud-assistant-architect-production.up.railway.app  
**API Docs:** https://cloud-assistant-architect-production.up.railway.app/docs  
**Fine-tuned model:** [Priyanka1218/cloud-architect-llama](https://huggingface.co/Priyanka1218/cloud-architect-llama)

---

## The problem this solves

AWS has over 200 services, and choosing the right combination for a given workload is genuinely hard. Most engineers default to what they already know, which often means over-engineering with EC2 when Lambda would be cheaper, or under-engineering with a single-AZ RDS when the system actually needs high availability.

Existing tools like the AWS Well-Architected Tool ask you questions and give you a report. Cloudcraft lets you draw diagrams. Neither actually tells you what to build or writes the code for you.

This project does all of that. You describe your system in a sentence or two, and it returns a complete technical recommendation with reasoning, cost breakdown, and working Terraform — all in under three minutes for a new query, and under two seconds if a similar one has been asked before.

---

## Demo

![Architecture recommendation, cost estimate, Terraform, and diagram](docs/demo.gif)

![Architecture drift detection — scanning a real AWS account](docs/demo-drift.gif)

---

## What you get back

When you send a query like *"Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday"*, the system returns six things:

**Architecture recommendation.** A layered breakdown of which AWS services to use — edge (CloudFront, WAF), networking (VPC, ALB, subnets), compute (ECS Fargate, Lambda, Auto Scaling), database (Aurora, DynamoDB, ElastiCache), messaging (SQS, SNS), and monitoring (CloudWatch, X-Ray, GuardDuty). Every architecture is guaranteed to include a VPC — this is enforced programmatically after the LLM call, not just hoped for in the prompt.

**Trade-off analysis.** For each major decision, the system explains what it chose and why. For example: "Chose ECS Fargate over EC2 Auto Scaling because your workload has variable traffic and Fargate removes the need to manage instance types and AMI updates. Switch to EC2 if you need GPU access or custom kernel modules."

**Cost estimate.** A monthly breakdown per service, with scale-aware pricing. The cost model knows that a system handling 5,000 users per day needs one instance of a service, while a system handling 5,000,000 users per day needs 10x to 18x as many. It also accounts for multi-region deployments, which double the cost of most services. The model covers 130+ AWS services with per-service flags for whether they auto-scale (like Aurora Serverless) or need explicit multipliers.

**Terraform HCL.** Production-ready infrastructure-as-code, retrieved from real GitHub repositories and adapted to the recommended services. Includes VPC, security groups, IAM roles, and service-specific configuration with parameterized variables.

**Architecture diagram.** A Mermaid flowchart showing the data flow between services, rendered inline in the API response.

**Multi-agent debate.** An alternative endpoint that runs three specialized agents in parallel — one optimizing purely for cost, one for reliability, and one for security — and then runs a Moderator agent that reads all three proposals and synthesizes a final recommendation. Each agent argues for its position, the Moderator resolves conflicts, and the response includes a per-topic breakdown of which agent "won" and why. This makes trade-offs explicit rather than hiding them inside a single model call.

---

## How it works

### Phase 1 — The RAG pipeline

The core of the system is a retrieval-augmented generation (RAG) pipeline. Instead of asking an LLM to generate an architecture purely from memory, the pipeline first searches a local vector database for relevant context, then passes that context to the LLM along with the user's query.

This matters because LLMs are good at reasoning but inconsistent about facts — they might confidently recommend a service that doesn't exist or suggest a pricing tier that's outdated. The vector database contains current AWS documentation, whitepaper excerpts, Stack Overflow Q&A, and real Terraform configs scraped from GitHub, which grounds the LLM's output in real information.

**Data sources:**
- 572 AWS documentation pages across 16 service categories
- 10 AWS whitepapers including the Well-Architected Framework
- 1,226 Stack Overflow Q&A pairs from AWS architecture tags
- 36 GitHub repositories with production Terraform configurations
- 20 AWS blog posts

These are chunked, embedded using `all-MiniLM-L6-v2` (a 384-dimensional sentence transformer), and stored in ChromaDB across three collections: `architecture_patterns`, `service_comparisons`, and `terraform_examples`.

**The pipeline steps:**

1. The user's query goes to a requirement extractor, which uses GPT-4o-mini to pull out structured information: scale (number of users), workload type (API, batch, streaming, etc.), constraints (budget, compliance, latency), and region requirements.

2. The extractor's output is used to query all three ChromaDB collections in parallel, retrieving the most relevant chunks for architecture reasoning, trade-off analysis, and Terraform generation.

3. The architecture generator calls GPT-4o-mini with the user's query plus the retrieved context. The prompt enforces a strict JSON schema with six named layers plus a security layer, explicit trade-off reasoning, and a VPC requirement. A post-processing step then reads the networking layer and programmatically inserts VPC if the LLM omitted it.

4. The cost calculator estimates monthly spend. It does not call the LLM — it looks up each service in a pricing table and applies multipliers based on the extracted scale (number of users).

5. The Terraform generator makes a second LLM call, this time with retrieved Terraform examples as context, to produce HCL for the recommended services.

6. The diagram generator produces a Mermaid flowchart from the architecture layers — no LLM involved, just string formatting.

### Phase 2 — Production deployment

The backend runs on Railway as a Docker container, always-on with no cold starts. Two features make it work in production:

**Semantic caching.** Every response is stored in Upstash Vector with its embedding. Before running the full pipeline on a new query, the system checks whether a semantically similar query has been answered before — if the cosine similarity between the new query and a cached one is 0.92 or higher, it returns the cached response in under 2 seconds instead of running the full pipeline. This handles the common case where users ask the same question slightly differently ("serverless API for 10k users" vs. "Lambda backend for 10,000 daily users").

**Metrics and observability.** A background thread pushes 41 Prometheus metric series to Grafana Cloud every 15 seconds using Prometheus remote_write. These include request counts, latency histograms at p50/p90/p95/p99, cache hit and miss rates, and container memory usage. The push is implemented without any protobuf library dependency — just Python and `python-snappy` for compression.

### Phase 3 — LLM observability

Every LLM call in the pipeline is wrapped with Langfuse tracing. This means that for every request that hits the API, there is a complete trace in Langfuse showing:

- Which functions were called and in what order
- The exact prompt sent to the LLM
- The exact response returned
- Token counts (input and output)
- The model used and the temperature setting
- Total latency per step

This is implemented using Langfuse's `@observe` decorator, which wraps any Python function and automatically captures its inputs, outputs, and timing. The architecture generator and Terraform generator are decorated with `as_type="generation"` to tell Langfuse they are LLM calls. The top-level `run_pipeline` function is decorated as a span, so the full trace shows the pipeline as a parent with nested LLM calls as children.

If the Langfuse environment variables are not set, the decorators silently become no-ops and the pipeline runs normally without tracing.

Langfuse is pinned to version `>=2.24.0,<3.0.0` because version 3 removed the `langfuse.decorators` module that the codebase relies on.

### Phase 4 — Scale-aware cost model

The original cost calculator added up fixed monthly prices per service regardless of how large the system needed to be. This made the model wrong in both directions — it underpriced large-scale systems and gave inflated estimates for small ones.

The updated model introduces two multipliers:

**Compute multiplier.** Based on the number of users extracted from the query, scalable services (those that need more instances as load increases) are multiplied by a factor that ranges from 1x (under 5,000 users per day) to 18x (over 5 million users per day). The tiers are: under 5k users = 1x, under 50k = 2x, under 500k = 4x, under 5M = 10x, above 5M = 18x. The cap at 18x prevents runaway cost estimates for extreme-scale queries.

**Region multiplier.** Services that need to be replicated across regions are doubled in cost when the query specifies a multi-region requirement.

Services are flagged in the pricing table as `scalable` (gets compute multiplier), `global` (no multiplier, billed once regardless of region), or neither (gets only the region multiplier if applicable). For example, Aurora Serverless is marked as not scalable because it handles its own scaling internally — applying a compute multiplier to it would be double-counting. AWS Shield Advanced is excluded from cost estimation entirely because its $3,000/month flat fee would dominate every estimate and distort the comparison between architectures.

### Evaluation harness

The system is tested against a set of 20 golden scenarios — hand-crafted queries that cover the main architecture patterns (serverless APIs, multi-region databases, compliance-heavy workloads, high-scale compute, batch processing, and real-time streaming). Each scenario has a known-good expected output and is scored on three dimensions:

- **Completeness (40%):** Does the response include all six architecture layers, trade-offs, cost estimate, Terraform, and diagram?
- **Compliance (30%):** For queries with compliance requirements (HIPAA, SOC 2, PCI-DSS), does the response include the right security services (KMS encryption, GuardDuty, CloudTrail, WAF)?
- **Cost accuracy (30%):** Is the estimated cost within the expected range for the workload size?

The current score is **20/20 (100%)**. Getting there required several rounds of fixes: adding a security layer to the JSON schema so compliance-sensitive services had a named home, adding SOC 2 as a compliance trigger alongside "soc2" and "soc-2", removing Shield Advanced from the pricing table, capping the compute multiplier at 18x, and adding the VPC post-processing guarantee.

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Backend API | FastAPI + Python 3.11 |
| Frontend | Next.js 16 + TypeScript + Tailwind CSS |
| Vector database | ChromaDB + Sentence Transformers (all-MiniLM-L6-v2) |
| Semantic cache | Upstash Vector (384-dim, cosine similarity, threshold 0.92) |
| LLM | GPT-4o-mini (primary) + Fine-tuned LLaMA 3.1 8B (via vLLM on Modal) |
| LLM observability | Langfuse (v2.60.x, @observe decorator, trace per request) |
| Deployment | Railway (Docker, always-on, no cold starts) |
| Metrics | Prometheus remote_write → Grafana Cloud (41 metric series, every 15s) |
| Fine-tuning | QLoRA on LLaMA 3.1 8B via HuggingFace PEFT |
| Drift detection | boto3 (read-only AWS scanner) |
| IaC | Terraform (VPC, EKS, ECR, ElastiCache, IAM) |
| CI/CD | GitHub Actions → ECR → EKS rolling deploy |

---

## Performance

Benchmarked with Locust against the live Railway deployment at 20 concurrent users over a 120-second run.

| Scenario | p50 | p95 |
|----------|-----|-----|
| Cold query (cache miss, full pipeline) | ~120s | ~155s |
| Warm query (cache hit, cosine >= 0.92) | <2s | <3s |
| GET /health | 45ms | 90ms |

Cold queries are slow because the pipeline makes two LLM calls (architecture + Terraform), each of which round-trips GPT-4o-mini, plus three ChromaDB vector searches with embedding generation. The semantic cache absorbs most repeat traffic — after a warmup period with diverse queries, cache hit rate settles around 71%, meaning the typical user sees a sub-2s response.

---

## Running locally

You will need Python 3.11+, Node 20+, and Docker.

```bash
git clone https://github.com/Priyanka06081218/cloud-architect-assistant.git
cd cloud-architect-assistant

# Copy the environment template and add your OpenAI key
cp .env.example .env

# Install Python dependencies
pip install -r requirements.txt

# Start the backend
uvicorn app.main:app --reload --port 8000

# In a separate terminal, start the frontend
cd app/frontend
npm install && npm run dev
# Frontend will be at http://localhost:3000
```

With Docker:
```bash
docker-compose up --build
```

The app works with just `OPENAI_API_KEY` set. The optional services each unlock a feature:

| Environment variable | What it enables |
|---------------------|----------------|
| `UPSTASH_VECTOR_URL` + `UPSTASH_VECTOR_TOKEN` | Semantic cache (falls back to in-memory without this) |
| `GRAFANA_REMOTE_WRITE_URL` + `GRAFANA_REMOTE_WRITE_USER` + `GRAFANA_REMOTE_WRITE_TOKEN` | Metrics push to Grafana Cloud |
| `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` + `LANGFUSE_HOST` | LLM tracing in Langfuse (silently disabled without this) |
| `VLLM_BASE_URL` + `FINETUNE_MODEL` | Use the fine-tuned LLaMA instead of GPT-4o-mini |
| `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | Drift detection against a real AWS account |

---

## API reference

### POST /analyze

The main endpoint. Takes a natural-language query and returns the full architecture recommendation.

```bash
curl -X POST https://cloud-assistant-architect-production.up.railway.app/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday."}'
```

The response includes `scenario_summary`, `architecture` (layers as lists of service names), `trade_offs`, `cost` (monthly breakdown + total), `terraform` (HCL string), `diagram` (Mermaid string), `cached` (boolean), and `elapsed_seconds`.

### POST /analyze/debate

Same input, but runs the three-agent debate instead of the single-pipeline. Returns each agent's proposal plus the Moderator's synthesis with a per-topic debate summary and influence scores (what percentage of the final architecture came from each agent).

### POST /drift

Takes the `architecture` object from `/analyze` plus read-only AWS credentials, scans the actual AWS account, and returns a list of drift findings with severity scores and fix instructions.

### GET /health

Returns `{"status": "healthy", "cache_size": N, "cache_backend": "redis" | "memory"}`. Used by Railway's health check.

---

## Project structure

```
cloud-architect-assistant/
  app/
    main.py                    # FastAPI app — endpoints, caching, CORS, startup hooks
    metrics_pusher.py          # Prometheus remote_write encoder (pure Python + snappy)
    frontend/                  # Next.js frontend
  pipeline/
    pipeline.py                # Orchestrates all 6 steps of the RAG pipeline
    extractor.py               # Requirement extraction (LLM)
    retriever.py               # ChromaDB vector search
    generator.py               # Architecture and Terraform generation (LLM)
    cost_calculator.py         # Pricing table + scale-aware cost estimation (no LLM)
    diagram.py                 # Mermaid diagram generation (no LLM)
    cache.py                   # Upstash Vector semantic cache
    agents.py                  # Multi-agent debate system
    drift_detector.py          # AWS account scanner + drift comparison
    observability.py           # Langfuse startup check and connectivity test
  collectors/                  # Scripts that built the training data
    collect_aws_docs.py
    collect_whitepapers.py
    collect_stackoverflow.py
    collect_github.py
  processors/
    process_and_load.py        # Chunk, embed, and load data into ChromaDB
  training/
    generate_synthetic.py      # Fast synthetic training pair generation
    finetune.py                # QLoRA fine-tuning script for LLaMA 3.1 8B
  evaluation/
    golden_set.json            # 20 hand-crafted test scenarios with expected outputs
    run_eval.py                # Evaluation harness — completeness, compliance, cost scoring
  scripts/
    patch_chromadb.py          # Build-time fix for chromadb 0.5.x pickle format issue
  infra/
    terraform/main.tf          # EKS, ECR, VPC, ElastiCache, IAM
    k8s/                       # Kubernetes manifests
  locustfile.py                # Load test — cold and warm query scenarios
  Dockerfile                   # Production image (python:3.11-slim)
  .env.example                 # Documents all environment variables
```

---

## Fine-tuning

The system supports swapping GPT-4o-mini for a fine-tuned LLaMA 3.1 8B model, served via vLLM on Modal. The fine-tuned model was trained on 1,732 instruction pairs — 1,212 from running real queries through the full RAG pipeline (gold-quality data), and 520 synthetic pairs generated directly via GPT-4o-mini to fill in underrepresented scenarios.

Training used QLoRA: 4-bit NF4 quantization with LoRA adapters at rank 16. Three epochs on an A100 GPU, roughly 80 minutes of training time. Final training loss: 0.21, token accuracy: 92.6%.

The fine-tuned model learned the output format (consistent JSON structure across all scenarios) better than the base model, but GPT-4o-mini still produces higher-quality reasoning for unfamiliar scenarios. The system falls back to GPT-4o-mini if the vLLM endpoint is unavailable.

```bash
# Generate synthetic training pairs
python -m training.generate_synthetic --target 10000 --workers 4

# Fine-tune (requires GPU)
python -m training.finetune train --data data/finetune/pairs.jsonl

# Merge adapter weights into the base model
python -m training.finetune merge
```

---

## Architecture drift detection

After getting an architecture recommendation, you can connect a real AWS account and check whether what's actually deployed matches what the system recommended. The drift detector uses boto3 with read-only credentials to scan 15 service categories, then compares the findings to the recommendation.

Each gap is flagged with a severity level (critical, high, medium, or low) and a specific fix instruction. For example: "GuardDuty is recommended but not enabled. Enable it at AWS Console → GuardDuty → Get Started. No additional infrastructure required." The overall summary is a score from 0 to 100 and a letter grade (A through F).

Services scanned: EC2, ECS, Lambda, RDS, DynamoDB, ElastiCache, ALB, CloudFront, API Gateway, SQS, S3, CloudWatch alarms, CloudTrail, GuardDuty, and WAF.

The credentials are used only for the scan and never stored anywhere.

---

## Running the evaluation

```bash
cd evaluation
python run_eval.py
```

This runs all 20 golden scenarios through the live pipeline and prints a detailed score breakdown. Each scenario is scored 0–1 on completeness, compliance, and cost accuracy, then weighted and summed for an overall score out of 20. Current score: 20/20.

---

## Deployment

The live API runs on Railway at the link at the top of this file. Railway watches for pushes and rebuilds automatically.

For AWS deployment, the full infrastructure is defined in Terraform:

```bash
cd infra/terraform
terraform init && terraform apply
```

This provisions a VPC, EKS cluster, ECR repository, ElastiCache cluster, and the required IAM roles. The GitHub Actions workflow (`.github/workflows/deploy.yml`) handles building the Docker image, pushing it to ECR, and doing a rolling deploy to EKS with automatic rollback if the health check fails.

