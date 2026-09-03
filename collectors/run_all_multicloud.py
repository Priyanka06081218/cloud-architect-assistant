#!/usr/bin/env python3
# collectors/run_all_multicloud.py
#
# Master script: runs all Azure + GCP data collectors in sequence,
# then ingests everything into cloud-specific ChromaDB collections.
#
# Usage:
#   python collectors/run_all_multicloud.py            # both Azure and GCP
#   python collectors/run_all_multicloud.py azure      # Azure only
#   python collectors/run_all_multicloud.py gcp        # GCP only
#   python collectors/run_all_multicloud.py ingest     # ingest only (skip collection)
#
# Prerequisites:
#   pip install requests beautifulsoup4 feedparser sentence-transformers chromadb
#   STACKOVERFLOW_KEY=xxx GITHUB_TOKEN=xxx in your .env

import sys
import os
import time

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def run_azure_collectors():
    section("AZURE — Docs")
    from collectors.collect_azure_docs import run as azure_docs
    azure_docs()

    section("AZURE — Stack Overflow")
    from collectors.collect_azure_stackoverflow import run as azure_so
    azure_so()

    section("AZURE — Blog")
    from collectors.collect_azure_blog import run as azure_blog
    azure_blog()

    section("AZURE — GitHub")
    from collectors.collect_azure_github import run as azure_gh
    azure_gh()


def run_gcp_collectors():
    section("GCP — Docs")
    from collectors.collect_gcp_docs import run as gcp_docs
    gcp_docs()

    section("GCP — Stack Overflow")
    from collectors.collect_gcp_stackoverflow import run as gcp_so
    gcp_so()

    section("GCP — Blog")
    from collectors.collect_gcp_blog import run as gcp_blog
    gcp_blog()

    section("GCP — GitHub")
    from collectors.collect_gcp_github import run as gcp_gh
    gcp_gh()


def run_ingest(clouds: list[str]):
    section(f"INGESTION — {', '.join(c.upper() for c in clouds)}")
    from processors.process_and_load_multicloud import run as ingest
    ingest(clouds)


def main():
    args   = sys.argv[1:]
    clouds = []

    if not args:
        clouds = ["azure", "gcp"]
    elif "ingest" in args:
        remaining = [a for a in args if a != "ingest"]
        clouds    = remaining if remaining else ["azure", "gcp"]
        run_ingest(clouds)
        return
    else:
        for a in args:
            if a.lower() in ("azure", "gcp"):
                clouds.append(a.lower())
        if not clouds:
            print("Usage: python run_all_multicloud.py [azure] [gcp] [ingest]")
            sys.exit(1)

    start = time.time()

    if "azure" in clouds:
        run_azure_collectors()

    if "gcp" in clouds:
        run_gcp_collectors()

    # Ingest into ChromaDB
    run_ingest(clouds)

    elapsed = time.time() - start
    print(f"\n\n✓ All done in {elapsed / 60:.1f} minutes.")
    print("\nNext steps:")
    print("  1. Verify ChromaDB collections in data/chromadb/")
    print("  2. The retriever now automatically queries the right collection")
    print("  3. Test with: python -m pipeline.retriever")


if __name__ == "__main__":
    main()
