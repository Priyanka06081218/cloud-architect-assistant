#!/usr/bin/env python3
"""
startup.py — run before uvicorn on Railway.

Checks whether the Azure/GCP ChromaDB collections exist and have enough
chunks. If not, builds them from the raw JSON files in data/raw/.
AWS collections are left untouched (assumed to already exist, or will
fall back to LLM training knowledge via the MIN_DOCS guard in retriever.py).
"""

import os
import sys

CHROMA_DIR = "data/chromadb"
MIN_CHUNKS = 10   # below this → treat collection as unpopulated

CLOUDS_TO_BUILD = ["azure", "gcp"]

COLLECTION_NAMES = {
    "azure": ["architecture_patterns_azure", "service_comparisons_azure"],
    "gcp":   ["architecture_patterns_gcp",   "service_comparisons_gcp"],
}


def collections_ready() -> bool:
    """Return True if all target collections already have enough chunks."""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        existing = {c.name: c.count() for c in client.list_collections()}
        for cloud in CLOUDS_TO_BUILD:
            for name in COLLECTION_NAMES[cloud]:
                if existing.get(name, 0) < MIN_CHUNKS:
                    print(f"[startup] Collection '{name}' has {existing.get(name, 0)} chunks — needs rebuild.")
                    return False
        return True
    except Exception as e:
        print(f"[startup] ChromaDB check failed ({e}) — will attempt build.")
        return False


def build_collections():
    """Run the multicloud processor to build Azure/GCP collections."""
    print("[startup] Building Azure/GCP ChromaDB collections from raw data…")
    # Add project root to path so process_and_load_multicloud can find config
    sys.path.insert(0, os.path.dirname(__file__))
    try:
        from processors.process_and_load_multicloud import run
        run(clouds=CLOUDS_TO_BUILD)
        print("[startup] ChromaDB build complete.")
    except Exception as e:
        # Non-fatal: retriever falls back gracefully via MIN_DOCS guard
        print(f"[startup] WARNING: ChromaDB build failed ({e}). "
              "Azure/GCP queries will use LLM training knowledge only.")


if __name__ == "__main__":
    if not collections_ready():
        build_collections()
    else:
        print("[startup] Azure/GCP collections already populated — skipping build.")
    print("[startup] Done. Starting uvicorn…")
