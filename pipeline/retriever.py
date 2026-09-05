# pipeline/retriever.py
#
# Queries ChromaDB collections and returns relevant text chunks.
# Each output type retrieves from a different collection:
#
#   architecture_patterns[_azure|_gcp]  → used for architecture recommendation
#   service_comparisons[_azure|_gcp]    → used for trade-off reasoning
#   terraform_examples[_azure|_gcp]     → used for Terraform generation
#
# When a cloud-specific collection has fewer than MIN_DOCS chunks (i.e., the
# data hasn't been collected yet), the function falls back gracefully with an
# empty string so the LLM still generates a response from its training.

import logging

import chromadb
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

CHROMA_DIR  = "data/chromadb"
EMBED_MODEL = "all-MiniLM-L6-v2"

# If a collection has fewer than this many documents, treat it as unpopulated.
MIN_DOCS = 10

# Human-readable cloud names used in RAG query strings.
# Add new clouds here rather than inline at each call site.
CLOUD_DISPLAY: dict[str, str] = {
    "aws":   "AWS",
    "azure": "Azure",
    "gcp":   "GCP",
}

# Load model and client once — reused for every query
_model  = None
_client = None


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def _get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client


def _collection_suffix(cloud_provider: str) -> str:
    """Return the ChromaDB collection suffix for a given cloud.

    "aws"      → "" (uses the original AWS collection names, no suffix)
    "azure"    → "_azure"
    "gcp"      → "_gcp"
    "agnostic" → "" (falls back to AWS)
    """
    pid = (cloud_provider or "aws").lower()
    if pid in ("azure",):
        return "_azure"
    if pid in ("gcp",):
        return "_gcp"
    return ""  # aws or agnostic → original names


def retrieve(collection_name: str, query: str, n_results: int = 5) -> list[str]:
    """Query a ChromaDB collection and return top-N relevant text chunks.

    Args:
        collection_name: e.g. "architecture_patterns", "architecture_patterns_azure"
        query:           what you're looking for
        n_results:       how many chunks to return

    Returns:
        List of text strings, most relevant first. Empty list if collection
        doesn't exist or is too small (collector hasn't run yet).
    """
    model  = _get_model()
    client = _get_client()

    # Check if collection exists and has enough data
    try:
        collection = client.get_collection(collection_name)
        if collection.count() < MIN_DOCS:
            return []
    except Exception:
        # Collection doesn't exist yet — data not collected
        return []

    embedding = model.encode([query]).tolist()

    results = collection.query(
        query_embeddings=embedding,
        n_results=min(n_results, collection.count()),
    )

    return results["documents"][0]


def retrieve_for_architecture(requirements: dict) -> str:
    """Retrieve context for architecture recommendation.

    Queries the cloud-specific architecture_patterns collection.
    Falls back gracefully if the collection is empty (data not yet collected).
    """
    cloud    = requirements.get("cloud_provider", "aws")
    suffix   = _collection_suffix(cloud)
    col_name = f"architecture_patterns{suffix}"

    cloud_name = CLOUD_DISPLAY.get(cloud.lower(), cloud.upper())
    query  = f"{requirements['workload_type']} {requirements['scale']} {cloud_name} architecture best practices"
    chunks = retrieve(col_name, query, n_results=5)

    if not chunks:
        log.warning(f"[retriever] {col_name} empty or missing — skipping RAG for architecture")
        return ""

    return "\n\n---\n\n".join(chunks)


def retrieve_for_tradeoffs(requirements: dict) -> str:
    """Retrieve context for service trade-off reasoning.

    Queries the cloud-specific service_comparisons collection.
    """
    cloud    = requirements.get("cloud_provider", "aws")
    suffix   = _collection_suffix(cloud)
    col_name = f"service_comparisons{suffix}"

    cloud_name   = CLOUD_DISPLAY.get(cloud.lower(), cloud.upper())
    constraints  = ", ".join(requirements.get("constraints", []))
    query  = f"{cloud_name} service comparison {requirements['workload_type']} {constraints}"
    chunks = retrieve(col_name, query, n_results=4)

    if not chunks:
        log.warning(f"[retriever] {col_name} empty or missing — skipping RAG for tradeoffs")
        return ""

    return "\n\n---\n\n".join(chunks)


def retrieve_for_terraform(services: list[str], cloud_provider: str = "aws") -> str:
    """Retrieve Terraform examples for the recommended services.

    Queries the cloud-specific terraform_examples collection.
    """
    suffix   = _collection_suffix(cloud_provider)
    col_name = f"terraform_examples{suffix}"

    cloud_name = CLOUD_DISPLAY.get(cloud_provider.lower(), cloud_provider.upper())
    query  = f"Terraform {cloud_name} {' '.join(services)}"
    chunks = retrieve(col_name, query, n_results=4)

    if not chunks:
        log.warning(f"[retriever] {col_name} empty or missing — skipping RAG for Terraform")
        return ""

    return "\n\n---\n\n".join(chunks)


if __name__ == "__main__":
    # Quick smoke test
    test_requirements = {
        "scale":          "500k concurrent users",
        "workload_type":  "e-commerce web application",
        "constraints":    ["high availability", "low latency"],
        "cloud_provider": "aws",
        "budget":         None,
    }

    print("=== AWS architecture retrieval ===")
    arch_ctx = retrieve_for_architecture(test_requirements)
    print(arch_ctx[:300] if arch_ctx else "(empty)")

    print("\n=== Azure architecture retrieval ===")
    test_requirements["cloud_provider"] = "azure"
    arch_ctx = retrieve_for_architecture(test_requirements)
    print(arch_ctx[:300] if arch_ctx else "(empty — Azure data not collected yet)")

    print("\n=== GCP architecture retrieval ===")
    test_requirements["cloud_provider"] = "gcp"
    arch_ctx = retrieve_for_architecture(test_requirements)
    print(arch_ctx[:300] if arch_ctx else "(empty — GCP data not collected yet)")
