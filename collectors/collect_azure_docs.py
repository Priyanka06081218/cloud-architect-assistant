# collectors/collect_azure_docs.py
#
# Scrapes Azure documentation pages from learn.microsoft.com and the
# Azure Architecture Center, then saves raw text as JSON.
#
# Same pattern as collect_aws_docs.py — reads each URL, extracts the
# main content div, cleans text, and writes one JSON file per section.

import requests
import json
import os
import time
from bs4 import BeautifulSoup
from config import RAW_AZURE_DOCS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AzureDocsCollector/1.0; "
        "cloud-architect-assistant research bot)"
    )
}

# Key Azure doc pages covering compute, storage, networking, databases,
# messaging, AI/ML, security, and well-architected guidance.
DOC_SECTIONS = {
    # ── Well-Architected Framework ──────────────────────────────────────────
    "waf_overview":           "https://learn.microsoft.com/en-us/azure/well-architected/",
    "waf_reliability":        "https://learn.microsoft.com/en-us/azure/well-architected/reliability/overview",
    "waf_security":           "https://learn.microsoft.com/en-us/azure/well-architected/security/overview",
    "waf_cost":               "https://learn.microsoft.com/en-us/azure/well-architected/cost-optimization/overview",
    "waf_performance":        "https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency/overview",
    "waf_operational":        "https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence/overview",

    # ── Architecture Center ─────────────────────────────────────────────────
    "arch_microservices":     "https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/microservices",
    "arch_event_driven":      "https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/event-driven",
    "arch_serverless":        "https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/serverless",
    "arch_cqrs":              "https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs",
    "arch_saga":              "https://learn.microsoft.com/en-us/azure/architecture/reference-architectures/saga/saga",
    "arch_high_avail":        "https://learn.microsoft.com/en-us/azure/architecture/framework/resiliency/app-design",
    "arch_multi_region":      "https://learn.microsoft.com/en-us/azure/architecture/reference-architectures/app-service-web-app/multi-region",

    # ── Compute ─────────────────────────────────────────────────────────────
    "aks_overview":           "https://learn.microsoft.com/en-us/azure/aks/intro-kubernetes",
    "aks_best_practices":     "https://learn.microsoft.com/en-us/azure/aks/best-practices",
    "aks_cluster_config":     "https://learn.microsoft.com/en-us/azure/aks/cluster-configuration",
    "aks_scaling":            "https://learn.microsoft.com/en-us/azure/aks/cluster-autoscaler",
    "azure_functions":        "https://learn.microsoft.com/en-us/azure/azure-functions/functions-overview",
    "azure_functions_scale":  "https://learn.microsoft.com/en-us/azure/azure-functions/functions-scale",
    "azure_functions_best":   "https://learn.microsoft.com/en-us/azure/azure-functions/functions-best-practices",
    "aca_overview":           "https://learn.microsoft.com/en-us/azure/container-apps/overview",
    "aca_scaling":            "https://learn.microsoft.com/en-us/azure/container-apps/scale-app",
    "app_service_overview":   "https://learn.microsoft.com/en-us/azure/app-service/overview",
    "app_service_scale":      "https://learn.microsoft.com/en-us/azure/app-service/manage-scale-up",
    "vmss_overview":          "https://learn.microsoft.com/en-us/azure/virtual-machine-scale-sets/overview",
    "batch_overview":         "https://learn.microsoft.com/en-us/azure/batch/batch-technical-overview",

    # ── Networking ──────────────────────────────────────────────────────────
    "vnet_overview":          "https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-overview",
    "app_gateway":            "https://learn.microsoft.com/en-us/azure/application-gateway/overview",
    "front_door":             "https://learn.microsoft.com/en-us/azure/frontdoor/front-door-overview",
    "cdn_overview":           "https://learn.microsoft.com/en-us/azure/cdn/cdn-overview",
    "lb_overview":            "https://learn.microsoft.com/en-us/azure/load-balancer/load-balancer-overview",
    "api_management":         "https://learn.microsoft.com/en-us/azure/api-management/api-management-key-concepts",
    "api_management_best":    "https://learn.microsoft.com/en-us/azure/api-management/api-management-policies",
    "private_link":           "https://learn.microsoft.com/en-us/azure/private-link/private-link-overview",

    # ── Databases ───────────────────────────────────────────────────────────
    "cosmos_overview":        "https://learn.microsoft.com/en-us/azure/cosmos-db/introduction",
    "cosmos_partitioning":    "https://learn.microsoft.com/en-us/azure/cosmos-db/partitioning-overview",
    "cosmos_consistency":     "https://learn.microsoft.com/en-us/azure/cosmos-db/consistency-levels",
    "cosmos_global_dist":     "https://learn.microsoft.com/en-us/azure/cosmos-db/distribute-data-globally",
    "sql_managed":            "https://learn.microsoft.com/en-us/azure/azure-sql/managed-instance/sql-managed-instance-paas-overview",
    "sql_hyperscale":         "https://learn.microsoft.com/en-us/azure/azure-sql/database/service-tier-hyperscale",
    "sql_ha":                 "https://learn.microsoft.com/en-us/azure/azure-sql/database/high-availability-sla",
    "postgres_flexible":      "https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/overview",
    "redis_cache":            "https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-overview",
    "redis_best":             "https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-best-practices-development",

    # ── Messaging & Streaming ───────────────────────────────────────────────
    "service_bus":            "https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-messaging-overview",
    "service_bus_best":       "https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-performance-improvements",
    "event_hub":              "https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-about",
    "event_hub_partitions":   "https://learn.microsoft.com/en-us/azure/event-hubs/event-hubs-scalability",
    "event_grid":             "https://learn.microsoft.com/en-us/azure/event-grid/overview",
    "storage_queue":          "https://learn.microsoft.com/en-us/azure/storage/queues/storage-queues-introduction",

    # ── Storage ─────────────────────────────────────────────────────────────
    "blob_storage":           "https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blobs-introduction",
    "blob_tiers":             "https://learn.microsoft.com/en-us/azure/storage/blobs/access-tiers-overview",
    "adls_gen2":              "https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-introduction",

    # ── Security & Identity ─────────────────────────────────────────────────
    "entra_id":               "https://learn.microsoft.com/en-us/entra/identity/",
    "key_vault":              "https://learn.microsoft.com/en-us/azure/key-vault/general/overview",
    "defender_cloud":         "https://learn.microsoft.com/en-us/azure/defender-for-cloud/defender-for-cloud-introduction",
    "sentinel":               "https://learn.microsoft.com/en-us/azure/sentinel/overview",
    "ddos_protection":        "https://learn.microsoft.com/en-us/azure/ddos-protection/ddos-protection-overview",
    "managed_identity":       "https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/overview",

    # ── Monitoring ──────────────────────────────────────────────────────────
    "monitor_overview":       "https://learn.microsoft.com/en-us/azure/azure-monitor/overview",
    "app_insights":           "https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview",
    "log_analytics":          "https://learn.microsoft.com/en-us/azure/azure-monitor/logs/log-analytics-overview",

    # ── AI / ML ─────────────────────────────────────────────────────────────
    "openai_service":         "https://learn.microsoft.com/en-us/azure/ai-services/openai/overview",
    "ml_overview":            "https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning",
    "cognitive_search":       "https://learn.microsoft.com/en-us/azure/search/search-what-is-azure-search",

    # ── Data & Analytics ────────────────────────────────────────────────────
    "synapse":                "https://learn.microsoft.com/en-us/azure/synapse-analytics/overview-what-is",
    "data_factory":           "https://learn.microsoft.com/en-us/azure/data-factory/introduction",
    "databricks":             "https://learn.microsoft.com/en-us/azure/databricks/introduction/",
}

