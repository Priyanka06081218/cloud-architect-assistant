# pipeline/ir.py
#
# Provider-neutral Intermediate Representation.
#
# Maps cloud-specific service names to abstract capability types (e.g., "Amazon ECS Fargate"
# → "container_compute"). This separates "what capability does the architecture need" from
# "which specific service implements it on this cloud."
#
# Used by candidates.py to generate architecture variants by swapping capability implementations,
# and by evaluator.py to reason about what a candidate can and cannot do.

from __future__ import annotations

# Abstract capability types. Each represents one logical function in an architecture.
CAPABILITIES = {
    "container_compute",   # managed containers without K8s overhead
    "serverless_compute",  # function-as-a-service; no idle cost, cold-start risk
    "kubernetes",          # full K8s control plane; highest ops complexity, highest throughput ceiling
    "vm_compute",          # bare VMs; maximum flexibility, maximum ops burden
    "relational_db",       # ACID SQL
    "nosql_db",            # document/key-value; no schema, high throughput
    "cache",               # sub-ms in-memory reads; reduces DB latency
    "message_queue",       # at-least-once async delivery
    "event_stream",        # ordered, replayable, high-throughput streaming
    "object_storage",      # binary blob store; cheap, durable, not for structured queries
    "cdn",                 # edge caching; reduces origin latency and egress cost
    "load_balancer",
    "api_gateway",         # rate limiting, auth, request routing
    "waf",                 # layer-7 threat filtering
    "key_management",      # encryption key lifecycle
    "secret_management",   # runtime secret injection
    "monitoring",
    "ml_platform",         # model training + managed inference
}

# Map lowercase service name fragments → capability type.
# Longest match wins (see _classify).
_KEYWORD_MAP: list[tuple[str, str]] = [
    # Compute — order matters: more specific first
    ("eks",                     "kubernetes"),
    ("aks",                     "kubernetes"),
    ("gke",                     "kubernetes"),
    ("kubernetes",              "kubernetes"),
    ("lambda",                  "serverless_compute"),
    ("azure functions",         "serverless_compute"),
    ("cloud functions",         "serverless_compute"),
    ("fargate",                 "container_compute"),
    ("ecs",                     "container_compute"),
    ("container apps",          "container_compute"),
    ("cloud run",               "container_compute"),
    ("app service",             "container_compute"),
    ("app engine",              "container_compute"),
    ("ec2",                     "vm_compute"),
    ("compute engine",          "vm_compute"),
    ("azure virtual machine",   "vm_compute"),
    # Databases
    ("aurora",                  "relational_db"),
    ("rds",                     "relational_db"),
    ("cloud sql",               "relational_db"),
    ("cloud spanner",           "relational_db"),
    ("azure database for postgres", "relational_db"),
    ("azure sql",               "relational_db"),
    ("dynamodb",                "nosql_db"),
    ("cosmos db",               "nosql_db"),
    ("firestore",               "nosql_db"),
    ("bigtable",                "nosql_db"),
    ("mongodb",                 "nosql_db"),
    # Cache
    ("elasticache",             "cache"),
    ("memorystore",             "cache"),
    ("azure cache for redis",   "cache"),
    ("redis",                   "cache"),
    ("memcached",               "cache"),
    # Messaging
    ("kinesis",                 "event_stream"),
    ("event hubs",              "event_stream"),
    ("cloud pub/sub",           "event_stream"),
    ("pub/sub",                 "event_stream"),
    ("dataflow",                "event_stream"),
    ("sqs",                     "message_queue"),
    ("sns",                     "message_queue"),
    ("service bus",             "message_queue"),
    ("event grid",              "message_queue"),
    ("cloud tasks",             "message_queue"),
    # Storage
    ("s3",                      "object_storage"),
    ("blob storage",            "object_storage"),
    ("cloud storage",           "object_storage"),
    ("gcs",                     "object_storage"),
    # CDN / edge
    ("cloudfront",              "cdn"),
    ("azure cdn",               "cdn"),
    ("front door",              "cdn"),
    ("cloud cdn",               "cdn"),
    # Networking
    ("alb",                     "load_balancer"),
    ("nlb",                     "load_balancer"),
    ("application load balancer", "load_balancer"),
    ("load balancer",           "load_balancer"),
    ("application gateway",     "load_balancer"),
    ("cloud load balancing",    "load_balancer"),
    ("api gateway",             "api_gateway"),
    ("api management",          "api_gateway"),
    ("cloud endpoints",         "api_gateway"),
    # Security
    ("waf",                     "waf"),
    ("cloud armor",             "waf"),
    ("guardduty",               "waf"),
    ("defender for cloud",      "waf"),
    ("kms",                     "key_management"),
    ("key vault",               "key_management"),
    ("cloud kms",               "key_management"),
    ("secrets manager",         "secret_management"),
    ("secret manager",          "secret_management"),
    ("parameter store",         "secret_management"),
    # Monitoring
    ("cloudwatch",              "monitoring"),
    ("azure monitor",           "monitoring"),
    ("application insights",    "monitoring"),
    ("cloud monitoring",        "monitoring"),
    ("cloud logging",           "monitoring"),
    ("log analytics",           "monitoring"),
    ("x-ray",                   "monitoring"),
    # ML
    ("sagemaker",               "ml_platform"),
    ("vertex ai",               "ml_platform"),
    ("azure machine learning",  "ml_platform"),
    ("azure openai",            "ml_platform"),
]


