# processors/verify_chromadb.py
#
# Tests that ChromaDB retrieval is working correctly.
# Runs 3 test queries — one per collection — and prints the top result.
# If results look relevant, your RAG pipeline is ready.

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_DIR  = "data/chromadb"
EMBED_MODEL = "all-MiniLM-L6-v2"

TEST_QUERIES = {
    "architecture_patterns": "How do I design a scalable web application on AWS with high availability?",
    "service_comparisons":   "When should I use ALB instead of NLB for my application?",
    "terraform_examples":    "Terraform code for AWS ECS with Application Load Balancer",
}


def run():
    print("Loading embedding model...")
    model  = SentenceTransformer(EMBED_MODEL)
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    print("\n" + "=" * 60)
    print("CHROMADB RETRIEVAL TEST")
    print("=" * 60)

    for collection_name, query in TEST_QUERIES.items():
        print(f"\nCollection : {collection_name}")
        print(f"Query      : {query}")
        print("-" * 60)

        try:
            collection = client.get_collection(collection_name)
            embedding  = model.encode([query]).tolist()

            results = collection.query(
                query_embeddings=embedding,
                n_results=2,
            )

            for i, doc in enumerate(results["documents"][0]):
                source = results["metadatas"][0][i].get("source", "unknown")
                print(f"\nResult {i+1} (source: {source})")
                print(doc[:300] + "...")

        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 60)
    print("If results above look relevant to each query, RAG is ready.")
    print("=" * 60)


if __name__ == "__main__":
    run()
