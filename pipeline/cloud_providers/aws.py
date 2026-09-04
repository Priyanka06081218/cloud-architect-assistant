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
