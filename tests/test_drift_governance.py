# tests/test_drift_governance.py
#
# Unit tests for continuous drift governance:
#   - Snapshot save/load/list/delete
#   - Drift history recording
#   - Drift score and alert threshold logic
#   - _compare() diff engine (existing drift_detector logic)
#
# No boto3 / AWS calls — all AWS scanning is mocked.

import json
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock


# ─── Snapshot tests ───────────────────────────────────────────────────────────

class TestSnapshotStore:

    @pytest.fixture(autouse=True)
    def tmp_snapshots(self, tmp_path, monkeypatch):
        """Redirect snapshot writes to a temp directory."""
        monkeypatch.setenv("SNAPSHOTS_DIR", str(tmp_path))
        # Reload the module so _SNAPSHOTS_DIR picks up the new env var
        import importlib
        import pipeline.snapshot as snap
        importlib.reload(snap)
        self.snap = snap
        self.tmp = tmp_path

    def _arch(self, *services):
        return {"layers": {"compute": list(services), "database": []}}

    def test_save_and_load_roundtrip(self):
        arch = self._arch("Amazon ECS", "AWS Lambda")
        saved = self.snap.save_snapshot("test-snap", arch, query="my query", cloud_provider="aws")
        loaded = self.snap.load_snapshot("test-snap")
        assert loaded is not None
        assert loaded["name"] == "test-snap"
        assert loaded["query"] == "my query"
        assert loaded["cloud_provider"] == "aws"
        assert loaded["architecture"] == arch

    def test_load_nonexistent_returns_none(self):
        assert self.snap.load_snapshot("does-not-exist") is None

    def test_list_snapshots(self):
        self.snap.save_snapshot("snap-a", self._arch("ECS"), query="query a")
        self.snap.save_snapshot("snap-b", self._arch("Lambda"), query="query b")
        snapshots = self.snap.list_snapshots()
        names = [s["name"] for s in snapshots]
        assert "snap-a" in names
        assert "snap-b" in names

    def test_list_excludes_history_files(self):
        # Write a fake history file
        hist = self.tmp / "mysnap_history.json"
        hist.write_text("[]")
        self.snap.save_snapshot("mysnap", self._arch("ECS"))
        names = [s["name"] for s in self.snap.list_snapshots()]
        assert "mysnap" in names
        # History file should not appear as a snapshot
        assert "mysnap_history" not in names

    def test_delete_existing(self):
        self.snap.save_snapshot("to-delete", self._arch("ECS"))
        assert self.snap.delete_snapshot("to-delete") is True
        assert self.snap.load_snapshot("to-delete") is None

    def test_delete_nonexistent(self):
        assert self.snap.delete_snapshot("ghost") is False

    def test_special_chars_in_name_are_sanitized(self):
        self.snap.save_snapshot("my/weird:name!", self._arch("ECS"), query="q")
        # Should not raise; file will be sanitized
        snapshots = self.snap.list_snapshots()
        assert len(snapshots) == 1

    def test_snapshot_includes_saved_at(self):
        saved = self.snap.save_snapshot("ts-test", self._arch("ECS"))
        assert "saved_at" in saved
        assert "saved_at_ts" in saved
        assert saved["saved_at_ts"] > 0


# ─── Drift history tests ──────────────────────────────────────────────────────

