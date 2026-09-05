# processors/process_and_load_multicloud.py
#
# Phase 2 (Azure + GCP): Clean → Chunk → Load into cloud-specific ChromaDB collections
#
# Creates six new collections (leaving existing AWS collections untouched):
#
#   architecture_patterns_azure   ← Azure docs, blog, GitHub READMEs
#   service_comparisons_azure     ← Azure Stack Overflow Q&A
#   terraform_examples_azure      ← Azure GitHub Terraform files
#
#   architecture_patterns_gcp     ← GCP docs, blog, GitHub READMEs
#   service_comparisons_gcp       ← GCP Stack Overflow Q&A
#   terraform_examples_gcp        ← GCP GitHub Terraform files
#
# Run this AFTER running all the Azure/GCP collectors.
# The existing process_and_load.py still handles AWS — don't remove it.

import os
import json
import re
import chromadb

from sentence_transformers import SentenceTransformer
from config import (
    RAW_AZURE_DOCS, RAW_AZURE_STACKOVERFLOW, RAW_AZURE_BLOG, RAW_AZURE_GITHUB,
    RAW_GCP_DOCS,   RAW_GCP_STACKOVERFLOW,   RAW_GCP_BLOG,   RAW_GCP_GITHUB,
)


CHROMA_DIR    = "data/chromadb"
EMBED_MODEL   = "all-MiniLM-L6-v2"
CHUNK_SIZE    = 400
CHUNK_OVERLAP = 60

COMPARISON_KEYWORDS = [
    "vs ", "versus", "compared to", "difference between",
    "when to use", "choose between", "should i use",
    "trade-off", "tradeoff", "instead of", "over using",
    # Azure-specific
    "azure functions vs", "aks vs", "cosmos db vs", "service bus vs",
    "app service vs", "container apps vs",
    # GCP-specific
    "cloud run vs", "gke vs", "cloud functions vs", "pubsub vs",
    "bigquery vs", "spanner vs", "firestore vs",
]



def clean_text(text):
    text = text.encode("utf-8", "ignore").decode("utf-8")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def should_skip_doc(text):
    text_lower = text.lower()
    skip_phrases = [
        "no longer available", "this service has been discontinued",
        "end of life", "end-of-life", "this page has moved", "404 not found",
    ]
    return any(p in text_lower for p in skip_phrases)


def is_comparison_doc(text):
    text_lower = text.lower()
    matches = sum(1 for kw in COMPARISON_KEYWORDS if kw in text_lower)
    return matches >= 2



def chunk_text(text, source_id=""):
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]
    chunks     = []
    current    = []
    word_count = 0

    for para in paragraphs:
        para_words = len(para.split())

        if word_count + para_words > CHUNK_SIZE and current:
            chunks.append("\n\n".join(current))

            # Overlap: carry last N words forward
            overlap_words = 0
            overlap_paras = []
            for p in reversed(current):
                overlap_words += len(p.split())
                overlap_paras.insert(0, p)
                if overlap_words >= CHUNK_OVERLAP:
                    break

            current    = overlap_paras
            word_count = sum(len(p.split()) for p in current)

        current.append(para)
        word_count += para_words

    if current:
        chunks.append("\n\n".join(current))

    return chunks



def _load_docs_dir(raw_dir: str, cloud: str) -> list[tuple[str, dict]]:
    """Load all JSON files from a raw docs directory."""
    docs = []
    if not os.path.isdir(raw_dir):
        print(f"  [skip] {raw_dir} not found — run the collector first")
        return docs

    for filename in os.listdir(raw_dir):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(raw_dir, filename), encoding="utf-8") as f:
            data = json.load(f)

        text = clean_text(data.get("text", ""))
        if len(text) < 200 or should_skip_doc(text):
            continue

        docs.append((text, {
            "source":  f"{cloud}_docs",
            "cloud":   cloud,
            "url":     data.get("url", ""),
            "section": data.get("section", ""),
        }))

    print(f"  Loaded {len(docs)} {cloud} doc pages from {raw_dir}")
    return docs


