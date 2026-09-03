# collectors/collect_stackoverflow.py
# Fetches AWS architecture questions + accepted answers from Stack Overflow
#
# KEY DESIGN: answers are fetched in BULK (up to 100 per API call) instead of
# one at a time. This cuts API usage by ~100x and avoids quota exhaustion.
#
# API quota:  300 requests/day without a key (not enough)
#             10,000 requests/day with a free key
# Get your free key → https://stackapps.com/apps/oauth/register

import requests
import json
import os
import time
from bs4 import BeautifulSoup
from config import STACKOVERFLOW_KEY, RAW_STACKOVERFLOW

TAGS = [
    "amazon-web-services",
    "amazon-ecs",
    "amazon-eks",
    "aws-lambda",
    "amazon-rds",
    "amazon-dynamodb",
    "elastic-load-balancing",
    "aws-api-gateway",
    "amazon-cloudfront",
    "amazon-elasticache",
    "aws-fargate",
    "amazon-aurora",
    "amazon-sqs",
    "aws-auto-scaling",
    "amazon-vpc",
    "amazon-kinesis",
]

# Tracks remaining daily API quota — shared across all function calls
quota_remaining = 10000


def safe_get(url, params):
    """Make a GET request. Handles errors, backoff, and quota tracking.
    Returns the full parsed JSON response, or empty dict on failure.
    """
    global quota_remaining

    for attempt in range(3):
        try:
            response = requests.get(url, params=params, timeout=10)

            # Empty response — wait and retry
            if not response.content or not response.text.strip():
                time.sleep(3)
                continue

            data = response.json()

            # Read how many requests we have left today
            quota_remaining = data.get("quota_remaining", quota_remaining)

            # "backoff" means the API is asking us to slow down — must respect it
            if "backoff" in data:
                wait = int(data["backoff"]) + 1
                print(f"  API backoff: waiting {wait}s...")
                time.sleep(wait)

            # Stop early if quota is nearly gone
            if quota_remaining < 20:
                print(f"  WARNING: only {quota_remaining} API requests left today. Stopping.")
                return {}

            return data

        except Exception as e:
            print(f"  Request error (attempt {attempt + 1}/3): {e}")
            time.sleep(3)

    return {}


def clean_html(html_text):
    """Strip HTML tags from Stack Overflow question/answer body."""
    return BeautifulSoup(html_text, "html.parser").get_text()


def fetch_questions(tag, page=1):
    """Fetch one page of top-voted questions for a tag."""
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
            "min":      5,            # only questions scored 5 or higher
            "key":      STACKOVERFLOW_KEY,
        }
    )
    return data.get("items", [])


def fetch_answers_bulk(answer_ids):
    """Fetch up to 100 answers in ONE API call instead of one call per answer.

    Stack Overflow supports semicolon-separated IDs in the URL.
    Example: /answers/123;456;789 returns all three answers at once.

    Returns a dict of {answer_id: cleaned_text} for easy lookup.
    """
    if not answer_ids:
        return {}

    # Join all IDs with semicolons — Stack Overflow accepts up to 100
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
    """Collect questions + answers for one tag. Skips tags already collected."""

    output_path = os.path.join(RAW_STACKOVERFLOW, f"{tag}.json")

    # Resume support — if this tag was already collected with data, skip it
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

        # Get only the questions that have an accepted answer
        answered = [q for q in questions if q.get("accepted_answer_id")]
        ids      = [q["accepted_answer_id"] for q in answered]

        # ONE bulk call fetches all answers for this entire page
        answers = fetch_answers_bulk(ids)

        for q in answered:
            answer_text = answers.get(q["accepted_answer_id"], "")
            if not answer_text:
                continue

            collected.append({
                "source":         "stackoverflow",
                "tag":            tag,
                "question_id":    q["question_id"],
                "title":          q["title"],
                "question_text":  clean_html(q.get("body", "")),
                "question_score": q["score"],
                "answer_text":    answer_text,
                "answer_id":      q["accepted_answer_id"],
                "tags":           q.get("tags", []),
            })

        time.sleep(1)  # 1 second between pages is enough with bulk fetching

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(collected, f, indent=2)

    print(f"  Saved {len(collected)} pairs → {output_path}")
    return len(collected)


def run():
    os.makedirs(RAW_STACKOVERFLOW, exist_ok=True)
    total = 0

    for tag in TAGS:
        if quota_remaining < 20:
            print(f"\nQuota exhausted. Stopping at {total} pairs total.")
            break

        print(f"\nCollecting: {tag}")
        count  = collect_for_tag(tag, pages=3)
        total += count
        time.sleep(1)

    print(f"\nTotal Stack Overflow Q&A pairs collected: {total}")
    print(f"API quota remaining: {quota_remaining}")


if __name__ == "__main__":
    run()