class TestDriftHistory:

    @pytest.fixture(autouse=True)
    def tmp_snapshots(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SNAPSHOTS_DIR", str(tmp_path))
        import importlib
        import pipeline.drift_scheduler as sched
        importlib.reload(sched)
        self.sched = sched

    def _mock_scan_result(self, score=85, grade="A"):
        return {
            "region": "us-east-1",
            "snapshot": {},
            "findings": [],
            "score": {
                "score":  score,
                "grade":  grade,
                "label":  "Well aligned",
                "total":  0,
                "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            },
        }

    def test_empty_history_returns_empty_list(self):
        assert self.sched.get_drift_history("nonexistent") == []

    def test_append_and_read_history(self):
        self.sched._append_history("my-schedule", self._mock_scan_result(85, "A"))
        history = self.sched.get_drift_history("my-schedule")
        assert len(history) == 1
        assert history[0]["score"] == 85
        assert history[0]["grade"] == "A"

    def test_multiple_appends_ordered_newest_first(self):
        self.sched._append_history("sched", self._mock_scan_result(90, "A"))
        self.sched._append_history("sched", self._mock_scan_result(75, "B"))
        self.sched._append_history("sched", self._mock_scan_result(55, "C"))
        history = self.sched.get_drift_history("sched")
        # newest first
        assert history[0]["score"] == 55
        assert history[1]["score"] == 75
        assert history[2]["score"] == 90

    def test_history_entry_has_required_keys(self):
        self.sched._append_history("k", self._mock_scan_result(80, "A"))
        h = self.sched.get_drift_history("k")[0]
        for key in ("timestamp", "timestamp_ts", "score", "grade", "label", "findings_total", "counts", "region"):
            assert key in h, f"Missing key: {key}"

    def test_history_capped_at_200(self):
        for i in range(210):
            self.sched._append_history("big", self._mock_scan_result(50 + (i % 40), "B"))
        history = self.sched.get_drift_history("big")
        assert len(history) <= 200


# ─── Drift score logic ────────────────────────────────────────────────────────

class TestDriftScore:

    def setup_method(self):
        from pipeline.drift_detector import _drift_score
        self._drift_score = _drift_score

    def _finding(self, severity):
        return {"severity": severity, "service": "test", "category": "test",
                "status": "not_deployed", "finding": "...", "fix": "..."}

    def test_no_findings_scores_100(self):
        result = self._drift_score([])
        assert result["score"] == 100
        assert result["grade"] == "A"

    def test_one_critical_finding_deducts_25(self):
        result = self._drift_score([self._finding("critical")])
        assert result["score"] == 75

    def test_one_high_finding_deducts_15(self):
        result = self._drift_score([self._finding("high")])
        assert result["score"] == 85

    def test_score_floors_at_zero(self):
        findings = [self._finding("critical")] * 10
        result = self._drift_score(findings)
        assert result["score"] == 0

    def test_grade_thresholds(self):
        assert self._drift_score([])["grade"] == "A"                        # 100
        assert self._drift_score([self._finding("high")])["grade"] == "A"   # 85
        assert self._drift_score([self._finding("critical"), self._finding("high")])["grade"] == "B"  # 60
        findings_c = [self._finding("critical")] * 2 + [self._finding("high")]
        assert self._drift_score(findings_c)["grade"] == "D"               # 35

    def test_counts_by_severity(self):
        findings = [
            self._finding("critical"),
            self._finding("critical"),
            self._finding("high"),
            self._finding("medium"),
        ]
        result = self._drift_score(findings)
        assert result["counts"]["critical"] == 2
        assert result["counts"]["high"] == 1
        assert result["counts"]["medium"] == 1
        assert result["counts"]["low"] == 0


# ─── Drift compare (diff engine) ─────────────────────────────────────────────

class TestDriftCompare:

    def setup_method(self):
        from pipeline.drift_detector import _compare
        self._compare = _compare

    def _clean_snapshot(self):
        return {
            "has_cloudfront": True, "cloudfront_distributions": 1,
            "has_alb": True, "alb_count": 1, "nlb_count": 0,
            "has_ecs": True, "ecs_clusters": 1,
            "has_lambda": False, "lambda_count": 0,
            "has_rds": True, "rds_count": 1, "rds_multi_az": True,
            "rds_encrypted": True, "rds_engines": ["postgres"],
            "has_dynamodb": False, "dynamodb_tables": 0,
            "has_elasticache": False, "elasticache_clusters": 0,
            "has_sqs": True, "sqs_queues": 1,
            "has_api_gateway": False, "api_gateway_count": 0,
            "has_cloudwatch_alarms": True, "cloudwatch_alarms": 5,
            "has_cloudtrail": True, "cloudtrail_multi_region": True,
            "has_guardduty": True,
            "has_waf": True,
            "has_s3": True, "s3_buckets": 3,
            "ec2_count": 0, "ec2_multi_az": False,
        }

    def test_no_drift_on_matching_snapshot(self):
        services = ["Amazon CloudFront", "Application Load Balancer", "Amazon ECS",
                    "Amazon RDS", "Amazon SQS", "Amazon CloudWatch", "AWS CloudTrail",
                    "Amazon GuardDuty", "AWS WAF"]
        findings = self._compare(services, self._clean_snapshot())
        # Should have no findings for the services we've said are deployed
        missing = [f for f in findings if f["status"] == "not_deployed"
                   and any(kw in f["service"].lower() for kw in
                           ["cloudfront", "load balancer", "ecs", "rds", "sqs",
                            "cloudwatch", "cloudtrail", "guardduty", "waf"])]
        assert missing == []

    def test_missing_guardduty_is_critical(self):
        snap = self._clean_snapshot()
        snap["has_guardduty"] = False
        findings = self._compare(["Amazon GuardDuty"], snap)
        guardduty_findings = [f for f in findings if "guardduty" in f["service"].lower()
                              or "guardduty" in f["finding"].lower()]
        assert any(f["severity"] == "critical" for f in findings)

    def test_missing_waf_on_public_endpoint_is_high(self):
        snap = self._clean_snapshot()
        snap["has_waf"] = False
        # has_alb = True, so WAF should be flagged
        findings = self._compare([], snap)
        waf_findings = [f for f in findings if "waf" in f["service"].lower()]
        assert len(waf_findings) >= 1
        assert any(f["severity"] in ("high", "critical") for f in waf_findings)

    def test_rds_unencrypted_is_critical_misconfiguration(self):
        snap = self._clean_snapshot()
        snap["rds_encrypted"] = False
        findings = self._compare([], snap)
        rds_findings = [f for f in findings if "rds" in f["service"].lower()
                        and f["category"] == "misconfiguration"]
        assert len(rds_findings) >= 1
        assert rds_findings[0]["severity"] == "critical"

    def test_rds_single_az_is_high_misconfiguration(self):
        snap = self._clean_snapshot()
        snap["rds_multi_az"] = False
        findings = self._compare([], snap)
        single_az = [f for f in findings if "single az" in f["finding"].lower()
                     or "single AZ" in f["finding"]]
        assert len(single_az) >= 1
        assert single_az[0]["severity"] == "high"

    def test_findings_sorted_critical_first(self):
        snap = self._clean_snapshot()
        snap["has_guardduty"] = False
        snap["rds_encrypted"] = False
        snap["has_cloudwatch_alarms"] = False
        findings = self._compare(["Amazon GuardDuty"], snap)
        severities = [f["severity"] for f in findings]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for i in range(len(severities) - 1):
            assert order[severities[i]] <= order[severities[i + 1]]

    def test_no_cloudtrail_is_always_flagged(self):
        snap = self._clean_snapshot()
        snap["has_cloudtrail"] = False
        findings = self._compare([], snap)
        ct_findings = [f for f in findings if "cloudtrail" in f["service"].lower()]
        assert len(ct_findings) >= 1
        assert ct_findings[0]["severity"] == "critical"


# ─── Alert threshold logic ────────────────────────────────────────────────────

class TestAlertThreshold:
    """Verify _send_alert is called (or not) based on score vs threshold."""

    def test_alert_fires_when_score_below_threshold(self):
        from pipeline.drift_scheduler import _send_alert
        scan = {
            "region": "us-east-1",
            "score": {"score": 30, "grade": "D", "label": "Significant drift",
                      "total": 5, "counts": {"critical": 2, "high": 1, "medium": 2, "low": 0}},
        }
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            _send_alert("https://hooks.slack.com/test", "my-schedule", scan)
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert "my-schedule" in call_kwargs.kwargs.get("json", {}).get("text", "")

    def test_alert_skips_when_no_webhook(self):
        from pipeline.drift_scheduler import _send_alert
        with patch("pipeline.drift_scheduler.log") as mock_log:
            scan = {
                "region": "us-east-1",
                "score": {"score": 20, "grade": "F", "label": "Severely drifted",
                          "total": 8, "counts": {"critical": 4, "high": 2, "medium": 2, "low": 0}},
            }
            _send_alert("", "schedule-name", scan)
            # No warning logged — just silently returns
            mock_log.warning.assert_not_called()