def _load_stackoverflow_dir(raw_dir: str, cloud: str) -> list[tuple[str, dict]]:
    docs = []
    if not os.path.isdir(raw_dir):
        print(f"  [skip] {raw_dir} not found — run the collector first")
        return docs

    for filename in os.listdir(raw_dir):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(raw_dir, filename), encoding="utf-8") as f:
            pairs = json.load(f)

        if not isinstance(pairs, list):
            continue

        for pair in pairs:
            title  = pair.get("title", "")
            q_text = pair.get("question_text", "")
            a_text = pair.get("answer_text", "")
            combined = f"Question: {title}\n\n{q_text}\n\nAnswer:\n{a_text}"
            text   = clean_text(combined)

            if len(text) < 100:
                continue

            docs.append((text, {
                "source":      "stackoverflow",
                "cloud":       cloud,
                "question_id": str(pair.get("question_id", "")),
                "tag":         pair.get("tag", ""),
                "score":       str(pair.get("question_score", 0)),
            }))

    print(f"  Loaded {len(docs)} {cloud} SO Q&A pairs from {raw_dir}")
    return docs


def _load_blog_dir(raw_dir: str, cloud: str) -> list[tuple[str, dict]]:
    docs = []
    if not os.path.isdir(raw_dir):
        print(f"  [skip] {raw_dir} not found — run the collector first")
        return docs

    for filename in os.listdir(raw_dir):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(raw_dir, filename), encoding="utf-8") as f:
            data = json.load(f)

        text = clean_text(data.get("text", ""))
        if len(text) < 300 or should_skip_doc(text):
            continue

        docs.append((text, {
            "source": f"{cloud}_blog",
            "cloud":  cloud,
            "title":  data.get("title", ""),
            "url":    data.get("url", ""),
        }))

    print(f"  Loaded {len(docs)} {cloud} blog posts from {raw_dir}")
    return docs


def _load_github_dir(raw_dir: str, cloud: str) -> tuple[list, list]:
    """Returns (readme_docs, terraform_docs)."""
    readme_docs    = []
    terraform_docs = []

    if not os.path.isdir(raw_dir):
        print(f"  [skip] {raw_dir} not found — run the collector first")
        return readme_docs, terraform_docs

    for filename in os.listdir(raw_dir):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(raw_dir, filename), encoding="utf-8") as f:
            data = json.load(f)

        repo = data.get("repo", filename)

        readme = clean_text(data.get("readme", ""))
        if len(readme) > 200:
            readme_docs.append((readme, {
                "source": "github_readme",
                "cloud":  cloud,
                "repo":   repo,
                "stars":  str(data.get("stars", 0)),
            }))

        for tf_file in data.get("terraform", []):
            content = clean_text(tf_file.get("content", ""))
            if len(content) > 100:
                terraform_docs.append((content, {
                    "source": "github_terraform",
                    "cloud":  cloud,
                    "repo":   repo,
                    "path":   tf_file.get("path", ""),
                }))

    print(f"  Loaded {len(readme_docs)} {cloud} READMEs, {len(terraform_docs)} Terraform files from {raw_dir}")
    return readme_docs, terraform_docs



def load_cloud_into_chromadb(cloud: str, arch_docs, comparison_docs, terraform_docs, model, client):
    """Embed and insert docs into cloud-specific ChromaDB collections."""

    arch_col = client.get_or_create_collection(f"architecture_patterns_{cloud}")
    comp_col = client.get_or_create_collection(f"service_comparisons_{cloud}")
    terr_col = client.get_or_create_collection(f"terraform_examples_{cloud}")

    def insert_docs(collection, docs, col_name):
        all_chunks    = []
        all_metadatas = []
        all_ids       = []
        chunk_index   = 0

        for text, metadata in docs:
            for chunk in chunk_text(text, metadata.get("source", "")):
                if len(chunk.strip()) < 80:
                    continue
                all_chunks.append(chunk)
                all_metadatas.append(metadata)
                all_ids.append(f"{col_name}_{chunk_index}")
                chunk_index += 1

        if not all_chunks:
            print(f"  {col_name}: no chunks to insert")
            return 0

        print(f"  {col_name}: embedding {len(all_chunks)} chunks...")

        all_embeddings = []
        batch_size     = 256
        for i in range(0, len(all_chunks), batch_size):
            batch      = all_chunks[i:i + batch_size]
            embeddings = model.encode(batch, show_progress_bar=False).tolist()
            all_embeddings.extend(embeddings)
            print(f"    Embedded {min(i + batch_size, len(all_chunks))}/{len(all_chunks)}")

        collection.add(
            documents=all_chunks,
            embeddings=all_embeddings,
            metadatas=all_metadatas,
            ids=all_ids,
        )
        print(f"  {col_name}: {len(all_chunks)} chunks loaded ✓")
        return len(all_chunks)

    a = insert_docs(arch_col,  arch_docs,        f"architecture_patterns_{cloud}")
    c = insert_docs(comp_col,  comparison_docs,  f"service_comparisons_{cloud}")
    t = insert_docs(terr_col,  terraform_docs,   f"terraform_examples_{cloud}")

    print(f"\n  {cloud.upper()} collection sizes:")
    print(f"    architecture_patterns_{cloud}  : {arch_col.count()} chunks")
    print(f"    service_comparisons_{cloud}    : {comp_col.count()} chunks")
    print(f"    terraform_examples_{cloud}     : {terr_col.count()} chunks")



