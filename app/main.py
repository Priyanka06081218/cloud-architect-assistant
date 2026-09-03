# app/main.py
#
# FastAPI backend — wraps the RAG pipeline into HTTP endpoints.
#
# Endpoints:
#   GET  /           → API info
#   GET  /health     → health check (used by Kubernetes liveness probes)
#   POST /analyze    → main endpoint, takes a query, returns full architecture response

import os
import json
import time
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import threading

from pipeline.pipeline import run_pipeline
from pipeline.agents import run_debate
from pipeline.drift_detector import scan_and_compare
from pipeline.snapshot import save_snapshot, load_snapshot, list_snapshots, delete_snapshot
from pipeline.drift_scheduler import (
    DriftScheduleConfig, start_scheduler, stop_scheduler,
    register_schedule, list_schedules, remove_schedule, get_drift_history,
)
from pipeline.cache import cache_get, cache_set, cache_flush
from pipeline.observability import log_langfuse_status

#  Logging 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

#  App setup 

from prometheus_client import (
    Counter, Histogram, CollectorRegistry,
    generate_latest, CONTENT_TYPE_LATEST,
)
from fastapi.responses import Response

# ── Custom metrics registry ───────────────────────────────────────────────────
# Use a dedicated registry to avoid interference from any installed middleware.
METRICS_REGISTRY = CollectorRegistry(auto_describe=True)

pipeline_requests_total = Counter(
    "cloud_architect_requests_total",
    "Total /analyze requests",
    ["cloud_provider", "cached"],
    registry=METRICS_REGISTRY,
)
pipeline_duration_seconds = Histogram(
    "cloud_architect_pipeline_duration_seconds",
    "Full pipeline wall-clock time (seconds)",
    ["cloud_provider"],
    buckets=[5, 10, 20, 30, 60, 90, 120, 180],
    registry=METRICS_REGISTRY,
)
cost_estimate_dollars = Histogram(
    "cloud_architect_cost_estimate_dollars",
    "Monthly cost estimate returned (USD)",
    ["cloud_provider"],
    buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000],
    registry=METRICS_REGISTRY,
)
cache_hits_total   = Counter("cloud_architect_cache_hits_total",   "Semantic cache hits",  registry=METRICS_REGISTRY)
cache_misses_total = Counter("cloud_architect_cache_misses_total",  "Semantic cache misses", registry=METRICS_REGISTRY)
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Cloud Architecture Assistant",
    description="AI-powered AWS architecture recommendations with cost estimation",
    version="1.0.0",
)


@app.get("/metrics", include_in_schema=False)
def metrics():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(METRICS_REGISTRY), media_type=CONTENT_TYPE_LATEST)

# Allow the React frontend to call this API
# In production, replace "*" with your actual frontend domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

#  Cache — Redis if available, in-memory fallback 
# When REDIS_URL env var is set (Docker / EKS), uses Redis for distributed cache.
# Falls back to a simple in-memory dict for local development.

CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours
_redis_client = None
_mem_cache: dict = {}


def _init_redis():
    global _redis_client
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return
    try:
        import redis
        _redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        _redis_client.ping()
        log.info(f"Redis cache connected: {redis_url}")
    except Exception as e:
        log.warning(f"Redis unavailable ({e}), falling back to in-memory cache")
        _redis_client = None


def get_cached(query: str):
    if _redis_client:
        try:
            value = _redis_client.get(f"arch:{query}")
            if value:
                return json.loads(value)
        except Exception as e:
            log.warning(f"Redis get failed: {e}")
    # In-memory fallback
    if query in _mem_cache:
        response, cached_at = _mem_cache[query]
        if time.time() - cached_at < CACHE_TTL_SECONDS:
            return response
    return None


def set_cache(query: str, response: dict):
    if _redis_client:
        try:
            _redis_client.setex(f"arch:{query}", CACHE_TTL_SECONDS, json.dumps(response))
            return
        except Exception as e:
            log.warning(f"Redis set failed: {e}")
    _mem_cache[query] = (response, time.time())


#  Grafana Cloud remote_write 

