# processors/process_and_load.py
#
# Phase 2: Clean → Chunk → Load into ChromaDB
#
# Reads all raw collected data, cleans it, splits into chunks,
# and loads into three ChromaDB collections:
#
#   architecture_patterns  ← AWS docs, whitepapers, blog posts
#   service_comparisons    ← Stack Overflow Q&A + comparison-heavy docs
#   terraform_examples     ← GitHub Terraform files
#
# Embeddings are generated locally using sentence-transformers (free, no API key).

import os
import json
import re
import chromadb

from sentence_transformers import SentenceTransformer
from config import RAW_AWS_DOCS, RAW_WHITEPAPERS, RAW_STACKOVERFLOW, RAW_GITHUB, RAW_BLOG

#  Setup 

# ChromaDB saves to disk — data persists across runs
CHROMA_DIR = "data/chromadb"

# Embedding model — runs locally, no API key needed
# all-MiniLM-L6-v2 is small (80MB), fast, and accurate enough for retrieval
EMBED_MODEL = "all-MiniLM-L6-v2"

# Chunk settings
CHUNK_SIZE    = 400   # target words per chunk
CHUNK_OVERLAP = 60    # words of overlap between consecutive chunks

# Keywords that signal a document is about service comparisons/trade-offs
COMPARISON_KEYWORDS = [
    "vs ", "versus", "compared to", "difference between",
    "when to use", "choose between", "should i use",
    "trade-off", "tradeoff", "instead of", "over using",
    "alb vs", "nlb vs", "lambda vs", "ecs vs", "eks vs",
    "rds vs", "dynamodb vs", "sqs vs", "kinesis vs",
]


#  Cleaning functions (one per source type) 

def clean_text(text):
    """Shared cleaning applied to all sources.
    Removes encoding artifacts, collapses whitespace.
    """
    text = text.encode("utf-8", "ignore").decode("utf-8")  # fix encoding issues
    text = re.sub(r"[ \t]+", " ", text)                    # collapse spaces/tabs
    text = re.sub(r"\n{3,}", "\n\n", text)                 # max 2 blank lines
    return text.strip()


def should_skip_doc(text):
    """Return True if this document is noise and should not be indexed."""
    text_lower = text.lower()

    skip_phrases = [
        "no longer available to new customers",
        "this service has been discontinued",
        "end of life",
        "end-of-life",
        "this page has moved",
        "404 not found",
    ]
    return any(phrase in text_lower for phrase in skip_phrases)


def is_comparison_doc(text):
    """Return True if this document is primarily about comparing services."""
    text_lower = text.lower()
    matches = sum(1 for kw in COMPARISON_KEYWORDS if kw in text_lower)
    return matches >= 2  # needs at least 2 comparison keywords to qualify


#  Chunking 

def chunk_text(text, source_id):
    """Split text into overlapping chunks of ~CHUNK_SIZE words.

    Splits on paragraph breaks first, then falls back to sentence breaks.
    Each chunk includes metadata for ChromaDB.
    """
    # Split on double newlines (paragraphs) first
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]

    chunks     = []
    current    = []
    word_count = 0

    for para in paragraphs:
        para_words = len(para.split())

        # If adding this paragraph would exceed chunk size, save current chunk
        if word_count + para_words > CHUNK_SIZE and current:
            chunk_text_joined = "\n\n".join(current)
            chunks.append(chunk_text_joined)

            # Overlap: keep last N words worth of paragraphs for context
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

    # Don't forget the last chunk
    if current:
        chunks.append("\n\n".join(current))

    return chunks


#  Document loaders (one per source type) 

def load_aws_docs():
    """Load AWS documentation files. Returns list of (text, metadata) tuples."""
    docs = []

    for root, dirs, files in os.walk(RAW_AWS_DOCS):
        for filename in files:
            if not filename.endswith(".json"):
                continue

            path = os.path.join(root, filename)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            text = clean_text(data.get("text", ""))

            if len(text) < 200 or should_skip_doc(text):
                continue

            docs.append((text, {
                "source":  "aws_docs",
                "url":     data.get("url", ""),
                "section": data.get("section", ""),
            }))

    print(f"  Loaded {len(docs)} AWS doc pages")
    return docs