def run(clouds: list[str] | None = None):
    """
    Args:
        clouds: list of "azure" | "gcp" (or None to process both)
    """
    if clouds is None:
        clouds = ["azure", "gcp"]

    print("=" * 60)
    print("MULTI-CLOUD PROCESSING & LOADING INTO CHROMADB")
    print(f"Clouds: {', '.join(clouds)}")
    print("=" * 60)

    os.makedirs(CHROMA_DIR, exist_ok=True)

    print("\nLoading embedding model...")
    model  = SentenceTransformer(EMBED_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    cloud_dirs = {
        "azure": {
            "docs":   RAW_AZURE_DOCS,
            "so":     RAW_AZURE_STACKOVERFLOW,
            "blog":   RAW_AZURE_BLOG,
            "github": RAW_AZURE_GITHUB,
        },
        "gcp": {
            "docs":   RAW_GCP_DOCS,
            "so":     RAW_GCP_STACKOVERFLOW,
            "blog":   RAW_GCP_BLOG,
            "github": RAW_GCP_GITHUB,
        },
    }

    for cloud in clouds:
        if cloud not in cloud_dirs:
            print(f"Unknown cloud: {cloud} — skipping")
            continue

        dirs = cloud_dirs[cloud]
        print(f"\n{'=' * 50}")
        print(f"Processing {cloud.upper()}")
        print(f"{'=' * 50}")

        print(f"\n[1/3] Loading raw data for {cloud}...")
        doc_docs            = _load_docs_dir(dirs["docs"], cloud)
        so_docs             = _load_stackoverflow_dir(dirs["so"], cloud)
        blog_docs           = _load_blog_dir(dirs["blog"], cloud)
        readme_docs, tf_docs = _load_github_dir(dirs["github"], cloud)

        print(f"\n[2/3] Routing {cloud} documents to collections...")
        arch_docs       = []
        comparison_docs = []

        # Docs: route comparison-heavy pages to service_comparisons
        for text, meta in doc_docs:
            if is_comparison_doc(text):
                comparison_docs.append((text, meta))
            else:
                arch_docs.append((text, meta))

        # Blog + README → architecture patterns
        arch_docs.extend(blog_docs)
        arch_docs.extend(readme_docs)

        # Stack Overflow → service comparisons
        comparison_docs.extend(so_docs)

        # Terraform files → terraform_examples
        terraform_docs = tf_docs

        print(f"  architecture_patterns_{cloud}  : {len(arch_docs)} documents")
        print(f"  service_comparisons_{cloud}    : {len(comparison_docs)} documents")
        print(f"  terraform_examples_{cloud}     : {len(terraform_docs)} documents")

        print(f"\n[3/3] Embedding and loading {cloud} into ChromaDB...")
        load_cloud_into_chromadb(cloud, arch_docs, comparison_docs, terraform_docs, model, client)

    print("\n\nAll done. Multi-cloud ChromaDB collections are ready.")
    print("Existing AWS collections are unchanged.")


if __name__ == "__main__":
    import sys
    clouds = sys.argv[1:] if len(sys.argv) > 1 else None
    run(clouds)
