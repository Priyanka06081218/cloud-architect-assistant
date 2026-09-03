# pipeline/cloud_providers/gcp.py
#
# GCP pricing and service map — us-east1, on-demand rates (2025).
# Prices are approximate monthly estimates for architecture sizing purposes.

from pipeline.cloud_providers.base import CloudProvider


class GCPProvider(CloudProvider):
    name              = "GCP"
    provider_id       = "gcp"
    networking_anchor = "VPC Network"
    optimization_tip  = (
        "Use Committed Use Discounts (1-year) for Compute Engine to save 37%. "
        "Enable GKE Autopilot to pay only for pod resources, not idle nodes. "
        "Use BigQuery on-demand pricing for infrequent queries; flat-rate for steady workloads."
    )
    terraform_provider = (
        'provider "google" { project = var.project_id region = var.region }'
    )

    pricing = {
        # Compute Engine
        "gce_e2_medium":        {"monthly": 25.00,   "unit": "instance (e2-medium)", "scalable": True},
        "gce_n2_standard_2":    {"monthly": 70.08,   "unit": "instance (n2-standard-2)", "scalable": True},
        "gce_n2_standard_4":    {"monthly": 140.16,  "unit": "instance (n2-standard-4)", "scalable": True},
        "gce_a2_highgpu_1g":    {"monthly": 918.00,  "unit": "instance (A2 GPU)", "scalable": True},
        # Containers
        "cloud_functions":      {"monthly": 0.20,    "unit": "per 1M invocations", "scalable": False},
        "cloud_run":            {"monthly": 30.00,   "unit": "estimated service", "scalable": True},
        "gke":                  {"monthly": 73.00,   "unit": "cluster management", "scalable": False},
        # Load balancers
        "cloud_load_balancing": {"monthly": 18.00,   "unit": "per forwarding rule", "scalable": False},
        "cloud_endpoints":      {"monthly": 3.00,    "unit": "per 1M API calls", "scalable": False},
        # CDN / DNS
        "cloud_cdn":            {"monthly": 10.00,   "unit": "per 1TB transfer", "scalable": False},
        "cloud_dns":            {"monthly": 6.00,    "unit": "per zone", "scalable": False, "global": True},
        # Databases
        "cloud_sql_postgres":   {"monthly": 50.00,   "unit": "db-g1-small (estimated)", "scalable": True},
        "cloud_sql_mysql":      {"monthly": 50.00,   "unit": "db-g1-small (estimated)", "scalable": True},
        "cloud_spanner":        {"monthly": 115.00,  "unit": "1 processing unit", "scalable": False},
        "alloydb":              {"monthly": 115.00,  "unit": "estimated (2vCPU)", "scalable": False},
        "firestore":            {"monthly": 20.00,   "unit": "estimated (moderate ops)", "scalable": False},
        "bigtable":             {"monthly": 65.00,   "unit": "1-node SSD cluster", "scalable": True},
        "bigquery":             {"monthly": 180.00,  "unit": "estimated (flat-rate)", "scalable": True},
        # Caching
        "memorystore_redis":    {"monthly": 50.00,   "unit": "M1 Basic (1GB)", "scalable": True},
        # Messaging
        "cloud_tasks":          {"monthly": 0.40,    "unit": "per 1M operations", "scalable": False},
        "cloud_pubsub":         {"monthly": 0.50,    "unit": "per 1M messages", "scalable": False},
        "cloud_dataflow":       {"monthly": 15.00,   "unit": "estimated (streaming)", "scalable": True},
        # Storage
        "cloud_storage":        {"monthly": 20.00,   "unit": "per 1TB stored", "scalable": False},
        "persistent_disk":      {"monthly": 8.00,    "unit": "per 100GB (pd-balanced)", "scalable": False},
        # Networking
        "cloud_nat":            {"monthly": 33.00,   "unit": "per NAT gateway", "scalable": False},
        "data_transfer":        {"monthly": 9.00,    "unit": "per 100GB egress", "scalable": False},
        "vpc_network":          {"monthly": 0.00,    "unit": "free", "scalable": False},
        # Security
        "cloud_kms":            {"monthly": 12.00,   "unit": "estimated (keys + ops)", "scalable": False},
        "cloud_audit_logs":     {"monthly": 20.00,   "unit": "estimated", "scalable": False},
        "cloud_armor":          {"monthly": 20.00,   "unit": "per policy", "scalable": False},
        "security_command_center": {"monthly": 15.00, "unit": "estimated", "scalable": False},
        "cloud_iam":            {"monthly": 0.00,    "unit": "free", "scalable": False},
        "secret_manager":       {"monthly": 5.00,    "unit": "estimated", "scalable": False},
        # Monitoring
        "cloud_monitoring":     {"monthly": 10.00,   "unit": "estimated", "scalable": False},
        "cloud_trace":          {"monthly": 5.00,    "unit": "estimated", "scalable": False},
        "cloud_logging":        {"monthly": 10.00,   "unit": "estimated", "scalable": False},
        # ML
        "vertex_ai":            {"monthly": 150.00,  "unit": "estimated (inference endpoint)", "scalable": True},
        "vertex_ai_training":   {"monthly": 80.00,   "unit": "estimated (GPU job)", "scalable": False},
    }

    service_name_map = {
        # CDN / routing
        "cloud cdn":                     "cloud_cdn",
        "google cloud cdn":              "cloud_cdn",
        # Load balancers
        "cloud load balancing":          "cloud_load_balancing",
        "google cloud load balancing":   "cloud_load_balancing",
        "cloud endpoints":               "cloud_endpoints",
        "apigee":                        "cloud_endpoints",
        # Compute
        "cloud functions":               "cloud_functions",
        "google cloud functions":        "cloud_functions",
        "cloud run":                     "cloud_run",
        "google cloud run":              "cloud_run",
        "gke":                           "gke",
        "google kubernetes engine":      "gke",
        "compute engine":                "gce_n2_standard_2",
        "google compute engine":         "gce_n2_standard_2",
        "managed instance groups":       "gce_n2_standard_2",
        "instance groups":               "gce_n2_standard_2",
        # DNS
        "cloud dns":                     "cloud_dns",
        "google cloud dns":              "cloud_dns",
        # Databases
        "cloud sql":                     "cloud_sql_postgres",
        "cloud sql postgresql":          "cloud_sql_postgres",
        "cloud sql mysql":               "cloud_sql_mysql",
        "cloud spanner":                 "cloud_spanner",
        "google cloud spanner":          "cloud_spanner",
        "alloydb":                       "alloydb",
        "cloud firestore":               "firestore",
        "firestore":                     "firestore",
        "cloud bigtable":                "bigtable",
        "bigtable":                      "bigtable",
        "bigquery":                      "bigquery",
        "google bigquery":               "bigquery",
        # Caching
        "memorystore":                   "memorystore_redis",
        "memorystore for redis":         "memorystore_redis",
        "cloud memorystore":             "memorystore_redis",
        "redis":                         "memorystore_redis",
        # Messaging
        "cloud tasks":                   "cloud_tasks",
        "cloud pub/sub":                 "cloud_pubsub",
        "pub/sub":                       "cloud_pubsub",
        "pubsub":                        "cloud_pubsub",
        "cloud pubsub":                  "cloud_pubsub",
        "cloud dataflow":                "cloud_dataflow",
        "dataflow":                      "cloud_dataflow",
        # Storage
        "cloud storage":                 "cloud_storage",
        "google cloud storage":          "cloud_storage",
        "persistent disk":               "persistent_disk",
        # Networking
        "cloud nat":                     "cloud_nat",
        "google cloud nat":              "cloud_nat",
        "vpc network":                   "vpc_network",
        "vpc":                           "vpc_network",
        "google vpc":                    "vpc_network",
        # Security
        "cloud kms":                     "cloud_kms",
        "google cloud kms":              "cloud_kms",
        "cloud audit logs":              "cloud_audit_logs",
        "audit logs":                    "cloud_audit_logs",
        "cloud armor":                   "cloud_armor",
        "google cloud armor":            "cloud_armor",
        "security command center":       "security_command_center",
        "google security command center":"security_command_center",
        "cloud iam":                     "cloud_iam",
        "iam":                           "cloud_iam",
        "secret manager":                "secret_manager",
        "google secret manager":         "secret_manager",
        # Monitoring
        "cloud monitoring":              "cloud_monitoring",
        "google cloud monitoring":       "cloud_monitoring",
        "cloud trace":                   "cloud_trace",
        "cloud logging":                 "cloud_logging",
        # ML
        "vertex ai":                     "vertex_ai",
        "google vertex ai":              "vertex_ai",
        "vertex ai training":            "vertex_ai_training",
    }
