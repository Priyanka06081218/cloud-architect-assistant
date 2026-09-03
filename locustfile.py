# locustfile.py
#
# Load test for the Cloud Architecture Assistant API.
#
# Usage (local or against Railway):
#
#   pip install locust
#
#   # Interactive web UI at http://localhost:8089
#   locust -f locustfile.py --host https://cloud-assistant-architect-production.up.railway.app
#
#   # Headless benchmark — 20 concurrent users, 60-second ramp, 120-second run
#   locust -f locustfile.py \
#     --host https://cloud-assistant-architect-production.up.railway.app \
#     --headless -u 20 -r 5 -t 120s \
#     --csv results/benchmark

from locust import HttpUser, task, between, events
import json
import time

# ---------------------------------------------------------------------------
# Scenario queries — varied enough to test both cache hits and misses
# ---------------------------------------------------------------------------

# These will almost certainly be cache MISSES on the first run (cold start)
COLD_QUERIES = [
    "Design an AWS architecture for a real-time analytics platform ingesting 1M events/day",
    "Build a HIPAA-compliant telemedicine platform with video calls and EHR integration",
    "Design a multi-tenant SaaS backend on AWS with per-customer isolation and 99.9% SLA",
    "Create a CI/CD pipeline for a microservices app with 15 services and blue/green deploys",
    "Design a global e-commerce platform for 500k concurrent Black Friday users",
]

# After the first pass, subsequent similar queries should be cache HITS (similarity >= 0.92)
WARM_QUERIES = [
    "Real-time analytics AWS architecture handling 1 million daily events",
    "HIPAA telemedicine app with video conferencing and medical records on AWS",
    "Multi-tenant SaaS on AWS with tenant isolation and high availability",
    "CI/CD pipeline for microservices with blue-green deployment strategy",
    "E-commerce platform AWS design for high concurrency during Black Friday sales",
]


# ---------------------------------------------------------------------------
# User behavior
# ---------------------------------------------------------------------------

class ArchitectureUser(HttpUser):
    """Simulates a recruiter or developer using the API."""
    wait_time = between(2, 8)   # think time between requests

    @task(1)
    def health_check(self):
        """Lightweight health probe — sanity-checks the API is up."""
        with self.client.get("/health", catch_response=True) as resp:
            if resp.status_code == 200:
                body = resp.json()
                if body.get("status") != "healthy":
                    resp.failure(f"Unexpected health status: {body}")
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    @task(3)
    def analyze_cold(self):
        """POST /analyze with a query unlikely to be in the semantic cache."""
        import random
        query = random.choice(COLD_QUERIES)
        payload = {"query": query}
        with self.client.post(
            "/analyze",
            json=payload,
            catch_response=True,
            timeout=300,         # pipeline can take 2–3 min on first run
            name="/analyze [cold]",
        ) as resp:
            if resp.status_code == 200:
                body = resp.json()
                cached = body.get("cached", False)
                elapsed = body.get("elapsed_seconds", 0)
                if "architecture" not in body:
                    resp.failure("Response missing 'architecture' field")
                else:
                    resp.success()
                    # Tag for Locust's custom stats
                    self.environment.events.request.fire(
                        request_type="CACHE",
                        name="hit" if cached else "miss",
                        response_time=elapsed * 1000,
                        response_length=len(resp.content),
                        exception=None,
                        context={},
                    )
            elif resp.status_code == 500:
                resp.failure(f"Pipeline error: {resp.text[:200]}")
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")

    @task(5)
    def analyze_warm(self):
        """POST /analyze with queries semantically similar to already-cached ones.
        These should return 'cached: true' with near-zero latency.
        """
        import random
        query = random.choice(WARM_QUERIES)
        payload = {"query": query}
        start = time.time()
        with self.client.post(
            "/analyze",
            json=payload,
            catch_response=True,
            timeout=300,
            name="/analyze [warm]",
        ) as resp:
            if resp.status_code == 200:
                body = resp.json()
                cached = body.get("cached", False)
                elapsed = body.get("elapsed_seconds", 0)
                if "architecture" not in body:
                    resp.failure("Response missing 'architecture' field")
                elif not cached:
                    # Not a failure, but worth logging — cache may still be warming up
                    resp.success()
                else:
                    resp.success()
            else:
                resp.failure(f"Unexpected status: {resp.status_code}")


# ---------------------------------------------------------------------------
# Summary reporter — prints cache hit/miss ratio at end of run
# ---------------------------------------------------------------------------

_cache_hits = 0
_cache_misses = 0


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, context, **kwargs):
    global _cache_hits, _cache_misses
    if request_type == "CACHE":
        if name == "hit":
            _cache_hits += 1
        elif name == "miss":
            _cache_misses += 1


@events.quitting.add_listener
def on_quit(environment, **kwargs):
    total = _cache_hits + _cache_misses
    hit_rate = (_cache_hits / total * 100) if total else 0
    print(f"\n{'='*60}")
    print(f"  Semantic Cache Summary")
    print(f"  Cache hits:   {_cache_hits:>5}  ({hit_rate:.1f}%)")
    print(f"  Cache misses: {_cache_misses:>5}  ({100-hit_rate:.1f}%)")
    print(f"  Total:        {total:>5}")
    print(f"{'='*60}\n")