def load_whitepapers():
    """Load whitepaper JSON files. Each file has multiple pages — treat each page as a doc."""
    docs = []

    for filename in os.listdir(RAW_WHITEPAPERS):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(RAW_WHITEPAPERS, filename)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        paper_name = data.get("name", filename)

        for page in data.get("pages", []):
            text = clean_text(page.get("text", ""))

            if len(text) < 150:
                continue

            docs.append((text, {
                "source":     "whitepaper",
                "paper_name": paper_name,
                "page":       str(page.get("page", 0)),
            }))

    print(f"  Loaded {len(docs)} whitepaper pages")
    return docs


def load_stackoverflow():
    """Load Stack Overflow Q&A pairs. Format each as: Question + Answer."""
    docs = []

    for filename in os.listdir(RAW_STACKOVERFLOW):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(RAW_STACKOVERFLOW, filename)
        with open(path, encoding="utf-8") as f:
            pairs = json.load(f)

        if not isinstance(pairs, list):
            continue

        for pair in pairs:
            title   = pair.get("title", "")
            q_text  = pair.get("question_text", "")
            a_text  = pair.get("answer_text", "")

            # Combine into a single readable document
            combined = f"Question: {title}\n\n{q_text}\n\nAnswer:\n{a_text}"
            text     = clean_text(combined)

            if len(text) < 100:
                continue

            docs.append((text, {
                "source":      "stackoverflow",
                "question_id": str(pair.get("question_id", "")),
                "tag":         pair.get("tag", ""),
                "score":       str(pair.get("question_score", 0)),
            }))

    print(f"  Loaded {len(docs)} Stack Overflow Q&A pairs")
    return docs


def load_github():
    """Load GitHub repos. READMEs go to architecture_patterns, .tf files go to terraform_examples."""
    readme_docs   = []
    terraform_docs = []

    for filename in os.listdir(RAW_GITHUB):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(RAW_GITHUB, filename)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        repo = data.get("repo", filename)

        # README → architecture patterns
        readme = clean_text(data.get("readme", ""))
        if len(readme) > 200:
            readme_docs.append((readme, {
                "source": "github_readme",
                "repo":   repo,
                "stars":  str(data.get("stars", 0)),
            }))

        # Terraform files → terraform examples collection
        for tf_file in data.get("terraform_files", []):
            content = clean_text(tf_file.get("content", ""))
            if len(content) > 100:
                terraform_docs.append((content, {
                    "source": "github_terraform",
                    "repo":   repo,
                    "path":   tf_file.get("path", ""),
                }))

    print(f"  Loaded {len(readme_docs)} GitHub READMEs, {len(terraform_docs)} Terraform files")
    return readme_docs, terraform_docs


def load_blog():
    """Load AWS Architecture Blog posts."""
    docs = []

    for filename in os.listdir(RAW_BLOG):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(RAW_BLOG, filename)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        text = clean_text(data.get("text", ""))

        if len(text) < 300 or should_skip_doc(text):
            continue

        docs.append((text, {
            "source": "aws_blog",
            "title":  data.get("title", ""),
            "url":    data.get("url", ""),
        }))

    print(f"  Loaded {len(docs)} blog posts")
    return docs


#  ChromaDB loader 

