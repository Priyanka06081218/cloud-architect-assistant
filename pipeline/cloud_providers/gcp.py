# pipeline/cloud_providers/gcp.py
#
# GCP pricing and service map — us-east1, on-demand rates (2025).
# Prices are approximate monthly estimates for architecture sizing purposes.

from pipeline.cloud_providers.base import CloudProvider


class GCPProvider(CloudProvider):
    name              = "GCP"
    provider_id       = "gcp"
    alias_prefixes    = ["google cloud ", "google ", "gcp "]
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

    compliance_controls = {
        "hipaa": [
            {"keyword": "kms",              "label": "Cloud KMS",               "reason": "HIPAA requires encryption of PHI at rest using customer-managed keys."},
            {"keyword": "audit log",        "label": "Cloud Audit Logs",        "reason": "HIPAA requires audit logging of all access to PHI."},
            {"keyword": "security command", "label": "Security Command Center", "reason": "HIPAA expects continuous threat detection for environments storing health data."},
            {"keyword": "vpc",              "label": "VPC Network",             "reason": "HIPAA requires PHI to be isolated in a private network."},
        ],
        "soc2": [
            {"keyword": "audit log",        "label": "Cloud Audit Logs",          "reason": "SOC 2 CC7.2 requires logging of all privileged and user activity."},
            {"keyword": "security command", "label": "Security Command Center",   "reason": "SOC 2 CC6.8 requires continuous monitoring for unauthorized access."},
            {"keyword": "cloud armor",      "label": "Cloud Armor",               "reason": "SOC 2 CC6.6 requires protection against common web exploits."},
        ],
        "pci-dss": [
            {"keyword": "cloud armor",      "label": "Cloud Armor",              "reason": "PCI-DSS Req 6.6 mandates a WAF in front of all web-facing applications."},
            {"keyword": "kms",              "label": "Cloud KMS",                "reason": "PCI-DSS Req 3.4 requires strong encryption for cardholder data at rest."},
            {"keyword": "audit log",        "label": "Cloud Audit Logs",         "reason": "PCI-DSS Req 10 mandates audit trails for all access to cardholder data."},
            {"keyword": "security command", "label": "Security Command Center",  "reason": "PCI-DSS Req 11.4 requires intrusion detection systems."},
            {"keyword": "vpc",              "label": "VPC Network",              "reason": "PCI-DSS Req 1 mandates network segmentation for cardholder data."},
        ],
        "gdpr": [
            {"keyword": "kms",       "label": "Cloud KMS",       "reason": "GDPR Art. 32 requires encryption of personal data at rest and in transit."},
            {"keyword": "audit log", "label": "Cloud Audit Logs","reason": "GDPR Art. 30 requires records of all processing activities."},
        ],
        "fedramp": [
            {"keyword": "audit log",        "label": "Cloud Audit Logs",          "reason": "FedRAMP AU-2 requires comprehensive audit event logging."},
            {"keyword": "security command", "label": "Security Command Center",   "reason": "FedRAMP SI-3/SI-4 requires malware and intrusion detection."},
            {"keyword": "kms",              "label": "Cloud KMS",                 "reason": "FedRAMP SC-28 requires FIPS 140-2 validated encryption at rest."},
            {"keyword": "asset inventory",  "label": "Cloud Asset Inventory",     "reason": "FedRAMP CM-6/CM-7 requires continuous configuration compliance."},
        ],
    }

    ha_database_keywords = ["cloud spanner", "spanner", "cloud sql", "bigtable", "firestore", "memorystore"]
    ha_compute_keywords  = ["gke", "cloud run", "cloud functions", "app engine"]
    ha_lb_keywords       = ["cloud load balancing", "cloud lb", "load balancing"]
    ha_missing_labels    = {
        "db":      "a multi-zone database (Cloud Spanner, Cloud SQL HA, or Cloud Bigtable)",
        "compute": "managed compute with zone spread (GKE regional cluster, or Cloud Run)",
        "lb":      "Cloud Load Balancing (global) for cross-zone traffic distribution",
    }
    ha_suggestion = (
        "To reach 99.99%+ availability: use Cloud Spanner (99.999% SLA for "
        "multi-region) or Cloud SQL with HA replica, run GKE Autopilot across "
        "zones with a regional cluster, and use Cloud Load Balancing (global) "
        "to route traffic to the nearest healthy instance."
    )

    cache_keywords   = ["memorystore", "redis"]
    cdn_keywords     = ["cloud cdn", "cdn"]
    fast_db_keywords = ["bigtable", "firestore", "spanner"]
    latency_suggestion = (
        "Add: Memorystore for Redis for in-memory caching (sub-millisecond reads), "
        "Cloud Bigtable for sub-10ms reads on time-series or wide-column data at scale, "
        "Cloud CDN to cache static content at Google's global edge."
    )

    multi_region_keywords = [
        "cloud load balancing", "cloud cdn", "cloud spanner",
        "spanner", "bigtable", "firestore",
    ]
    multi_region_suggestion = (
        "Add Cloud Load Balancing (global) to route users to the nearest region with "
        "Cloud CDN for edge caching. For the database layer, use Cloud Spanner "
        "(globally distributed, 99.999% multi-region SLA) or Firestore in multi-region "
        "mode. Both Cloud Bigtable and BigQuery natively replicate across regions."
    )

    budget_suggestion = (
        "Consider replacing GKE with Cloud Run (scale-to-zero, pay-per-request), "
        "switching Cloud SQL to a smaller tier or Cloud Spanner only if truly needed "
        "(Cloud SQL is significantly cheaper), or removing Memorystore if in-process "
        "caching is sufficient. Verify Compute Engine instances use Spot/preemptible pricing."
    )
