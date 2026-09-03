# pipeline/drift_scheduler.py
#
# Continuous drift governance — scheduled scanning with history and alerts.
#
# How it works:
#   1. You register a DriftSchedule: which snapshot to compare against,
#      how often to scan, what AWS credentials to use, and where to alert.
#   2. APScheduler runs the scan in the background on the configured interval.
#   3. Each scan result is appended to a per-schedule history file.
#   4. If the drift score drops below alert_threshold, a Slack-compatible
#      webhook POST is fired.
#
# Usage:
#   from pipeline.drift_scheduler import DriftScheduleConfig, start_scheduler
#   start_scheduler()   # call once at app startup
#   register_schedule(DriftScheduleConfig(...))

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_SNAPSHOTS_DIR  = Path(os.getenv("SNAPSHOTS_DIR", "snapshots"))
_scheduler      = None   # APScheduler BackgroundScheduler (lazy init)
_registered: dict[str, "DriftScheduleConfig"] = {}


# ─── Config dataclass ────────────────────────────────────────────────────────

@dataclass
class DriftScheduleConfig:
    """Configuration for a periodic drift scan.

    Fields:
        name:                Unique name for this schedule (matches a snapshot name).
        snapshot_name:       Which snapshot to compare the live account against.
        aws_access_key_id:   AWS access key for the scan (read-only IAM recommended).
        aws_secret_access_key: AWS secret key.
        region:              AWS region to scan (default: us-east-1).
        interval_minutes:    How often to scan (default: 60).
        alert_threshold:     Drift score below which an alert fires (default: 60).
        alert_webhook_url:   Slack-compatible webhook URL for alerts (optional).
        enabled:             Whether the schedule is active (default: True).
    """
    name:                    str
    snapshot_name:           str
    aws_access_key_id:       str
    aws_secret_access_key:   str
    region:                  str   = "us-east-1"
    interval_minutes:        int   = 60
    alert_threshold:         int   = 60
    alert_webhook_url:       str   = ""
    enabled:                 bool  = True


# ─── History store ───────────────────────────────────────────────────────────

def _history_path(name: str) -> Path:
    _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return _SNAPSHOTS_DIR / f"{safe}_history.json"


def _append_history(name: str, scan_result: dict) -> None:
    path = _history_path(name)
    history = []
    if path.exists():
        try:
            history = json.loads(path.read_text())
        except Exception:
            pass

    history.append({
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "timestamp_ts":   time.time(),
        "score":          scan_result["score"]["score"],
        "grade":          scan_result["score"]["grade"],
        "label":          scan_result["score"]["label"],
        "findings_total": scan_result["score"]["total"],
        "counts":         scan_result["score"]["counts"],
        "region":         scan_result.get("region", ""),
    })

    # Keep last 200 entries
    if len(history) > 200:
        history = history[-200:]

    path.write_text(json.dumps(history, indent=2))


def get_drift_history(name: str) -> list[dict]:
    """Return the drift scan history for a named schedule (newest first)."""
    path = _history_path(name)
    if not path.exists():
        return []
    try:
        history = json.loads(path.read_text())
        return list(reversed(history))
    except Exception:
        return []


# ─── Alert sender ────────────────────────────────────────────────────────────

def _send_alert(webhook_url: str, schedule_name: str, scan_result: dict) -> None:
    """POST a Slack-compatible alert when drift score drops below threshold."""
    if not webhook_url:
        return

    score   = scan_result["score"]
    counts  = score["counts"]
    region  = scan_result.get("region", "unknown")

    # Build a concise Slack message
    text = (
        f":warning: *Drift Alert — {schedule_name}* (region: `{region}`)\n"
        f"Score dropped to *{score['score']}/100* ({score['grade']} — {score['label']})\n"
        f"Findings: {counts.get('critical', 0)} critical, {counts.get('high', 0)} high, "
        f"{counts.get('medium', 0)} medium, {counts.get('low', 0)} low\n"
        f"_Run `/drift` or check the API for details._"
    )
    payload = {"text": text}

    try:
        import requests as _req
        resp = _req.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200:
            log.info(f"Drift alert sent for schedule '{schedule_name}'")
        else:
            log.warning(f"Drift alert webhook returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Drift alert failed for '{schedule_name}': {e}")