def load_into_chromadb(arch_docs, comparison_docs, terraform_docs):
    """Embed all chunks and insert into three ChromaDB collections."""

    os.makedirs(CHROMA_DIR, exist_ok=True)

    print("\nLoading embedding model (downloading once, ~80MB)...")
    model  = SentenceTransformer(EMBED_MODEL)

    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # Create or get each collection
    arch_col  = client.get_or_create_collection("architecture_patterns")
    comp_col  = client.get_or_create_collection("service_comparisons")
    terr_col  = client.get_or_create_collection("terraform_examples")

    def insert_docs(collection, docs, collection_name):
        """Chunk docs, embed, and insert into a ChromaDB collection."""
        all_chunks    = []
        all_metadatas = []
        all_ids       = []
        chunk_index   = 0

        for text, metadata in docs:
            chunks = chunk_text(text, metadata.get("source", ""))
            for chunk in chunks:
                if len(chunk.strip()) < 80:
                    continue
                all_chunks.append(chunk)
                all_metadatas.append(metadata)
                all_ids.append(f"{collection_name}_{chunk_index}")
                chunk_index += 1

        if not all_chunks:
            print(f"  {collection_name}: no chunks to insert")
            return

        print(f"  {collection_name}: embedding {len(all_chunks)} chunks...")

        # Embed in batches of 256 to avoid memory issues
        all_embeddings = []
        batch_size     = 256

        for i in range(0, len(all_chunks), batch_size):
            batch      = all_chunks[i:i + batch_size]
            embeddings = model.encode(batch, show_progress_bar=False).tolist()
            all_embeddings.extend(embeddings)
            print(f"    Embedded {min(i + batch_size, len(all_chunks))}/{len(all_chunks)}")

        # Insert into ChromaDB
        collection.add(
            documents=all_chunks,
            embeddings=all_embeddings,
            metadatas=all_metadatas,
            ids=all_ids,
        )

        print(f"  {collection_name}: {len(all_chunks)} chunks loaded")

    insert_docs(arch_col,  arch_docs,       "architecture_patterns")
    insert_docs(comp_col,  comparison_docs, "service_comparisons")
    insert_docs(terr_col,  terraform_docs,  "terraform_examples")

    # Final counts
    print(f"\nChromaDB collection sizes:")
    print(f"  architecture_patterns : {arch_col.count()} chunks")
    print(f"  service_comparisons   : {comp_col.count()} chunks")
    print(f"  terraform_examples    : {terr_col.count()} chunks")


#  Main pipeline 

def run():
    print("=" * 55)
    print("PHASE 2: PROCESSING & LOADING INTO CHROMADB")
    print("=" * 55)

    # Step 1: Load all raw data
    print("\n[1/3] Loading raw data...")
    aws_docs         = load_aws_docs()
    whitepaper_docs  = load_whitepapers()
    so_docs          = load_stackoverflow()
    readme_docs, terraform_docs = load_github()
    blog_docs        = load_blog()

    # Step 2: Route documents into the right collections
    #
    # architecture_patterns  → general architecture docs + blog posts + READMEs
    # service_comparisons    → SO Q&A + docs that compare services
    # terraform_examples     → all Terraform files from GitHub
    print("\n[2/3] Routing documents to collections...")

    arch_docs       = []
    comparison_docs = []

    # AWS docs: route comparison-heavy pages to service_comparisons
    for text, meta in aws_docs:
        if is_comparison_doc(text):
            comparison_docs.append((text, meta))
        else:
            arch_docs.append((text, meta))

    # Whitepapers → always architecture patterns
    arch_docs.extend(whitepaper_docs)

    # Stack Overflow → always service comparisons (that's what it's for)
    comparison_docs.extend(so_docs)

    # GitHub READMEs → architecture patterns
    arch_docs.extend(readme_docs)

    # Blog posts → architecture patterns
    arch_docs.extend(blog_docs)

    print(f"  architecture_patterns  : {len(arch_docs)} documents")
    print(f"  service_comparisons    : {len(comparison_docs)} documents")
    print(f"  terraform_examples     : {len(terraform_docs)} documents")

    # Step 3: Embed and load into ChromaDB
    print("\n[3/3] Embedding and loading into ChromaDB...")
    load_into_chromadb(arch_docs, comparison_docs, terraform_docs)

    print("\nProcessing complete. ChromaDB is ready.")


if __name__ == "__main__":
    run()
