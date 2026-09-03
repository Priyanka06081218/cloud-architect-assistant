# collectors/collect_aws_docs.py
# Scrapes specific AWS documentation pages and saves them as text files

import requests
import json
import os
import time
from bs4 import BeautifulSoup
from config import RAW_AWS_DOCS

# These are the exact AWS doc sections most useful for architecture decisions.
# Each key is a category name, each value is the starting URL to crawl.

DOC_SECTIONS = {
    "load_balancing": "https://docs.aws.amazon.com/elasticloadbalancing/latest/userguide/what-is-load-balancing.html",
    "ecs":            "https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html",
    "eks":            "https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html",
    "lambda":         "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html",
    "rds":            "https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Welcome.html",
    "dynamodb":       "https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html",
    "aurora":         "https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_AuroraOverview.html",
    "elasticache":    "https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/WhatIs.html",
    "api_gateway":    "https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html",
    "cloudfront":     "https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html",
    "vpc":            "https://docs.aws.amazon.com/vpc/latest/userguide/what-is-amazon-vpc.html",
    "auto_scaling":   "https://docs.aws.amazon.com/autoscaling/ec2/userguide/what-is-amazon-ec2-auto-scaling.html",
    "sqs":            "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html",
    "kinesis":        "https://docs.aws.amazon.com/streams/latest/dev/introduction.html",
    "s3":             "https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html",
    "well_architected": "https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html",
}

def get_page_text(url):
    """Fetch a single AWS docs page and return clean text."""
    
    headers = {"User-Agent": "Mozilla/5.0 (research project)"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")
        
        # AWS docs keep their content inside this specific div
        content = soup.find("div", {"id": "main-content"})
        
        if not content:
            return None
        
        # Remove navigation and feedback elements — they're noise
        for tag in content.find_all(["nav", "footer", "aside", "script", "style"]):
            tag.decompose()
        
        text = content.get_text(separator="\n", strip=True)
        
        # Only keep pages with real content (not just navigation pages)
        if len(text) < 300:
            return None
            
        return text
    
    except Exception as e:
        print(f"  Failed: {url} — {e}")
        return None


def get_subpage_links(url):
    """Get links to other AWS docs pages from the current page."""
    
    headers = {"User-Agent": "Mozilla/5.0 (research project)"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, "html.parser")
        content = soup.find("div", {"id": "main-content"})
        
        if not content:
            return []
        
        links = []
        for a_tag in content.find_all("a", href=True):
            href = a_tag["href"]
            
            # Only follow links within the same AWS docs domain
            if href.startswith("https://docs.aws.amazon.com"):
                links.append(href)
            elif href.startswith("./") or href.startswith("../"):
                # Relative links — build the full URL
                base = "/".join(url.split("/")[:-1])
                links.append(base + "/" + href.lstrip("./"))
        
        return links[:15]  # max 15 links per page to avoid crawling too deep
    
    except Exception:
        return []


def scrape_section(section_name, start_url, max_pages=40):
    """Crawl a section of AWS docs starting from a URL. Save each page."""
    
    output_dir = os.path.join(RAW_AWS_DOCS, section_name)
    os.makedirs(output_dir, exist_ok=True)
    
    visited = set()
    queue   = [start_url]
    saved   = 0
    
    print(f"\nScraping: {section_name}")
    
    while queue and saved < max_pages:
        url = queue.pop(0)
        
        if url in visited:
            continue
        visited.add(url)
        
        text = get_page_text(url)
        
        if text:
            # Use the last part of the URL as the filename
            filename = url.rstrip("/").split("/")[-1].replace(".html", "")
            filepath = os.path.join(output_dir, f"{filename}.json")
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({
                    "source":  "aws_docs",
                    "section": section_name,
                    "url":     url,
                    "text":    text
                }, f, indent=2)
            
            saved += 1
            print(f"  [{saved}/{max_pages}] Saved: {filename}")
            
            # Add subpage links to the queue
            queue.extend(get_subpage_links(url))
        
        time.sleep(0.5)  # polite delay between requests
    
    print(f"  Done. Saved {saved} pages for '{section_name}'")
    return saved


def run():
    os.makedirs(RAW_AWS_DOCS, exist_ok=True)
    total = 0
    
    for section_name, start_url in DOC_SECTIONS.items():
        count = scrape_section(section_name, start_url, max_pages=40)
        total += count
    
    print(f"\nTotal AWS docs pages collected: {total}")


if __name__ == "__main__":
    run()