GRAFANA_REMOTE_WRITE_URL   = os.getenv("GRAFANA_REMOTE_WRITE_URL", "")
GRAFANA_REMOTE_WRITE_USER  = os.getenv("GRAFANA_REMOTE_WRITE_USER", "")
GRAFANA_REMOTE_WRITE_TOKEN = os.getenv("GRAFANA_REMOTE_WRITE_TOKEN", "")
METRICS_PUSH_INTERVAL = 15  # seconds


def _push_metrics_loop():
    """Background thread: push Prometheus metrics to Grafana Cloud every 15s."""
    if not GRAFANA_REMOTE_WRITE_URL:
        return
    from app.metrics_pusher import push_metrics
    import time as _time

    log.info(f"Grafana metrics push started → {GRAFANA_REMOTE_WRITE_URL}")
    while True:
        try:
            push_metrics(
                METRICS_REGISTRY.collect(),
                url=GRAFANA_REMOTE_WRITE_URL,
                username=GRAFANA_REMOTE_WRITE_USER,
                token=GRAFANA_REMOTE_WRITE_TOKEN,
            )
        except Exception as e:
            log.warning(f"Grafana metrics push failed: {e}")
        _time.sleep(METRICS_PUSH_INTERVAL)


# Initialize Redis on startup (no-op if REDIS_URL not set)
@app.on_event("startup")
async def startup():
    log_langfuse_status()
    _init_redis()
    start_scheduler()
    if GRAFANA_REMOTE_WRITE_URL:
        t = threading.Thread(target=_push_metrics_loop, daemon=True)
        t.start()


@app.on_event("shutdown")
async def shutdown():
    stop_scheduler()


#  Request / Response models 

class AnalyzeRequest(BaseModel):
    query: str

    class Config:
        json_schema_extra = {
            "example": {
                "query": "Design an AWS architecture for an e-commerce app expecting 100k concurrent users during Black Friday."
            }
        }


class DriftRequest(BaseModel):
    architecture: dict           # the 'architecture' key from /analyze response
    aws_access_key_id: str
    aws_secret_access_key: str
    region: str = "us-east-1"

    class Config:
        json_schema_extra = {
            "example": {
                "architecture": {"layers": {"compute": ["Amazon ECS"], "database": ["Amazon RDS"]}},
                "aws_access_key_id": "AKIA...",
                "aws_secret_access_key": "...",
                "region": "us-east-1",
            }
        }


class SnapshotSaveRequest(BaseModel):
    name: str
    architecture: dict
    query: str = ""
    requirements: dict = {}
    cloud_provider: str = "aws"

    class Config:
        json_schema_extra = {
            "example": {
                "name": "prod-ecommerce",
                "architecture": {"layers": {"compute": ["Amazon ECS"]}},
                "query": "E-commerce platform with 100k concurrent users",
                "cloud_provider": "aws",
            }
        }


class DriftScheduleRequest(BaseModel):
    name: str
    snapshot_name: str
    aws_access_key_id: str
    aws_secret_access_key: str
    region: str = "us-east-1"
    interval_minutes: int = 60
    alert_threshold: int = 60
    alert_webhook_url: str = ""

    class Config:
        json_schema_extra = {
            "example": {
                "name": "prod-ecommerce-hourly",
                "snapshot_name": "prod-ecommerce",
                "aws_access_key_id": "AKIA...",
                "aws_secret_access_key": "...",
                "interval_minutes": 60,
                "alert_threshold": 60,
                "alert_webhook_url": "https://hooks.slack.com/services/...",
            }
        }


class HealthResponse(BaseModel):
    status: str
    cache_size: int
    cache_backend: str


#  Endpoints 

@app.get("/")
def root():
    """API info endpoint."""
    return {
        "name":        "Cloud Architecture Assistant",
        "version":     "1.0.0",
        "description": "AI-powered AWS architecture recommendations with cost estimation",
        "endpoints": {
            "POST /analyze":        "Generate architecture recommendation for a given scenario",
            "POST /analyze/debate": "Multi-agent debate: Cost vs Reliability vs Security agents",
            "POST /drift":          "Compare recommended architecture against real AWS account",
            "GET  /health":         "Health check",
        }
    }


@app.get("/health", response_model=HealthResponse)
def health():
    """Health check — returns 200 if the API is running.
    Used by Kubernetes liveness and readiness probes.
    """
    cache_size = 0
    if _redis_client:
        try:
            cache_size = _redis_client.dbsize()
        except Exception:
            pass
    else:
        cache_size = len(_mem_cache)

    return {
        "status":        "healthy",
        "cache_size":    cache_size,
        "cache_backend": "redis" if _redis_client else "memory",
    }


