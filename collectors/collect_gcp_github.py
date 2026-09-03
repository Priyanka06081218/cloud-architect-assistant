# collectors/collect_gcp_github.py
#
# Collects README and Terraform files from high-quality GCP infrastructure repos.
# Same pattern as collect_github.py.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import base64
import time
from config import GITHUB_TOKEN, RAW_GCP_GITHUB

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github.v3+json"
}

SEARCH_QUERIES = [
    "gcp architecture terraform stars:>200",
    "google cloud gke production terraform stars:>100",
    "google cloud run terraform stars:>100",
    "google cloud functions terraform stars:>100",
    "google bigquery terraform stars:>100",
    "google cloud spanner terraform stars:>50",
    "gcp well-architected terraform stars:>50",
    "google cloud platform infrastructure terraform stars:>100",
]


def search_repos(query, max_results=20):
    url    = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": "stars", "per_page": max_results}
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code != 200:
        print(f"  GitHub API error: {response.status_code}")
        return []
    return response.json().get("items", [])


def get_readme(owner, repo):
    url      = f"https://api.github.com/repos/{owner}/{repo}/readme"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        return None
    encoded = response.json().get("content", "")
    return base64.b64decode(encoded).decode("utf-8", errors="ignore")


def get_terraform_files(owner, repo):
    url      = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD"
    response = requests.get(url, headers=HEADERS, params={"recursive": "1"})
    if response.status_code != 200:
        return []

    files = [item["path"] for item in response.json().get("tree", [])
             if item["path"].endswith(".tf")]

    tf_contents = []
    for path in files[:10]:
        raw_url  = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{path}"
        raw_resp = requests.get(raw_url, timeout=10)
        if raw_resp.status_code == 200:
            tf_contents.append({"path": path, "content": raw_resp.text})
        time.sleep(0.3)

    return tf_contents


def run():
    os.makedirs(RAW_GCP_GITHUB, exist_ok=True)
    seen_repos = set()
    total      = 0

    for query in SEARCH_QUERIES:
        print(f"\nQuery: {query}")
        repos = search_repos(query)
        print(f"  Found {len(repos)} repos")

        for repo in repos:
            owner     = repo["owner"]["login"]
            name      = repo["name"]
            full_name = f"{owner}/{name}"

            if full_name in seen_repos:
                continue
            seen_repos.add(full_name)

            slug     = full_name.replace("/", "__")
            out_path = os.path.join(RAW_GCP_GITHUB, f"{slug}.json")

            if os.path.exists(out_path):
                print(f"  [skip] {full_name}")
                continue

            print(f"  Collecting {full_name}...")
            readme = get_readme(owner, name)
            tf     = get_terraform_files(owner, name)

            if not readme and not tf:
                continue

            record = {
                "source":      "github",
                "cloud":       "gcp",
                "repo":        full_name,
                "stars":       repo.get("stargazers_count", 0),
                "description": repo.get("description", ""),
                "readme":      readme or "",
                "terraform":   tf,
            }

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)

            print(f"    Saved — README: {bool(readme)}, TF files: {len(tf)}")
            total += 1
            time.sleep(1)

        time.sleep(2)

    print(f"\nTotal GCP GitHub repos collected: {total}")


if __name__ == "__main__":
    run()
