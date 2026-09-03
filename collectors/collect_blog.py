# collectors/collect_blog.py
# Scrapes AWS Architecture Blog posts for architecture reasoning content.
#
# FIX: The blog index page is JavaScript-rendered — BeautifulSoup can't see
# post links there. Instead we use the RSS feed, which is plain XML and
# gives us post URLs reliably. We paginate the feed to collect URLs, then
# scrape each individual post page (which IS server-rendered HTML).

import requests
import json
import os
import time
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from config import RAW_BLOG

HEADERS = {"User-Agent": "Mozilla/5.0 (research project)"}


def get_post_urls_from_feed(page=1):
    """Fetch one page of the RSS feed and return a list of post URLs.

    The AWS blog runs on WordPress. WordPress RSS feeds support ?paged=N.
    Each page returns ~10 post URLs in plain XML — no JavaScript needed.
    """
    url      = f"https://aws.amazon.com/blogs/architecture/feed/?paged={page}"
    response = requests.get(url, headers=HEADERS, timeout=15)

    if response.status_code != 200 or not response.text.strip():
        return []

    try:
        root  = ET.fromstring(response.text)
        items = root.findall(".//item")
        urls  = []

        for item in items:
            link = item.find("link")
            if link is not None and link.text:
                urls.append(link.text.strip())

        return urls

    except ET.ParseError:
        return []


def scrape_post(url):
    """Scrape a single blog post page and return its title + text content."""

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, "html.parser")

        # AWS blog posts keep content in one of these containers
        content = (
            soup.find("div", {"class": "blog-post-content"}) or
            soup.find("div", {"class": "aws-text-box"})       or
            soup.find("article")
        )

        if not content:
            return None

        title_tag = soup.find("h1")
        title     = title_tag.get_text(strip=True) if title_tag else "Unknown"

        # Remove code blocks — architecture reasoning is in prose, not code
        for tag in content.find_all(["pre", "code", "script", "style"]):
            tag.decompose()

        text = content.get_text(separator="\n", strip=True)

        if len(text) < 300:
            return None

        return {
            "source": "aws_blog",
            "title":  title,
            "url":    url,
            "text":   text
        }

    except Exception as e:
        print(f"  Error scraping {url}: {e}")
        return None


def run(max_posts=150):
    os.makedirs(RAW_BLOG, exist_ok=True)

    # Step 1: collect post URLs from RSS feed pages
    print("Collecting post URLs from RSS feed...")
    all_urls  = []
    feed_page = 1

    while len(all_urls) < max_posts:
        urls = get_post_urls_from_feed(page=feed_page)

        if not urls:
            print(f"  No more posts at feed page {feed_page}. Stopping URL collection.")
            break

        all_urls.extend(urls)
        print(f"  Feed page {feed_page}: {len(urls)} URLs (total: {len(all_urls)})")
        feed_page += 1
        time.sleep(0.5)

    all_urls = all_urls[:max_posts]
    print(f"\nTotal URLs to scrape: {len(all_urls)}")

    # Step 2: scrape each post individually
    print("\nScraping posts...")
    collected = 0

    for i, url in enumerate(all_urls):
        slug     = url.rstrip("/").split("/")[-1][:80]
        out_path = os.path.join(RAW_BLOG, f"{slug}.json")

        # Resume support — skip posts already saved
        if os.path.exists(out_path):
            print(f"  [{i+1}/{len(all_urls)}] Already saved, skipping.")
            collected += 1
            continue

        post = scrape_post(url)

        if post:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(post, f, indent=2)
            collected += 1
            print(f"  [{collected}/{len(all_urls)}] Saved: {post['title'][:70]}")
        else:
            print(f"  [{i+1}/{len(all_urls)}] Skipped (no content): {slug}")

        time.sleep(0.8)

    print(f"\nTotal blog posts saved: {collected}")


if __name__ == "__main__":
    run(max_posts=150)
