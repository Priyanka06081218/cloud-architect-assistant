# collectors/collect_github.py
# Collects README and Terraform files from high-quality AWS infrastructure repos

import requests
import json
import os
import base64
import time
from config import GITHUB_TOKEN, RAW_GITHUB

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github.v3+json"
}

# These search terms find repos with real AWS production infrastructure
SEARCH_QUERIES = [
    "aws architecture terraform stars:>200",
    "aws eks production terraform stars:>100",
    "aws serverless architecture stars:>150",
    "aws microservices kubernetes stars:>100",
    "aws well-architected terraform stars:>50",
    "aws data pipeline terraform stars:>100",
    "aws cost optimization terraform stars:>50",
    "cloudformation architecture patterns stars:>100",
]


def search_repos(query, max_results=20):
    """Search GitHub for repositories matching a query."""
    
    url    = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": "stars", "per_page": max_results}
    
    response = requests.get(url, headers=HEADERS, params=params)
    
    if response.status_code != 200:
        print(f"  GitHub API error: {response.status_code}")
        return []
    
    return response.json().get("items", [])


def get_readme(owner, repo):
    """Download the README content of a repository."""
    
    url      = f"https://api.github.com/repos/{owner}/{repo}/readme"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code != 200:
        return None
    
    # README content is base64 encoded by the GitHub API
    encoded = response.json().get("content", "")
    return base64.b64decode(encoded).decode("utf-8", errors="ignore")


def get_terraform_files(owner, repo):
    """Get all .tf files from a repository (up to 10 files)."""
    
    # First get the full file tree
    url      = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD"
    params   = {"recursive": "1"}
    response = requests.get(url, headers=HEADERS, params=params)
    
    if response.status_code != 200:
        return []
    
    tree = response.json().get("tree", [])
    
    # Filter for .tf files that aren't too large
    tf_files = [
        item for item in tree
        if item["path"].endswith(".tf") and item.get("size", 0) < 30000
    ][:10]  # max 10 files per repo
    
    results = []
    for tf_file in tf_files:
        file_url  = f"https://api.github.com/repos/{owner}/{repo}/contents/{tf_file['path']}"
        file_resp = requests.get(file_url, headers=HEADERS)
        
        if file_resp.status_code == 200:
            encoded = file_resp.json().get("content", "")
            content = base64.b64decode(encoded).decode("utf-8", errors="ignore")
            results.append({
                "path":    tf_file["path"],
                "content": content
            })
        
        time.sleep(0.1)
    
    return results


def run():
    os.makedirs(RAW_GITHUB, exist_ok=True)
    
    total     = 0
    seen_repos = set()  # avoid collecting the same repo twice
    
    for query in SEARCH_QUERIES:
        print(f"\nSearching: {query}")
        repos = search_repos(query, max_results=15)
        
        for repo in repos:
            owner    = repo["owner"]["login"]
            name     = repo["name"]
            repo_key = f"{owner}/{name}"
            
            # Skip if we already collected this repo from a previous query
            if repo_key in seen_repos:
                continue
            seen_repos.add(repo_key)
            
            print(f"  Collecting: {repo_key} ({repo['stargazers_count']} stars)")
            
            readme = get_readme(owner, name)
            
            # Skip repos with no meaningful README
            if not readme or len(readme) < 200:
                print(f"  Skipped: README too short")
                continue
            
            tf_files = get_terraform_files(owner, name)
            
            data = {
                "source":      "github",
                "repo":        repo_key,
                "stars":       repo["stargazers_count"],
                "description": repo.get("description", ""),
                "readme":      readme,
                "terraform_files": tf_files
            }
            
            # Save as one file per repo
            safe_name = repo_key.replace("/", "_")
            output_path = os.path.join(RAW_GITHUB, f"{safe_name}.json")
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            total += 1
            print(f"  Saved: {output_path}")
            
            time.sleep(0.5)
    
    print(f"\nTotal GitHub repos collected: {total}")


if __name__ == "__main__":
    run()
