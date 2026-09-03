# collectors/collect_azure_stackoverflow.py
#
# Fetches Azure architecture questions + accepted answers from Stack Overflow.
# Same bulk-fetch pattern as collect_stackoverflow.py — one API call per 100 answers.
#
# API quota:  300 requests/day without a key (not enough)
#             10,000 requests/day with a free key
# Get your free key → https://stackapps.com/apps/oauth/register

import requests
import json
import os
import time
from bs4 import BeautifulSoup
from config import STACKOVERFLOW_KEY, RAW_AZURE_STACKOVERFLOW

TAGS = [
    "azure",
    "azure-functions",
    "azure-kubernetes-service",
    "azure-cosmos-db",
    "azure-service-bus",
    "azure-event-hub",
    "azure-app-service",
    "azure-container-apps",
    "azure-api-management",
    "azure-storage",
    "azure-blob-storage",
    "azure-active-directory",
    "azure-key-vault",
    "azure-application-gateway",
    "azure-front-door",
    "azure-monitor",
    "azure-devops",
    "azure-sql-database",
    "azure-cache-for-redis",
    "azure-virtual-network",
]

quota_remaining = 10000


def safe_get(url, params):
    global quota_remaining
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=10)
            if not response.content or not response.text.strip():
                time.sleep(3)
                continue

            data = response.json()
            quota_remaining = data.get("quota_remaining", quota_remaining)

            if "backoff" in data:
                wait = int(data["backoff"]) + 1
                print(f"  API backoff: waiting {wait}s...")
                time.sleep(wait)

            if quota_remaining < 20:
                print(f"  WARNING: only {quota_remaining} API requests left today. Stopping.")
                return {}

            return data

        except Exception as e:
            print(f"  Request error (attempt {attempt + 1}/3): {e}")
            time.sleep(3)

    return {}


def clean_html(html_text):
    return BeautifulSoup(html_text, "html.parser").get_text()


def fetch_questions(tag, page=1):
    data = safe_get(
        "https://api.stackexchange.com/2.3/questions",
        {
            "order":    "desc",
            "sort":     "votes",
            "tagged":   tag,
            "site":     "stackoverflow",
            "filter":   "withbody",
            "page":     page,
            "pagesize": 50,
            "min":      5,
            "key":      STACKOVERFLOW_KEY,
        }
    )
    return data.get("items", [])


def fetch_answers_bulk(answer_ids):
    if not answer_ids:
        return {}

    ids_string = ";".join(str(i) for i in answer_ids[:100])
    data = safe_get(
        f"https://api.stackexchange.com/2.3/answers/{ids_string}",
        {
            "site":   "stackoverflow",
            "filter": "withbody",
            "key":    STACKOVERFLOW_KEY,
        }
    )
    return {
        item["answer_id"]: clean_html(item.get("body", ""))
        for item in data.get("items", [])
    }


def collect_for_tag(tag, pages=3):
    output_path = os.path.join(RAW_AZURE_STACKOVERFLOW, f"{tag}.json")

    if os.path.exists(output_path):
        with open(output_path) as f:
            existing = json.load(f)
        if len(existing) > 0:
            print(f"  Already collected ({len(existing)} pairs), skipping.")
            return len(existing)

    collected = []

    for page_num in range(1, pages + 1):
        if quota_remaining < 20:
            print("  Quota too low, stopping.")
            break

        questions = fetch_questions(tag, page=page_num)
        print(f"  Page {page_num} | {len(questions)} questions found | Quota left: {quota_remaining}")

        if not questions:
            break

        answered = [q for q in questions if q.get("accepted_answer_id")]
        ids      = [q["accepted_answer_id"] for q in answered]
        answers  = fetch_answers_bulk(ids)

        for q in answered:
            answer_text = answers.get(q["accepted_answer_id"], "")
            if not answer_text:
                continue

            collected.append({
                "source":         "stackoverflow",
                "cloud":          "azure",
                "tag":            tag,
                "question_id":    q["question_id"],
                "title":          q["title"],
                "question_text":  clean_html(q.get("body", "")),
                "question_score": q["score"],
                "answer_text":    answer_text,
                "answer_id":      q["accepted_answer_id"],
                "tags":           q.get("tags", []),
            })

        time.sleep(1)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(collected, f, indent=2)

    print(f"  Saved {len(collected)} pairs → {output_path}")
    return len(collected)


def run():
    os.makedirs(RAW_AZURE_STACKOVERFLOW, exist_ok=True)
    total = 0

    for tag in TAGS:
        if quota_remaining < 20:
            print(f"\nQuota exhausted. Stopping at {total} pairs total.")
            break

        print(f"\nCollecting: {tag}")
        count  = collect_for_tag(tag, pages=3)
        total += count
        time.sleep(1)

    print(f"\nTotal Azure SO Q&A pairs collected: {total}")
    print(f"API quota remaining: {quota_remaining}")


if __name__ == "__main__":
    run()
