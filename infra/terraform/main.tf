# infra/terraform/main.tf
#
# AWS infrastructure for the Cloud Architecture Assistant.
#
# Resources created:
#   - VPC with public + private subnets across 2 AZs
#   - EKS cluster (2-4 t3.medium nodes, auto-scaling)
#   - ECR repositories for backend and frontend images
#   - ElastiCache Redis cluster (cache for API responses)
#   - Application Load Balancer (public ingress)
#   - IAM roles for EKS nodes and service accounts
#   - S3 bucket for ChromaDB backups
#
# Deploy:
#   cd infra/terraform
#   terraform init
#   terraform plan -var="cluster_name=cloud-architect"
#   terraform apply

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
  }

  # Remote state — replace bucket/key with your own
  backend "s3" {
    bucket  = "your-terraform-state-bucket"
    key     = "cloud-architect/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "cloud-architect-assistant"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# ── Variables ──────────────────────────────────────────────────────────────────

variable "aws_region"    { default = "us-east-1" }
variable "environment"   { default = "prod" }
variable "cluster_name"  { default = "cloud-architect" }
variable "node_min"      { default = 2 }
variable "node_max"      { default = 4 }
variable "node_type"     { default = "t3.medium" }

# ── VPC ───────────────────────────────────────────────────────────────────────

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${var.aws_region}a", "${var.aws_region}b"]
  public_subnets  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnets = ["10.0.10.0/24", "10.0.11.0/24"]

  enable_nat_gateway   = true
  single_nat_gateway   = true  # saves cost; use false for HA production
  enable_dns_hostnames = true
  enable_dns_support   = true

  # Required tags for EKS to discover subnets
  public_subnet_tags  = { "kubernetes.io/role/elb" = "1" }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }
}

# ── EKS Cluster ───────────────────────────────────────────────────────────────

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.31"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Allow kubectl from anywhere (restrict to your IP in production)
  cluster_endpoint_public_access = true

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_type]
      min_size       = var.node_min
      max_size       = var.node_max
      desired_size   = var.node_min

      # Use Spot instances for 60-70% cost savings on non-critical workloads
      # capacity_type = "SPOT"

      labels = {
        role = "app"
      }
    }
  }

  # Allow nodes to pull from ECR and access other AWS services
  enable_irsa = true
}

# ── ECR Repositories ──────────────────────────────────────────────────────────

resource "aws_ecr_repository" "backend" {
  name                 = "${var.cluster_name}/backend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "${var.cluster_name}/frontend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Lifecycle policy: keep only the last 10 images to save storage costs
resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name
  policy     = aws_ecr_lifecycle_policy.backend.policy
}

# ── ElastiCache Redis (API response cache) ────────────────────────────────────

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.cluster_name}-redis-subnets"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_security_group" "redis" {
  name   = "${var.cluster_name}-redis-sg"
  vpc_id = module.vpc.vpc_id

  ingress {
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [module.vpc.vpc_cidr_block]
    description = "Redis access from within VPC"
  }
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${var.cluster_name}-redis"
  description          = "Cache for API responses"

  node_type            = "cache.t3.micro"   # upgrade to t3.small in production
  num_cache_clusters   = 1                  # use 2 for Multi-AZ
  parameter_group_name = "default.redis7"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

# ── S3 bucket for ChromaDB backups ────────────────────────────────────────────

resource "aws_s3_bucket" "chroma_backup" {
  bucket = "${var.cluster_name}-chroma-backup-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "chroma_backup" {
  bucket = aws_s3_bucket.chroma_backup.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "chroma_backup" {
  bucket = aws_s3_bucket.chroma_backup.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ── IAM: EKS pod service account for S3/SSM access ───────────────────────────

resource "aws_iam_role" "backend_pod" {
  name = "${var.cluster_name}-backend-pod-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = module.eks.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${module.eks.oidc_provider}:sub" = "system:serviceaccount:default:backend"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "backend_pod" {
  name = "backend-pod-policy"
  role = aws_iam_role.backend_pod.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.chroma_backup.arn,
          "${aws_s3_bucket.chroma_backup.arn}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/${var.cluster_name}/*"
      },
    ]
  })
}

# ── SSM Parameters for secrets ────────────────────────────────────────────────
# Store the OpenAI key in SSM Parameter Store (not in k8s secrets or env vars)
# Create manually: aws ssm put-parameter --name /cloud-architect/openai-key --value "sk-..." --type SecureString

data "aws_ssm_parameter" "openai_key" {
  name = "/${var.cluster_name}/openai-key"
}

# ── Data sources ──────────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "ecr_backend_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "redis_endpoint" {
  value     = aws_elasticache_replication_group.redis.primary_endpoint_address
  sensitive = true
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}
