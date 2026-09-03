# config.py

import os
from dotenv import load_dotenv

load_dotenv()

STACKOVERFLOW_KEY = os.getenv("STACKOVERFLOW_KEY")
GITHUB_TOKEN      = os.getenv("GITHUB_TOKEN")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
FINETUNE_MODEL = os.getenv("FINETUNE_MODEL", "")
VLLM_BASE_URL  = os.getenv("VLLM_BASE_URL", "")

# Folder paths — AWS
RAW_AWS_DOCS      = "data/raw/aws_docs"
RAW_WHITEPAPERS   = "data/raw/whitepapers"
RAW_STACKOVERFLOW = "data/raw/stackoverflow"
RAW_GITHUB        = "data/raw/github"
RAW_BLOG          = "data/raw/blog"

# Folder paths — Azure
RAW_AZURE_DOCS          = "data/raw/azure_docs"
RAW_AZURE_STACKOVERFLOW = "data/raw/azure_stackoverflow"
RAW_AZURE_BLOG          = "data/raw/azure_blog"
RAW_AZURE_GITHUB        = "data/raw/azure_github"

# Folder paths — GCP
RAW_GCP_DOCS          = "data/raw/gcp_docs"
RAW_GCP_STACKOVERFLOW = "data/raw/gcp_stackoverflow"
RAW_GCP_BLOG          = "data/raw/gcp_blog"
RAW_GCP_GITHUB        = "data/raw/gcp_github"