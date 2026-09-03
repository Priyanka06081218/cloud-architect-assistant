# collectors/verify_collection.py
# Quick sanity check — shows what was collected from each source

import os
import json
from config import RAW_AWS_DOCS, RAW_WHITEPAPERS, RAW_STACKOVERFLOW, RAW_GITHUB, RAW_BLOG


def count_files(folder):
    """Count JSON files in a folder (including subfolders)."""
    count = 0
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.endswith(".json"):
                count += 1
    return count


def sample_file(folder):
    """Show a preview of one file from the folder."""
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.endswith(".json"):
                path = os.path.join(root, file)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)

                # Stack Overflow files are a list of Q&A pairs
                if isinstance(data, list):
                    if data:
                        first = data[0]
                        text  = first.get("question_text") or first.get("title") or ""
                        return text[:200]
                    return "Empty list"

                # All other sources are dicts
                text = data.get("text") or \
                       data.get("readme") or \
                       data.get("question_text") or ""

                if isinstance(data.get("pages"), list):
                    text = data["pages"][0]["text"] if data["pages"] else ""

                return text[:200]
    return "No files found"


def run():
    sources = {
        "AWS Docs":     RAW_AWS_DOCS,
        "Whitepapers":  RAW_WHITEPAPERS,
        "Stack Overflow": RAW_STACKOVERFLOW,
        "GitHub":       RAW_GITHUB,
        "AWS Blog":     RAW_BLOG,
    }
    
    print("=" * 50)
    print("COLLECTION SUMMARY")
    print("=" * 50)
    
    total = 0
    for name, folder in sources.items():
        count = count_files(folder)
        total += count
        print(f"\n{name}: {count} files")

        # For Stack Overflow, also show total Q&A pair count across all files
        if name == "Stack Overflow":
            pair_count = 0
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.endswith(".json"):
                        with open(os.path.join(root, file), encoding="utf-8") as f:
                            d = json.load(f)
                        if isinstance(d, list):
                            pair_count += len(d)
            print(f"  → {pair_count} total Q&A pairs across all tag files")

        print(f"Sample: {sample_file(folder)[:150]}...")
    
    print("\n" + "=" * 50)
    print(f"TOTAL FILES COLLECTED: {total}")
    print("=" * 50)


if __name__ == "__main__":
    run()