def classify(service_name: str) -> str | None:
    """Return the capability type for a service name, or None if unknown."""
    sl = service_name.lower()
    best: tuple[str, str] | None = None
    for keyword, cap in _KEYWORD_MAP:
        if keyword in sl:
            if best is None or len(keyword) > len(best[0]):
                best = (keyword, cap)
    return best[1] if best else None


def extract_capabilities(architecture: dict) -> dict[str, list[str]]:
    """Map each service in an architecture to its capability type.

    Returns {capability_type: [service_names]} for all services that can be classified.
    Services in messaging, monitoring, and security layers are included but flagged
    as non-critical-path by the caller.
    """
    result: dict[str, list[str]] = {}
    for layer_name, services in architecture.get("layers", {}).items():
        for svc in services:
            cap = classify(svc)
            if cap:
                result.setdefault(cap, []).append(svc)
    return result


# Per-cloud canonical service for each capability type.
# Used by candidates.py to resolve abstract swaps into named services.
CANONICAL: dict[str, dict[str, str]] = {
    "aws": {
        "container_compute":  "Amazon ECS Fargate",
        "serverless_compute": "AWS Lambda",
        "kubernetes":         "Amazon EKS",
        "vm_compute":         "EC2 Auto Scaling",
        "relational_db":      "Amazon Aurora",
        "nosql_db":           "Amazon DynamoDB",
        "cache":              "Amazon ElastiCache (Redis)",
        "message_queue":      "Amazon SQS",
        "event_stream":       "Amazon Kinesis Data Streams",
        "object_storage":     "Amazon S3",
        "cdn":                "Amazon CloudFront",
        "load_balancer":      "Application Load Balancer",
        "api_gateway":        "Amazon API Gateway",
        "waf":                "AWS WAF",
        "key_management":     "AWS KMS",
        "secret_management":  "AWS Secrets Manager",
        "monitoring":         "Amazon CloudWatch",
        "ml_platform":        "Amazon SageMaker",
    },
    "azure": {
        "container_compute":  "Azure Container Apps",
        "serverless_compute": "Azure Functions",
        "kubernetes":         "AKS",
        "vm_compute":         "Azure Virtual Machine Scale Sets",
        "relational_db":      "Azure Database for PostgreSQL",
        "nosql_db":           "Azure Cosmos DB",
        "cache":              "Azure Cache for Redis",
        "message_queue":      "Azure Service Bus",
        "event_stream":       "Azure Event Hubs",
        "object_storage":     "Azure Blob Storage",
        "cdn":                "Azure CDN",
        "load_balancer":      "Azure Load Balancer",
        "api_gateway":        "Azure API Management",
        "waf":                "Azure WAF",
        "key_management":     "Azure Key Vault",
        "secret_management":  "Azure Key Vault",
        "monitoring":         "Azure Monitor",
        "ml_platform":        "Azure Machine Learning",
    },
    "gcp": {
        "container_compute":  "Cloud Run",
        "serverless_compute": "Cloud Functions",
        "kubernetes":         "Google Kubernetes Engine (GKE)",
        "vm_compute":         "Compute Engine",
        "relational_db":      "Cloud SQL (PostgreSQL)",
        "nosql_db":           "Firestore",
        "cache":              "Memorystore for Redis",
        "message_queue":      "Cloud Pub/Sub",
        "event_stream":       "Cloud Pub/Sub",
        "object_storage":     "Cloud Storage",
        "cdn":                "Cloud CDN",
        "load_balancer":      "Cloud Load Balancing",
        "api_gateway":        "Cloud Endpoints",
        "waf":                "Cloud Armor",
        "key_management":     "Cloud KMS",
        "secret_management":  "Cloud Secret Manager",
        "monitoring":         "Cloud Monitoring",
        "ml_platform":        "Vertex AI",
    },
}


def resolve(capability: str, cloud: str) -> str | None:
    """Return the canonical service name for a capability on the given cloud."""
    return CANONICAL.get(cloud, {}).get(capability)