# CSS selectors tried in order to find main content
CONTENT_SELECTORS = [
    "div#main-content",
    "main",
    "article",
    "div.content",
    "div[role='main']",
]


def extract_text(html: str) -> str:
    """Extract clean text from an Azure docs HTML page."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove nav, footer, sidebars, cookie banners
    for tag in soup.find_all(["nav", "footer", "aside", "script", "style",
                               "header", "form"]):
        tag.decompose()

    for selector in CONTENT_SELECTORS:
        tag, attr = (selector.split("[", 1)[0], None) if "[" not in selector else (selector.split("[")[0], selector)
        if selector.startswith("div#"):
            node = soup.find("div", id=selector[len("div#"):])
        elif selector.startswith("div."):
            node = soup.find("div", class_=selector[len("div."):])
        elif "[" in selector:
            # e.g. div[role='main']
            node = soup.find("div", attrs={"role": "main"})
        else:
            node = soup.find(selector)
        if node:
            return node.get_text(separator="\n", strip=True)

    # Fallback: all body text
    body = soup.find("body")
    return body.get_text(separator="\n", strip=True) if body else ""


def fetch_section(name: str, url: str) -> dict | None:
    """Fetch one doc section and return a record dict, or None on failure."""
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
    os.makedirs(RAW_AZURE_DOCS, exist_ok=True)
    total = 0

    for name, url in DOC_SECTIONS.items():
        output_path = os.path.join(RAW_AZURE_DOCS, f"{name}.json")

        # Resume: skip if already collected
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

        time.sleep(1.5)  # polite rate limit

    print(f"\nDone. {total}/{len(DOC_SECTIONS)} sections collected.")


if __name__ == "__main__":
    run()
