# pipeline/cache.py
#
# Semantic cache using Upstash Vector.
#
# How it works:
#   1. Encode the user query with all-MiniLM-L6-v2 (same model as RAG retrieval)
#   2. Query Upstash Vector for the nearest cached query embedding
#   3. If cosine similarity >= THRESHOLD (0.92): cache HIT → return stored result
#   4. Otherwise: cache MISS → caller runs the pipeline, then we store the result
#
# Why 0.92?  Queries that differ by <8% cosine distance almost always produce
# identical architecture recommendations. In testing: "serverless API 10k users"
# and "serverless REST API 10k daily users" are ~0.95 similar — same answer.

import json
import logging
import os
import time
import uuid
import gzip
import base64
from typing import Optional

log = logging.getLogger(__name__)

THRESHOLD = 0.92          # minimum cosine similarity for a cache hit
CACHE_ENABLED = bool(os.getenv("UPSTASH_VECTOR_URL"))

# Cloud provider keywords used to namespace the cache key.
# Without this, "HIPAA pipeline on GCP" and "HIPAA pipeline on AWS" embed
# to ~0.95 similarity and collide — returning the wrong cloud's cached result.
_CLOUD_KEYWORDS = {
    "gcp":   ["gcp", "google cloud", "google cloud platform", "cloud run",
              "bigquery", "gke", "pub/sub", "vertex ai", "cloud spanner",
              "firestore", "cloud functions"],
    "azure": ["azure", "microsoft azure", "azure functions", "cosmos db",
              "aks", "azure kubernetes", "service bus", "event hub",
              "azure sql", "azure openai"],
}


def _quick_cloud(query: str) -> str:
    """Fast keyword scan to detect cloud provider — no LLM needed.

    Returns "aws" | "azure" | "gcp".  Used only for cache namespacing so
    queries for different clouds never collide even if semantically similar.
    """
    q = query.lower()
    for cloud, keywords in _CLOUD_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return cloud
    return "aws"


def _cache_query(query: str, cloud_provider: str | None = None) -> str:
    """Prepend the cloud provider so embeddings are namespaced per cloud.

    Uses the explicit cloud_provider when given; falls back to keyword detection.
    """
    cloud = (cloud_provider or "").lower().strip() or _quick_cloud(query)
    return f"[{cloud}] {query}"

_index = None
_embed_model = None


def _get_index():
    global _index
    if _index is None:
        from upstash_vector import Index
        _index = Index(
            url=os.getenv("UPSTASH_VECTOR_URL", ""),
            token=os.getenv("UPSTASH_VECTOR_TOKEN", ""),
        )
    return _index


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _embed(query: str) -> list[float]:
    model = _get_embed_model()
    return model.encode([query]).tolist()[0]


def _compress(data: dict) -> str:
    """Gzip + base64 encode a dict so it fits in Upstash metadata (48KB limit)."""
    raw = json.dumps(data).encode("utf-8")
    compressed = gzip.compress(raw)
    return base64.b64encode(compressed).decode("utf-8")


def _decompress(s: str) -> dict:
    raw = base64.b64decode(s.encode("utf-8"))
    return json.loads(gzip.decompress(raw).decode("utf-8"))


def cache_get(query: str, cloud_provider: str | None = None) -> Optional[dict]:
    """Return cached pipeline result if a similar query was seen before, else None.

    cloud_provider pins the namespace to the explicit requested provider.
    Without it, keyword detection is used — but explicit always wins.
    """
    if not CACHE_ENABLED:
        return None
    try:
        namespaced = _cache_query(query, cloud_provider)
        vector  = _embed(namespaced)
        results = _get_index().query(vector=vector, top_k=1, include_metadata=True)
        if results and results[0].score >= THRESHOLD:
            log.info(f"[Cache HIT] similarity={results[0].score:.4f} id={results[0].id}")
            return _decompress(results[0].metadata["result"])
        if results:
            log.info(f"[Cache MISS] best similarity={results[0].score:.4f}")
        else:
            log.info("[Cache MISS] empty index")
    except Exception as e:
        log.warning(f"[Cache] get failed (non-fatal): {e}")
    return None


def cache_set(query: str, result: dict, cloud_provider: str | None = None) -> None:
    """Store a pipeline result in the cache, namespaced by cloud provider."""
    if not CACHE_ENABLED:
        return
    try:
        cloud      = (cloud_provider or "").lower().strip() or _quick_cloud(query)
        namespaced = _cache_query(query, cloud)
        vector     = _embed(namespaced)
        compressed = _compress(result)
        _get_index().upsert(vectors=[{
            "id": str(uuid.uuid4()),
            "vector": vector,
            "metadata": {
                "query":      query[:500],
                "cloud":      cloud,
                "result":     compressed,
                "cached_at":  int(time.time()),
            },
        }])
        log.info(f"[Cache] stored [{cloud}] result for: {query[:60]}")
    except Exception as e:
        log.warning(f"[Cache] set failed (non-fatal): {e}")


def cache_flush() -> int:
    """Delete all vectors from the Upstash index. Returns count deleted."""
    if not CACHE_ENABLED:
        return 0
    try:
        index = _get_index()
        info  = index.info()
        index.reset()
        count = getattr(info, "vector_count", 0) or 0
        log.info(f"[Cache] flushed {count} entries")
        return count
    except Exception as e:
        log.warning(f"[Cache] flush failed: {e}")
        return 0
