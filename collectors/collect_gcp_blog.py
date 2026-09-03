# collectors/collect_gcp_blog.py
#
# Scrapes GCP blog posts from:
#   - Google Cloud Blog (cloud.google.com/blog)
#   - Google Cloud Architecture Center articles
#
# Saves results to RAW_GCP_BLOG as JSON files.

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import time
import feedparser
from bs4 import BeautifulSoup
from config import RAW_GCP_BLOG

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GCPBlogCollector/1.0; "
        "cloud-architect-assistant research bot)"
    )
}

# Google Cloud blog RSS feeds by topic
RSS_FEEDS = [
    "https://cloudblog.withgoogle.com/products/gcp/rss/",
    "https://cloudblog.withgoogle.com/topics/developers-practitioners/rss/",
    "https://cloudblog.withgoogle.com/topics/infrastructure/rss/",
]

# Curated GCP Architecture Center article listings
ARCH_CENTER_LISTINGS = [
    "https://cloud.google.com/architecture/all-articles",
    "https://cloud.google.com/architecture/framework",
]

CONTENT_SELECTORS = [
    "article",
    "div.devsite-article-body",
    "main",
    "div[role='main']",
    "div#main-content",
]


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["nav", "footer", "aside", "script", "style", "header"]):
        tag.decompose()
    for selector in CONTENT_SELECTORS:
        if selector.startswith("div."):
            node = soup.find("div", class_=selector[len("div."):])
        elif selector.startswith("div#"):
            node = soup.find("div", id=selector[len("div#"):])
        elif "[" in selector:
            node = soup.find("div", attrs={"role": "main"})
        else:
            node = soup.find(selector)
        if node:
            return node.get_text(separator="\n", strip=True)
    body = soup.find("body")
    return body.get_text(separator="\n", strip=True) if body else ""


def fetch_url(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return None
        return extract_text(resp.text)
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def collect_rss(feed_url: str, max_posts: int = 30) -> list[dict]:
    records = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:max_posts]:
            url  = entry.get("link", "")
            if not url:
                continue

            slug = url.rstrip("/").split("/")[-1][:60]
            out  = os.path.join(RAW_GCP_BLOG, f"rss_{slug}.json")
            if os.path.exists(out):
                records.append({"skipped": True})
                continue

            text = fetch_url(url)
            if not text or len(text) < 300:
                continue

            record = {
                "source": "blog",
                "cloud":  "gcp",
                "url":    url,
                "title":  entry.get("title", ""),
                "text":   text,
            }
            with open(out, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)

            print(f"  Saved: {slug}")
            records.append(record)
            time.sleep(1.5)

    except Exception as e:
        print(f"  RSS error for {feed_url}: {e}")

    return records


def collect_arch_center_listing(listing_url: str) -> list[dict]:
    records = []
    try:
        resp = requests.get(listing_url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return records
        soup = BeautifulSoup(resp.text, "html.parser")
        links = [a["href"] for a in soup.find_all("a", href=True)
                 if "/architecture/" in a["href"] and not a["href"].endswith("/architecture/")]

        base = "https://cloud.google.com"
        seen = set()
        abs_links = []
        for href in links:
            url = href if href.startswith("http") else base + href
            if url not in seen:
                seen.add(url)
                abs_links.append(url)

        for url in abs_links[:25]:
            slug = url.rstrip("/").split("/")[-1][:60]
            out  = os.path.join(RAW_GCP_BLOG, f"arch_{slug}.json")
            if os.path.exists(out):
                continue

            text = fetch_url(url)
            if not text or len(text) < 300:
                continue

            record = {"source": "blog", "cloud": "gcp", "url": url, "title": slug, "text": text}
            with open(out, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)

            print(f"  Saved: {slug}")
            records.append(record)
            time.sleep(1.5)

    except Exception as e:
        print(f"  Error scraping listing {listing_url}: {e}")

    return records


def run():
    os.makedirs(RAW_GCP_BLOG, exist_ok=True)
    total = 0

    print("=== Google Cloud Blog RSS ===")
    for feed_url in RSS_FEEDS:
        print(f"\nFeed: {feed_url}")
        recs  = collect_rss(feed_url, max_posts=30)
        count = sum(1 for r in recs if not r.get("skipped"))
        total += count
        print(f"  {count} new posts")

    print("\n=== GCP Architecture Center ===")
    for listing_url in ARCH_CENTER_LISTINGS:
        print(f"\nListing: {listing_url}")
        recs   = collect_arch_center_listing(listing_url)
        total += len(recs)
        print(f"  {len(recs)} articles")

    print(f"\nDone. Total GCP blog posts: {total}")


if __name__ == "__main__":
    run()