@app.delete("/admin/cache")
def flush_cache():
    """Flush the Upstash Vector semantic cache.

    Use this after a major pipeline update (e.g. adding multi-cloud support)
    to ensure stale cached results are not returned for new queries.
    """
    deleted = cache_flush()
    # Also clear in-memory fallback cache
    _mem_cache.clear()
    return {"flushed": True, "deleted_vectors": deleted}


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    """Main endpoint — runs the full RAG pipeline for a cloud architecture query.

    Takes a natural language scenario and returns:
    - Architecture recommendation (which AWS services to use)
    - Service trade-off reasoning (why these services, not alternatives)
    - Monthly cost breakdown
    - Terraform HCL code
    - Mermaid architecture diagram

    Responses are cached for 24 hours — identical queries return instantly.
    """

    query = request.query.strip()

    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    if len(query) < 10:
        raise HTTPException(status_code=400, detail="Query too short. Describe your architecture scenario.")

    # Semantic cache check (Upstash Vector, similarity >= 0.92)
    cached = cache_get(query)
    if cached:
        log.info(f"Semantic cache hit for: {query[:60]}...")
        cloud = cached.get("cloud_provider", "aws").lower()
        cache_hits_total.inc()
        pipeline_requests_total.labels(cloud_provider=cloud, cached="true").inc()
        return {**cached, "cached": True, "elapsed_seconds": 0}

    # Run the full pipeline
    log.info(f"Running pipeline for: {query[:60]}...")
    cache_misses_total.inc()
    start = time.time()

    try:
        response = run_pipeline(query)
    except Exception as e:
        log.error(f"Pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")

    elapsed = round(time.time() - start, 2)
    log.info(f"Pipeline completed in {elapsed}s")

    # Record business metrics
    cloud = response.get("cloud_provider", "aws").lower()
    pipeline_requests_total.labels(cloud_provider=cloud, cached="false").inc()
    pipeline_duration_seconds.labels(cloud_provider=cloud).observe(elapsed)
    cost = response.get("cost_estimate", {}).get("total_monthly_usd", 0) or 0
    if cost > 0:
        cost_estimate_dollars.labels(cloud_provider=cloud).observe(cost)

    # Store in semantic cache
    cache_set(query, response)

    return {**response, "cached": False, "elapsed_seconds": elapsed}


@app.post("/analyze/debate")
def analyze_debate(request: AnalyzeRequest):
    """Multi-agent debate endpoint — runs Cost, Reliability, and Security agents in parallel,
    then a Moderator agent synthesizes a final balanced recommendation.

    Returns all three specialist proposals plus the moderated synthesis with
    a per-topic debate summary and influence scores.

    Responses are cached for 24 hours.
    """
    query = request.query.strip()

    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    if len(query) < 10:
        raise HTTPException(status_code=400, detail="Query too short. Describe your architecture scenario.")

    cache_key = f"debate:{query}"

    # Check cache
    if _redis_client:
        try:
            value = _redis_client.get(cache_key)
            if value:
                return {**json.loads(value), "cached": True}
        except Exception:
            pass
    elif cache_key in _mem_cache:
        response, cached_at = _mem_cache[cache_key]
        if time.time() - cached_at < CACHE_TTL_SECONDS:
            return {**response, "cached": True}

    log.info(f"Running debate for: {query[:60]}...")
    start = time.time()

    try:
        result = run_debate(query)
    except Exception as e:
        log.error(f"Debate failed: {e}")
        raise HTTPException(status_code=500, detail=f"Debate error: {str(e)}")

    elapsed = round(time.time() - start, 2)
    log.info(f"Debate completed in {elapsed}s")

    # Cache it
    if _redis_client:
        try:
            _redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(result))
        except Exception:
            pass
    else:
        _mem_cache[cache_key] = (result, time.time())

    return {**result, "cached": False, "elapsed_seconds": elapsed}


