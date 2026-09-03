# pipeline/snapshot.py
#
# Architecture snapshot store.
#
# Saves pipeline recommendations to disk so the drift scanner can compare
# the current AWS state against the original recommendation without re-running
# the full pipeline.
#
# Storage: snapshots/<name>.json  (one file per named snapshot)
# Note: Railway's filesystem is ephemeral per-dyno. For long-lived snapshots
# in production, swap _store_path() to a mounted volume or S3 bucket.

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

_SNAPSHOTS_DIR = Path(os.getenv("SNAPSHOTS_DIR", "snapshots"))


def _store_path(name: str) -> Path:
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return _SNAPSHOTS_DIR / f"{safe}.json"


def save_snapshot(
    name: str,
    architecture: dict,
    query: str = "",
    requirements: dict | None = None,
    cloud_provider: str = "aws",
) -> dict:
    """Persist an architecture recommendation as a named snapshot.

    Args:
        name:          Unique name for this snapshot (e.g. "prod-ecommerce").
        architecture:  The 'architecture' dict from run_pipeline().
        query:         The original natural language query (for reference).
        requirements:  The structured requirements dict (optional).
        cloud_provider: Cloud provider slug ("aws", "azure", "gcp").

    Returns the saved snapshot dict.
    """
    snapshot = {
        "name":           name,
        "query":          query,
        "requirements":   requirements or {},
        "architecture":   architecture,
        "cloud_provider": cloud_provider,
        "saved_at":       datetime.now(timezone.utc).isoformat(),
        "saved_at_ts":    time.time(),
    }
    path = _store_path(name)
    path.write_text(json.dumps(snapshot, indent=2))
    return snapshot


def load_snapshot(name: str) -> dict | None:
    """Load a previously saved snapshot by name. Returns None if not found."""
    path = _store_path(name)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def delete_snapshot(name: str) -> bool:
    """Delete a snapshot. Returns True if it existed, False otherwise."""
    path = _store_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def list_snapshots() -> list[dict]:
    """List all saved snapshots sorted by save time (newest first)."""
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for path in _SNAPSHOTS_DIR.glob("*.json"):
        if path.name.endswith("_history.json"):
            continue  # skip drift history files
        try:
            data = json.loads(path.read_text())
            snapshots.append({
                "name":           data.get("name", path.stem),
                "query":          data.get("query", "")[:120],
                "cloud_provider": data.get("cloud_provider", "aws"),
                "saved_at":       data.get("saved_at", ""),
                "saved_at_ts":    data.get("saved_at_ts", 0),
            })
        except Exception:
            pass
    snapshots.sort(key=lambda s: s["saved_at_ts"], reverse=True)
    return snapshots
