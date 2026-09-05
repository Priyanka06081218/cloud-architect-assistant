# pipeline/cloud_providers/aws.py
#
# AWS pricing and service map — us-east-1, on-demand rates (2025).
# This is the canonical source; cost_calculator.py now imports from here.

from pipeline.cloud_providers.base import CloudProvider


class AWSProvider(CloudProvider):
    name              = "AWS"
    provider_id       = "aws"
    networking_anchor = "VPC"
    optimization_tip  = (
        "Switch to 1-year Reserved Instances for EC2/RDS/ElastiCache "
        "to save 30-40% on compute costs. Use S3 Intelligent-Tiering "
        "for infrequently accessed data."
    )
    terraform_provider = 'provider "aws" { region = var.aws_region }'

    pricing = {
        # Compute
        "ec2_t3_micro":    {"monthly": 7.59,    "unit": "instance", "scalable": True},
        "ec2_t3_small":    {"monthly": 15.18,   "unit": "instance", "scalable": True},
        "ec2_t3_medium":   {"monthly": 30.37,   "unit": "instance", "scalable": True},
        "ec2_t3_large":    {"monthly": 60.74,   "unit": "instance", "scalable": True},
        "ec2_m5_large":    {"monthly": 70.08,   "unit": "instance", "scalable": True},
        "ec2_m5_xlarge":   {"monthly": 140.16,  "unit": "instance", "scalable": True},
        "ec2_p3_xlarge":   {"monthly": 918.00,  "unit": "instance (GPU)", "scalable": True},
        "ec2_g4dn_xlarge": {"monthly": 394.00,  "unit": "instance (GPU)", "scalable": True},
        # Containers
        "ecs_fargate":     {"monthly": 35.42,   "unit": "task", "scalable": True},
        "lambda":          {"monthly": 0.20,    "unit": "per 1M requests", "scalable": False},
        "eks_cluster":     {"monthly": 73.00,   "unit": "cluster", "scalable": False},
        # Load balancers
        "alb":             {"monthly": 22.27,   "unit": "per ALB", "scalable": False},
        "nlb":             {"monthly": 16.43,   "unit": "per NLB", "scalable": False},
        "api_gateway":     {"monthly": 3.50,    "unit": "per 1M requests", "scalable": False},
        # CDN / DNS
        "cloudfront":      {"monthly": 10.00,   "unit": "per 1TB transfer", "scalable": False},
        "route53":         {"monthly": 8.00,    "unit": "estimated", "scalable": False, "global": True},
        # Databases
        "rds_t3_medium":   {"monthly": 57.60,   "unit": "instance (single-AZ)", "scalable": True},
        "rds_t3_large":    {"monthly": 115.20,  "unit": "instance (single-AZ)", "scalable": True},
        "aurora_serverless":{"monthly": 115.00, "unit": "estimated (2-8 ACUs)", "scalable": False},
        "dynamodb":        {"monthly": 25.00,   "unit": "estimated (moderate traffic)", "scalable": False},
        "redshift":        {"monthly": 180.00,  "unit": "dc2.large node", "scalable": True},
        # Caching
        "elasticache_t3_medium": {"monthly": 49.28,  "unit": "node", "scalable": True},
        "elasticache_r6g_large": {"monthly": 122.64, "unit": "node", "scalable": True},
        # Messaging
        "sqs":             {"monthly": 0.40,    "unit": "per 1M messages", "scalable": False},
        "sns":             {"monthly": 0.50,    "unit": "per 1M notifications", "scalable": False},
        "kinesis":         {"monthly": 15.00,   "unit": "per shard", "scalable": True},
        "msk":             {"monthly": 180.00,  "unit": "estimated (small cluster)", "scalable": True},
        # Storage
        "s3":              {"monthly": 23.00,   "unit": "per 1TB stored", "scalable": False},
        "ebs_gp3":         {"monthly": 8.00,    "unit": "per 100GB", "scalable": False},
        # Networking
        "nat_gateway":     {"monthly": 32.40,   "unit": "per gateway", "scalable": False},
        "data_transfer":   {"monthly": 9.00,    "unit": "per 100GB egress", "scalable": False},
        "vpc":             {"monthly": 0.00,    "unit": "free", "scalable": False},
        # Security
        "kms":             {"monthly": 15.00,   "unit": "estimated (keys + API calls)", "scalable": False},
        "cloudtrail":      {"monthly": 20.00,   "unit": "estimated (management events)", "scalable": False},
        "waf":             {"monthly": 25.00,   "unit": "estimated (web ACL + rules)", "scalable": False},
        "guardduty":       {"monthly": 75.00,   "unit": "estimated", "scalable": False},
        "shield_advanced": {"monthly": 3000.00, "unit": "fixed (global)", "scalable": False, "global": True},
        "security_hub":    {"monthly": 10.00,   "unit": "estimated", "scalable": False},
        "config":          {"monthly": 8.00,    "unit": "estimated", "scalable": False},
        "secrets_manager": {"monthly": 5.00,    "unit": "estimated", "scalable": False},
        "iam":             {"monthly": 0.00,    "unit": "free", "scalable": False},
        # Monitoring
        "cloudwatch":      {"monthly": 10.00,   "unit": "estimated", "scalable": False},
        "x_ray":           {"monthly": 5.00,    "unit": "estimated", "scalable": False},
        # ML
        "sagemaker":          {"monthly": 150.00, "unit": "estimated (inference endpoint)", "scalable": True},
        "sagemaker_training": {"monthly": 80.00,  "unit": "estimated (periodic GPU job)", "scalable": False},
    }

    service_name_map = {
        # CDN
        "cloudfront":                    "cloudfront",
        "amazon cloudfront":             "cloudfront",
        # Load balancers
        "alb":                           "alb",
        "application load balancer":     "alb",
        "aws application load balancer": "alb",
        "nlb":                           "nlb",
        "network load balancer":         "nlb",
        # API
        "api gateway":                   "api_gateway",
        "aws api gateway":               "api_gateway",
        "amazon api gateway":            "api_gateway",
        # Compute
        "lambda":                        "lambda",
        "aws lambda":                    "lambda",
        "ecs":                           "ecs_fargate",
        "ecs fargate":                   "ecs_fargate",
        "amazon ecs fargate":            "ecs_fargate",
        "fargate":                       "ecs_fargate",
        "eks":                           "eks_cluster",
        "amazon eks":                    "eks_cluster",
        "ec2":                           "ec2_m5_large",
        "ec2 instances":                 "ec2_m5_large",
        "ec2 auto scaling":              "ec2_m5_large",
        "auto scaling group":            "ec2_m5_large",
        # DNS
        "route 53":                      "route53",
        "route53":                       "route53",
        "amazon route 53":               "route53",
        # Databases
        "rds":                           "rds_t3_large",
        "rds postgresql":                "rds_t3_large",
        "rds mysql":                     "rds_t3_large",
        "amazon rds":                    "rds_t3_large",
        "amazon rds postgresql":         "rds_t3_large",
        "aurora":                        "aurora_serverless",
        "aurora serverless":             "aurora_serverless",
        "aurora postgresql":             "aurora_serverless",
        "aurora global database":        "aurora_serverless",
        "amazon aurora":                 "aurora_serverless",
        "dynamodb":                      "dynamodb",
        "amazon dynamodb":               "dynamodb",
        "dynamodb global tables":        "dynamodb",
        "redshift":                      "redshift",
        "amazon redshift":               "redshift",
        # Caching
        "elasticache":                   "elasticache_t3_medium",
        "elasticache redis":             "elasticache_t3_medium",
        "amazon elasticache":            "elasticache_t3_medium",
        "redis":                         "elasticache_t3_medium",
        "memcached":                     "elasticache_t3_medium",
        # Messaging
        "sqs":                           "sqs",
        "amazon sqs":                    "sqs",
        "sns":                           "sns",
        "amazon sns":                    "sns",
        "kinesis":                       "kinesis",
        "kinesis data streams":          "kinesis",
        "kinesis firehose":              "kinesis",
        "amazon kinesis":                "kinesis",
        "msk":                           "msk",
        "kafka":                         "msk",
        "amazon msk":                    "msk",
        # Storage
        "s3":                            "s3",
        "amazon s3":                     "s3",
        "ebs":                           "ebs_gp3",
        "amazon ebs":                    "ebs_gp3",
        # Networking
        "nat gateway":                   "nat_gateway",
        "aws nat gateway":               "nat_gateway",
        "vpc":                           "vpc",
        "vpc with private subnets":      "vpc",
        "vpc subnets":                   "vpc",
        # Security
        "kms":                           "kms",
        "aws kms":                       "kms",
        "cloudtrail":                    "cloudtrail",
        "aws cloudtrail":                "cloudtrail",
        "waf":                           "waf",
        "aws waf":                       "waf",
        "guardduty":                     "guardduty",
        "amazon guardduty":              "guardduty",
        "security hub":                  "security_hub",
        "aws security hub":              "security_hub",
        "config":                        "config",
        "aws config":                    "config",
        "secrets manager":               "secrets_manager",
        "aws secrets manager":           "secrets_manager",
        "iam":                           "iam",
        "iam roles":                     "iam",
        # Monitoring
        "cloudwatch":                    "cloudwatch",
        "amazon cloudwatch":             "cloudwatch",
        "x-ray":                         "x_ray",
        "aws x-ray":                     "x_ray",
        "xray":                          "x_ray",
        # ML
        "sagemaker":                     "sagemaker",
        "aws sagemaker":                 "sagemaker",
        "sagemaker inference":           "sagemaker",
        "sagemaker training":            "sagemaker_training",
        "sagemaker training jobs":       "sagemaker_training",
        "aws batch":                     "ecs_fargate",
    }

    compliance_controls = {
        "hipaa": [
            {"keyword": "kms",        "label": "AWS KMS",                 "reason": "HIPAA requires encryption of PHI at rest using managed keys."},
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",          "reason": "HIPAA requires audit logging of all access to PHI."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty",        "reason": "HIPAA expects continuous threat detection for environments storing health data."},
            {"keyword": "vpc",        "label": "VPC with private subnets","reason": "HIPAA requires PHI to be isolated in a private network."},
        ],
        "soc2": [
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",   "reason": "SOC 2 CC7.2 requires logging of all privileged and user activity."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty", "reason": "SOC 2 CC6.8 requires continuous monitoring for unauthorized access attempts."},
            {"keyword": "waf",        "label": "AWS WAF",          "reason": "SOC 2 CC6.6 requires protection against common web exploits."},
        ],
        "pci-dss": [
            {"keyword": "waf",        "label": "AWS WAF",                 "reason": "PCI-DSS Req 6.6 mandates a WAF in front of all web-facing applications."},
            {"keyword": "kms",        "label": "AWS KMS",                 "reason": "PCI-DSS Req 3.4 requires strong encryption for cardholder data at rest."},
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",          "reason": "PCI-DSS Req 10 mandates audit trails for all access to cardholder data."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty",        "reason": "PCI-DSS Req 11.4 requires intrusion detection systems."},
            {"keyword": "vpc",        "label": "VPC with private subnets","reason": "PCI-DSS Req 1 mandates network segmentation for cardholder data."},
        ],
        "gdpr": [
            {"keyword": "kms",        "label": "AWS KMS",        "reason": "GDPR Art. 32 requires encryption of personal data at rest and in transit."},
            {"keyword": "cloudtrail", "label": "AWS CloudTrail", "reason": "GDPR Art. 30 requires records of all processing activities."},
        ],
        "fedramp": [
            {"keyword": "cloudtrail", "label": "AWS CloudTrail",   "reason": "FedRAMP AU-2 requires comprehensive audit event logging."},
            {"keyword": "guardduty",  "label": "Amazon GuardDuty", "reason": "FedRAMP SI-3/SI-4 requires malware and intrusion detection."},
            {"keyword": "kms",        "label": "AWS KMS",          "reason": "FedRAMP SC-28 requires FIPS 140-2 validated encryption at rest."},
            {"keyword": "config",     "label": "AWS Config",       "reason": "FedRAMP CM-6/CM-7 requires continuous configuration compliance monitoring."},
        ],
    }

    ha_database_keywords = ["aurora", "rds multi", "dynamodb", "elasticache"]
    ha_compute_keywords  = ["ecs", "eks", "fargate", "auto scaling", "lambda"]
    ha_lb_keywords       = ["load balancer", "alb", "nlb"]
    ha_missing_labels    = {
        "db":      "a Multi-AZ database (Aurora, DynamoDB, or ElastiCache)",
        "compute": "managed compute with auto-scaling (ECS Fargate, EKS, or Lambda)",
        "lb":      "a load balancer (ALB or NLB) to distribute traffic across AZs",
    }
    ha_suggestion = (
        "To reach 99.99%+ availability: use Aurora with Multi-AZ replicas or "
        "DynamoDB (globally distributed by default), place ECS tasks across at "
        "least 3 AZs behind an ALB with health checks, and enable auto-scaling "
        "policies to replace unhealthy instances automatically."
    )

    cache_keywords   = ["elasticache", "redis", "memcached", "dax"]
    cdn_keywords     = ["cloudfront", "cdn"]
    fast_db_keywords = ["dynamodb", "dax"]
    latency_suggestion = (
        "Add: ElastiCache (Redis) for in-memory caching, "
        "DynamoDB for single-digit millisecond reads at any scale, "
        "CloudFront to serve static content from edge locations. "
        "ElastiCache is the highest-impact single addition — it eliminates "
        "database round-trips for hot data."
    )

    multi_region_keywords = [
        "route 53", "global accelerator", "cloudfront",
        "aurora global", "dynamodb global", "s3 replication",
    ]
    multi_region_suggestion = (
        "Add Route 53 with latency-based or geolocation routing to direct users "
        "to the nearest region. For the database layer, use Aurora Global Database "
        "(sub-1s cross-region replication) or DynamoDB Global Tables (active-active "
        "across multiple regions). AWS Global Accelerator reduces latency by routing "
        "traffic over AWS's private backbone rather than the public internet."
    )

    budget_suggestion = (
        "Consider replacing provisioned compute (ECS, EC2) with serverless "
        "(Lambda, Fargate Spot), switching RDS to Aurora Serverless v2 "
        "(scales to zero when idle), or removing ElastiCache if caching can "
        "be handled in-process. Also verify that the stated scale is not higher than necessary."
    )
