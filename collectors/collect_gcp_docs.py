# collectors/collect_gcp_docs.py
#
# Scrapes GCP documentation pages from cloud.google.com/docs and
# cloud.google.com/architecture, then saves raw text as JSON.
#
# Same pattern as collect_aws_docs.py.

import requests
import json
import os
import time
from bs4 import BeautifulSoup
from config import RAW_GCP_DOCS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GCPDocsCollector/1.0; "
        "cloud-architect-assistant research bot)"
    )
}

# Key GCP doc pages covering compute, storage, networking, databases,
# messaging, AI/ML, security, and architecture guidance.
DOC_SECTIONS = {
    "arch_center":                "https://cloud.google.com/architecture",
    "arch_best_practices":        "https://cloud.google.com/architecture/framework",
    "arch_reliability":           "https://cloud.google.com/architecture/framework/reliability",
    "arch_security":              "https://cloud.google.com/architecture/framework/security",
    "arch_cost":                  "https://cloud.google.com/architecture/framework/cost-optimization",
    "arch_performance":           "https://cloud.google.com/architecture/framework/performance-optimization",
    "arch_microservices":         "https://cloud.google.com/architecture/microservices-architecture-on-google-kubernetes-engine",
    "arch_serverless":            "https://cloud.google.com/architecture/serverless-web-applications",
    "arch_event_driven":          "https://cloud.google.com/eventarc/docs/overview",
    "arch_multi_region":          "https://cloud.google.com/architecture/multi-region-services",

    "gke_overview":               "https://cloud.google.com/kubernetes-engine/docs/concepts/kubernetes-engine-overview",
    "gke_best_practices":         "https://cloud.google.com/kubernetes-engine/docs/best-practices/enterprise-multitenancy",
    "gke_autopilot":              "https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview",
    "gke_scaling":                "https://cloud.google.com/kubernetes-engine/docs/concepts/cluster-autoscaler",
    "cloud_run_overview":         "https://cloud.google.com/run/docs/overview/what-is-cloud-run",
    "cloud_run_concurrency":      "https://cloud.google.com/run/docs/about-concurrency",
    "cloud_run_scaling":          "https://cloud.google.com/run/docs/configuring/max-instances",
    "cloud_functions_overview":   "https://cloud.google.com/functions/docs/concepts/overview",
    "cloud_functions_2nd_gen":    "https://cloud.google.com/functions/docs/concepts/version-comparison",
    "cloud_functions_best":       "https://cloud.google.com/functions/docs/bestpractices/tips",
    "compute_engine_overview":    "https://cloud.google.com/compute/docs/overview",
    "mig_overview":               "https://cloud.google.com/compute/docs/instance-groups/creating-groups-of-managed-instances",
    "app_engine_overview":        "https://cloud.google.com/appengine/docs/an-overview-of-app-engine",
    "cloud_batch":                "https://cloud.google.com/batch/docs/get-started",

    "vpc_overview":               "https://cloud.google.com/vpc/docs/overview",
    "cloud_load_balancing":       "https://cloud.google.com/load-balancing/docs/load-balancing-overview",
    "cloud_cdn":                  "https://cloud.google.com/cdn/docs/overview",
    "cloud_armor":                "https://cloud.google.com/armor/docs/cloud-armor-overview",
    "cloud_dns":                  "https://cloud.google.com/dns/docs/overview",
    "api_gateway":                "https://cloud.google.com/api-gateway/docs/about-api-gateway",
    "cloud_endpoints":            "https://cloud.google.com/endpoints/docs/openapi/about-cloud-endpoints",
    "private_service_connect":    "https://cloud.google.com/vpc/docs/private-service-connect",

    "cloud_spanner":              "https://cloud.google.com/spanner/docs/whatis",
    "cloud_spanner_schema":       "https://cloud.google.com/spanner/docs/schema-design",
    "cloud_spanner_perf":         "https://cloud.google.com/spanner/docs/performance",
    "bigtable_overview":          "https://cloud.google.com/bigtable/docs/overview",
    "bigtable_schema":            "https://cloud.google.com/bigtable/docs/schema-design",
    "firestore_overview":         "https://cloud.google.com/firestore/docs/overview",
    "cloud_sql_overview":         "https://cloud.google.com/sql/docs/mysql/introduction",
    "cloud_sql_ha":               "https://cloud.google.com/sql/docs/mysql/high-availability",
    "alloydb_overview":           "https://cloud.google.com/alloydb/docs/overview",
    "memorystore_redis":          "https://cloud.google.com/memorystore/docs/redis/redis-overview",

    "pubsub_overview":            "https://cloud.google.com/pubsub/docs/overview",
    "pubsub_ordering":            "https://cloud.google.com/pubsub/docs/ordering",
    "pubsub_replay":              "https://cloud.google.com/pubsub/docs/replay-overview",
    "dataflow_overview":          "https://cloud.google.com/dataflow/docs/overview",
    "cloud_tasks":                "https://cloud.google.com/tasks/docs/overview",

    "gcs_overview":               "https://cloud.google.com/storage/docs/introduction",
    "gcs_storage_classes":        "https://cloud.google.com/storage/docs/storage-classes",
    "filestore_overview":         "https://cloud.google.com/filestore/docs/overview",

    "iam_overview":               "https://cloud.google.com/iam/docs/overview",
    "iam_best_practices":         "https://cloud.google.com/iam/docs/using-iam-securely",
    "secret_manager":             "https://cloud.google.com/secret-manager/docs/overview",
    "security_command_center":    "https://cloud.google.com/security-command-center/docs/concepts-security-command-center-overview",
    "workload_identity":          "https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity",
    "chronicle_siem":             "https://cloud.google.com/chronicle/docs/overview",

    "cloud_monitoring":           "https://cloud.google.com/monitoring/docs/overview",
    "cloud_logging":              "https://cloud.google.com/logging/docs/overview",
    "cloud_trace":                "https://cloud.google.com/trace/docs/overview",
    "cloud_profiler":             "https://cloud.google.com/profiler/docs/about-profiler",
    "error_reporting":            "https://cloud.google.com/error-reporting/docs/overview",

    "vertex_ai_overview":         "https://cloud.google.com/vertex-ai/docs/start/introduction-unified-platform",
    "vertex_prediction":          "https://cloud.google.com/vertex-ai/docs/predictions/overview",
    "gemini_overview":            "https://cloud.google.com/vertex-ai/docs/generative-ai/learn/overview",

    "bigquery_overview":          "https://cloud.google.com/bigquery/docs/introduction",
    "bigquery_best_practices":    "https://cloud.google.com/bigquery/docs/best-practices-performance-overview",
    "bigquery_storage":           "https://cloud.google.com/bigquery/docs/storage_overview",
    "dataproc_overview":          "https://cloud.google.com/dataproc/docs/concepts/overview",
}

