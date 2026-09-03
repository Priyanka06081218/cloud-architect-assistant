FROM python:3.11-slim

# System dependencies needed by sentence-transformers and chromadb
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer if requirements unchanged)
COPY requirements.txt .
# Cache bust: increment when adding new packages that Docker caches incorrectly
ARG CACHE_BUST=5
# Install langfuse explicitly first so it's never silently skipped by layer cache
# Pin to <3.0.0: v3+ removed langfuse.decorators entirely (breaking change)
RUN pip install --no-cache-dir "langfuse>=2.24.0,<3.0.0"
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY config.py        ./config.py
COPY pipeline/        ./pipeline/
COPY app/main.py          ./app/main.py
COPY app/metrics_pusher.py ./app/metrics_pusher.py
RUN touch ./app/__init__.py

# Copy the ChromaDB vector store (pre-built during data processing)
COPY data/chromadb/   ./data/chromadb/

# Patch chromadb config_json_str — 0.5.15 crashes on empty '{}' due to missing _type key.
COPY scripts/patch_chromadb.py ./scripts/patch_chromadb.py
RUN python3 scripts/patch_chromadb.py

# Non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