@app.post("/drift")
def drift(request: DriftRequest):
    """Architecture drift detection — scans a real AWS account and compares what's
    deployed against the recommended architecture from /analyze.

    Returns:
    - snapshot: what was found in the AWS account (per service)
    - findings: list of drift items (missing services, misconfigurations)
    - score: overall health score 0–100 with grade (A–F) and severity counts

    Credentials are used only for the boto3 scan (read-only) and never stored.
    """
    if not request.aws_access_key_id or not request.aws_secret_access_key:
        raise HTTPException(status_code=400, detail="AWS credentials are required.")

    if not request.architecture:
        raise HTTPException(status_code=400, detail="Architecture dict is required.")

    log.info(f"Running drift scan in {request.region}...")
    start = time.time()

    try:
        report = scan_and_compare(
            recommended=request.architecture,
            aws_access_key_id=request.aws_access_key_id,
            aws_secret_access_key=request.aws_secret_access_key,
            region=request.region,
        )
    except Exception as e:
        log.error(f"Drift scan failed: {e}")
        raise HTTPException(status_code=500, detail=f"Drift scan error: {str(e)}")

    elapsed = round(time.time() - start, 2)
    log.info(f"Drift scan complete in {elapsed}s — score: {report['score']['score']}")

    return {**report, "elapsed_seconds": elapsed}


# ─── Drift governance endpoints ──────────────────────────────────────────────

@app.post("/drift/snapshot")
def drift_snapshot_save(request: SnapshotSaveRequest):
    """Save an architecture recommendation as a named snapshot.

    Snapshots are the baseline the drift scanner compares against.
    Typically called right after /analyze with the architecture from the response.
    """
    if not request.name:
        raise HTTPException(status_code=400, detail="Snapshot name is required.")
    if not request.architecture:
        raise HTTPException(status_code=400, detail="Architecture dict is required.")

    snapshot = save_snapshot(
        name=request.name,
        architecture=request.architecture,
        query=request.query,
        requirements=request.requirements,
        cloud_provider=request.cloud_provider,
    )
    log.info(f"Snapshot saved: '{request.name}'")
    return {"status": "saved", "snapshot": {k: v for k, v in snapshot.items() if k != "architecture"}}


@app.get("/drift/snapshots")
def drift_snapshots_list():
    """List all saved architecture snapshots."""
    return {"snapshots": list_snapshots()}


@app.delete("/drift/snapshot/{name}")
def drift_snapshot_delete(name: str):
    """Delete a named snapshot."""
    deleted = delete_snapshot(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Snapshot '{name}' not found.")
    return {"status": "deleted", "name": name}


@app.post("/drift/schedule")
def drift_schedule_create(request: DriftScheduleRequest):
    """Register a periodic drift scan against a saved snapshot.

    The scan runs immediately on registration and then on the configured interval.
    An alert is POSTed to alert_webhook_url if the drift score drops below alert_threshold.
    """
    if not request.snapshot_name:
        raise HTTPException(status_code=400, detail="snapshot_name is required.")

    snapshot = load_snapshot(request.snapshot_name)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot '{request.snapshot_name}' not found. Save one first via POST /drift/snapshot."
        )

    config = DriftScheduleConfig(
        name=request.name,
        snapshot_name=request.snapshot_name,
        aws_access_key_id=request.aws_access_key_id,
        aws_secret_access_key=request.aws_secret_access_key,
        region=request.region,
        interval_minutes=request.interval_minutes,
        alert_threshold=request.alert_threshold,
        alert_webhook_url=request.alert_webhook_url,
    )
    result = register_schedule(config)
    log.info(f"Drift schedule registered: '{request.name}'")
    return result


@app.get("/drift/schedules")
def drift_schedules_list():
    """List all registered drift schedules."""
    return {"schedules": list_schedules()}


@app.delete("/drift/schedule/{name}")
def drift_schedule_delete(name: str):
    """Remove a drift schedule."""
    removed = remove_schedule(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Schedule '{name}' not found.")
    return {"status": "removed", "name": name}


@app.get("/drift/history/{name}")
def drift_history(name: str):
    """Return the drift score history for a named schedule (newest first, up to 200 entries)."""
    history = get_drift_history(name)
    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"No history found for schedule '{name}'. Run a drift scan first."
        )
    latest = history[0] if history else None
    return {
        "name":    name,
        "count":   len(history),
        "latest":  latest,
        "history": history,
    }


#  Run

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