# ─── Scan job ────────────────────────────────────────────────────────────────

def _run_scan(config: DriftScheduleConfig) -> dict | None:
    """Execute one drift scan, record history, and fire alert if needed."""
    from pipeline.snapshot import load_snapshot
    from pipeline.drift_detector import scan_and_compare

    snapshot = load_snapshot(config.snapshot_name)
    if snapshot is None:
        log.warning(f"Drift schedule '{config.name}': snapshot '{config.snapshot_name}' not found — skipping.")
        return None

    architecture = snapshot.get("architecture", {})
    log.info(f"Drift scan starting: schedule='{config.name}' region={config.region}")

    try:
        result = scan_and_compare(
            recommended=architecture,
            aws_access_key_id=config.aws_access_key_id,
            aws_secret_access_key=config.aws_secret_access_key,
            region=config.region,
        )
    except Exception as e:
        log.error(f"Drift scan failed for schedule '{config.name}': {e}")
        return None

    _append_history(config.name, result)

    score = result["score"]["score"]
    log.info(f"Drift scan complete: schedule='{config.name}' score={score}")

    if score < config.alert_threshold and config.alert_webhook_url:
        _send_alert(config.alert_webhook_url, config.name, result)

    return result


# ─── Scheduler lifecycle ─────────────────────────────────────────────────────

def start_scheduler() -> None:
    """Start the APScheduler background scheduler. Call once at app startup."""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1},
            timezone="UTC",
        )
        _scheduler.start()
        log.info("Drift governance scheduler started.")
    except ImportError:
        log.warning("apscheduler not installed — drift scheduling disabled.")
        _scheduler = None


def stop_scheduler() -> None:
    """Gracefully stop the scheduler. Call at app shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Drift scheduler stopped.")
    _scheduler = None


def register_schedule(config: DriftScheduleConfig) -> dict:
    """Register (or update) a periodic drift scan.

    Returns a summary dict with the schedule details.
    Replaces any existing schedule with the same name.
    """
    global _scheduler, _registered

    if _scheduler is None:
        start_scheduler()

    # Remove old job if it exists
    if config.name in _registered and _scheduler:
        try:
            _scheduler.remove_job(f"drift_{config.name}")
        except Exception:
            pass

    _registered[config.name] = config

    if config.enabled and _scheduler:
        _scheduler.add_job(
            func=_run_scan,
            args=[config],
            trigger="interval",
            minutes=config.interval_minutes,
            id=f"drift_{config.name}",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc),  # run immediately on register
        )
        log.info(
            f"Drift schedule '{config.name}' registered: "
            f"every {config.interval_minutes}min, threshold={config.alert_threshold}"
        )

    return {
        "name":             config.name,
        "snapshot_name":    config.snapshot_name,
        "region":           config.region,
        "interval_minutes": config.interval_minutes,
        "alert_threshold":  config.alert_threshold,
        "alert_webhook_url": bool(config.alert_webhook_url),
        "enabled":          config.enabled,
        "status":           "registered",
    }


def list_schedules() -> list[dict]:
    """Return all registered drift schedules."""
    return [
        {
            "name":             c.name,
            "snapshot_name":    c.snapshot_name,
            "region":           c.region,
            "interval_minutes": c.interval_minutes,
            "alert_threshold":  c.alert_threshold,
            "has_webhook":      bool(c.alert_webhook_url),
            "enabled":          c.enabled,
        }
        for c in _registered.values()
    ]


def remove_schedule(name: str) -> bool:
    """Remove a drift schedule. Returns True if it existed."""
    global _scheduler, _registered
    if name not in _registered:
        return False
    del _registered[name]
    if _scheduler:
        try:
            _scheduler.remove_job(f"drift_{name}")
        except Exception:
            pass
    log.info(f"Drift schedule '{name}' removed.")
    return True
