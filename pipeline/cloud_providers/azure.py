# pipeline/cloud_providers/azure.py
#
# Azure pricing and service map — East US region, Pay-As-You-Go (2025).
# Prices are approximate monthly estimates for architecture sizing purposes.

from pipeline.cloud_providers.base import CloudProvider


class AzureProvider(CloudProvider):
    name              = "Azure"
    provider_id       = "azure"
    networking_anchor = "Azure Virtual Network"
    optimization_tip  = (
        "Use Azure Reserved VM Instances (1-year) to save 30-40% on compute. "
        "Enable Azure Cost Management budgets and alerts. "
        "Use Azure Blob Storage lifecycle policies to tier cold data automatically."
    )
    terraform_provider = (
        'provider "azurerm" { features {} subscription_id = var.subscription_id }'
    )

    pricing = {
        # Compute
        "vm_b2s":               {"monthly": 30.37,   "unit": "instance (B2s)", "scalable": True},
        "vm_d2s_v3":            {"monthly": 70.08,   "unit": "instance (D2s_v3)", "scalable": True},
        "vm_d4s_v3":            {"monthly": 140.16,  "unit": "instance (D4s_v3)", "scalable": True},
        "vm_nc6s_v3":           {"monthly": 918.00,  "unit": "instance (NC6s_v3 GPU)", "scalable": True},
        # Containers
        "azure_functions":      {"monthly": 0.20,    "unit": "per 1M executions", "scalable": False},
        "aca":                  {"monthly": 35.00,   "unit": "container app (estimated)", "scalable": True},
        "aks":                  {"monthly": 73.00,   "unit": "cluster management", "scalable": False},
        # Load balancers / gateways
        "app_gateway":          {"monthly": 25.00,   "unit": "per gateway", "scalable": False},
        "azure_lb":             {"monthly": 18.00,   "unit": "per load balancer", "scalable": False},
        "apim":                 {"monthly": 50.00,   "unit": "Developer tier", "scalable": False},
        # CDN / DNS
        "azure_front_door":     {"monthly": 35.00,   "unit": "estimated", "scalable": False},
        "azure_cdn":            {"monthly": 10.00,   "unit": "per 1TB transfer", "scalable": False},
        "azure_dns":            {"monthly": 6.00,    "unit": "per zone", "scalable": False, "global": True},
        # Databases
        "azure_postgres":       {"monthly": 60.00,   "unit": "Flexible Server (2vCPU)", "scalable": True},
        "azure_mysql":          {"monthly": 57.60,   "unit": "Flexible Server (2vCPU)", "scalable": True},
        "cosmos_db":            {"monthly": 25.00,   "unit": "estimated (moderate RU/s)", "scalable": False},
        "azure_synapse":        {"monthly": 180.00,  "unit": "DW100c node", "scalable": True},
        # Caching
        "azure_redis":          {"monthly": 50.00,   "unit": "C1 Standard cache", "scalable": True},
        # Messaging
        "service_bus":          {"monthly": 0.40,    "unit": "per 1M operations", "scalable": False},
        "event_grid":           {"monthly": 0.50,    "unit": "per 1M operations", "scalable": False},
        "event_hubs":           {"monthly": 15.00,   "unit": "per throughput unit", "scalable": True},
        # Storage
        "blob_storage":         {"monthly": 20.00,   "unit": "per 1TB stored", "scalable": False},
        "managed_disk":         {"monthly": 8.00,    "unit": "per 100GB (P10 SSD)", "scalable": False},
        # Networking
        "azure_nat_gateway":    {"monthly": 33.00,   "unit": "per gateway", "scalable": False},
        "data_transfer":        {"monthly": 9.00,    "unit": "per 100GB egress", "scalable": False},
        "vnet":                 {"monthly": 0.00,    "unit": "free", "scalable": False},
        # Security
        "key_vault":            {"monthly": 10.00,   "unit": "estimated (keys + ops)", "scalable": False},
        "azure_monitor_logs":   {"monthly": 20.00,   "unit": "estimated (5GB/day)", "scalable": False},
        "azure_waf":            {"monthly": 20.00,   "unit": "per policy", "scalable": False},
        "defender_for_cloud":   {"monthly": 15.00,   "unit": "estimated", "scalable": False},
        "azure_firewall":       {"monthly": 75.00,   "unit": "per deployment", "scalable": False},
        "entra_id":             {"monthly": 0.00,    "unit": "free (P1 = $6/user)", "scalable": False},
        # Monitoring
        "azure_monitor":        {"monthly": 10.00,   "unit": "estimated", "scalable": False},
        "app_insights":         {"monthly": 5.00,    "unit": "estimated", "scalable": False},
        # ML
        "azure_ml":             {"monthly": 150.00,  "unit": "estimated (compute cluster)", "scalable": True},
        "azure_ml_training":    {"monthly": 80.00,   "unit": "estimated (GPU job)", "scalable": False},
        # AI / OpenAI
        "azure_openai":         {"monthly": 1200.00, "unit": "estimated (GPT-4, moderate usage)", "scalable": False},
        "azure_openai_gpt4":    {"monthly": 2000.00, "unit": "estimated (GPT-4, 10k queries/day)", "scalable": False},
        # Media
        "azure_media_services": {"monthly": 400.00,  "unit": "estimated (encoding + streaming units)", "scalable": True},
    }

    service_name_map = {
        # CDN / routing
        "azure front door":              "azure_front_door",
        "front door":                    "azure_front_door",
        "azure cdn":                     "azure_cdn",
        "cdn":                           "azure_cdn",
        # Load balancers
        "azure application gateway":     "app_gateway",
        "application gateway":           "app_gateway",
        "azure load balancer":           "azure_lb",
        "load balancer":                 "azure_lb",
        # API
        "azure api management":          "apim",
        "api management":                "apim",
        "apim":                          "apim",
        # Compute
        "azure functions":               "azure_functions",
        "functions":                     "azure_functions",
        "azure container apps":          "aca",
        "container apps":                "aca",
        "aca":                           "aca",
        "aks":                           "aks",
        "azure kubernetes service":      "aks",
        "azure virtual machines":        "vm_d2s_v3",
        "virtual machines":              "vm_d2s_v3",
        "vm":                            "vm_d2s_v3",
        "vmss":                          "vm_d2s_v3",
        "virtual machine scale sets":    "vm_d2s_v3",
        # DNS
        "azure dns":                     "azure_dns",
        "azure traffic manager":         "azure_dns",
        "traffic manager":               "azure_dns",
        # Databases
        "azure database for postgresql": "azure_postgres",
        "azure postgres":                "azure_postgres",
        "postgresql":                    "azure_postgres",
        "azure database for mysql":      "azure_mysql",
        "azure mysql":                   "azure_mysql",
        "cosmos db":                     "cosmos_db",
        "azure cosmos db":               "cosmos_db",
        "cosmosdb":                      "cosmos_db",
        "azure synapse analytics":       "azure_synapse",
        "synapse analytics":             "azure_synapse",
        "synapse":                       "azure_synapse",
        # Caching
        "azure cache for redis":         "azure_redis",
        "azure redis":                   "azure_redis",
        "redis":                         "azure_redis",
        # Messaging
        "azure service bus":             "service_bus",
        "service bus":                   "service_bus",
        "azure event grid":              "event_grid",
        "event grid":                    "event_grid",
        "azure event hubs":              "event_hubs",
        "event hubs":                    "event_hubs",
        # Storage
        "azure blob storage":            "blob_storage",
        "azure blob":                    "blob_storage",
        "blob storage":                  "blob_storage",
        "azure storage":                 "blob_storage",
        "storage account":               "blob_storage",
        "azure managed disks":           "managed_disk",
        "managed disks":                 "managed_disk",
        # Networking
        "azure nat gateway":             "azure_nat_gateway",
        "nat gateway":                   "azure_nat_gateway",
        "azure virtual network":         "vnet",
        "virtual network":               "vnet",
        "vnet":                          "vnet",
        # Security
        "azure key vault":               "key_vault",
        "key vault":                     "key_vault",
        "azure monitor logs":            "azure_monitor_logs",
        "log analytics":                 "azure_monitor_logs",
        "azure waf":                     "azure_waf",
        "waf":                           "azure_waf",
        "microsoft defender for cloud":  "defender_for_cloud",
        "defender for cloud":            "defender_for_cloud",
        "azure firewall":                "azure_firewall",
        "microsoft entra id":            "entra_id",
        "entra id":                      "entra_id",
        "azure active directory":        "entra_id",
        # Monitoring
        "azure monitor":                 "azure_monitor",
        "azure application insights":    "app_insights",
        "application insights":          "app_insights",
        # ML / AI
        "azure machine learning":        "azure_ml",
        "azure ml":                      "azure_ml",
        "azure openai service":          "azure_openai_gpt4",
        "azure openai":                  "azure_openai_gpt4",
        "openai service":                "azure_openai_gpt4",
        "azure cognitive services":      "azure_openai",
        "cognitive services":            "azure_openai",
        # Media
        "azure media services":          "azure_media_services",
        "media services":                "azure_media_services",
    }

    compliance_controls = {
        "hipaa": [
            {"keyword": "key vault",       "label": "Azure Key Vault",              "reason": "HIPAA requires encryption of PHI at rest using managed keys."},
            {"keyword": "monitor",         "label": "Azure Monitor (Activity Logs)","reason": "HIPAA requires audit logging of all access to PHI."},
            {"keyword": "defender",        "label": "Microsoft Defender for Cloud", "reason": "HIPAA expects continuous threat detection for environments storing health data."},
            {"keyword": "virtual network", "label": "Azure Virtual Network",        "reason": "HIPAA requires PHI to be isolated in a private network."},
        ],
        "soc2": [
            {"keyword": "monitor",  "label": "Azure Monitor",                 "reason": "SOC 2 CC7.2 requires logging of all privileged and user activity."},
            {"keyword": "defender", "label": "Microsoft Defender for Cloud",  "reason": "SOC 2 CC6.8 requires continuous monitoring for unauthorized access."},
            {"keyword": "waf",      "label": "Azure WAF",                     "reason": "SOC 2 CC6.6 requires protection against common web exploits."},
        ],
        "pci-dss": [
            {"keyword": "waf",            "label": "Azure WAF",                   "reason": "PCI-DSS Req 6.6 mandates a WAF in front of all web-facing applications."},
            {"keyword": "key vault",      "label": "Azure Key Vault",             "reason": "PCI-DSS Req 3.4 requires strong encryption for cardholder data at rest."},
            {"keyword": "monitor",        "label": "Azure Monitor",               "reason": "PCI-DSS Req 10 mandates audit trails for all access to cardholder data."},
            {"keyword": "defender",       "label": "Microsoft Defender for Cloud","reason": "PCI-DSS Req 11.4 requires intrusion detection systems."},
            {"keyword": "virtual network","label": "Azure Virtual Network",       "reason": "PCI-DSS Req 1 mandates network segmentation for cardholder data."},
        ],
        "gdpr": [
            {"keyword": "key vault", "label": "Azure Key Vault", "reason": "GDPR Art. 32 requires encryption of personal data at rest and in transit."},
            {"keyword": "monitor",   "label": "Azure Monitor",   "reason": "GDPR Art. 30 requires records of all processing activities."},
        ],
        "fedramp": [
            {"keyword": "monitor",   "label": "Azure Monitor",                 "reason": "FedRAMP AU-2 requires comprehensive audit event logging."},
            {"keyword": "defender",  "label": "Microsoft Defender for Cloud",  "reason": "FedRAMP SI-3/SI-4 requires malware and intrusion detection."},
            {"keyword": "key vault", "label": "Azure Key Vault",               "reason": "FedRAMP SC-28 requires FIPS 140-2 validated encryption at rest."},
            {"keyword": "policy",    "label": "Azure Policy",                  "reason": "FedRAMP CM-6/CM-7 requires continuous configuration compliance."},
        ],
    }

    ha_database_keywords = ["cosmos db", "cosmosdb", "azure sql", "azure database", "azure cache for redis", "redis"]
    ha_compute_keywords  = ["aks", "container apps", "app service", "azure functions", "vmss"]
    ha_lb_keywords       = ["load balancer", "application gateway", "front door"]
    ha_missing_labels    = {
        "db":      "a zone-redundant database (Azure Cosmos DB or Azure Database for PostgreSQL HA)",
        "compute": "managed container compute across zones (AKS, Container Apps, or App Service)",
        "lb":      "an Azure Application Gateway or Load Balancer for zone-redundant traffic distribution",
    }
    ha_suggestion = (
        "To reach 99.99%+ availability: use Azure Cosmos DB (99.999% SLA) or "
        "Azure Database for PostgreSQL with zone-redundant HA, run AKS or "
        "Container Apps across availability zones, and place an Azure Application "
        "Gateway or Load Balancer in front to distribute traffic."
    )

    cache_keywords   = ["redis", "azure cache", "azure cache for redis"]
    cdn_keywords     = ["azure cdn", "front door", "cdn"]
    fast_db_keywords = ["cosmos db", "cosmosdb"]
    latency_suggestion = (
        "Add: Azure Cache for Redis for in-memory caching (sub-millisecond reads), "
        "Azure Cosmos DB for single-digit millisecond NoSQL reads at global scale, "
        "Azure CDN or Azure Front Door to serve static content from 100+ edge PoPs."
    )

    multi_region_keywords = [
        "front door", "traffic manager", "cosmos db", "cosmosdb",
        "geo-replication", "azure front door",
    ]
    multi_region_suggestion = (
        "Add Azure Front Door for global HTTP load balancing with intelligent routing "
        "and automatic failover. For the database layer, use Azure Cosmos DB with "
        "multi-region writes (active-active, 99.999% SLA) or Azure Database for "
        "PostgreSQL with read replicas in each target region. "
        "Azure Traffic Manager can also provide DNS-level failover between regions."
    )

    budget_suggestion = (
        "Consider replacing AKS or VMs with Azure Container Apps or Azure Functions "
        "(consumption plan), switching Azure Database for PostgreSQL to the Flexible "
        "Server Burstable tier for dev/staging, or removing Azure Cache for Redis "
        "if in-process caching is sufficient. Verify the stated scale is not over-provisioned."
    )