CONTENT_SELECTORS = [
    "article",
    "div.devsite-article-body",
    "main",
    "div#main-content",
    "div[role='main']",
]


def extract_text(html: str) -> str:
    """Extract clean text from a GCP docs HTML page."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["nav", "footer", "aside", "script", "style",
                               "header", "form", "devsite-nav"]):
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


def fetch_section(name: str, url: str) -> dict | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code} — skipping {name}")
            return None

        text = extract_text(resp.text)
        if len(text) < 200:
            print(f"  Too short ({len(text)} chars) — skipping {name}")
            return None

        return {"url": url, "section": name, "text": text}

    except Exception as e:
        print(f"  Error fetching {name}: {e}")
        return None


def run():
    os.makedirs(RAW_GCP_DOCS, exist_ok=True)
    total = 0

    for name, url in DOC_SECTIONS.items():
        output_path = os.path.join(RAW_GCP_DOCS, f"{name}.json")

        if os.path.exists(output_path):
            print(f"[skip] {name} — already collected")
            total += 1
            continue

        print(f"[fetch] {name}")
        record = fetch_section(name, url)

        if record:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
            print(f"  Saved {len(record['text'])} chars → {output_path}")
            total += 1
        else:
            print(f"  Failed — {name}")

        time.sleep(1.5)

    print(f"\nDone. {total}/{len(DOC_SECTIONS)} sections collected.")


if __name__ == "__main__":
    run()
