import tempfile
import unittest
from pathlib import Path

from src.console.services.failure_taxonomy import FailureTaxonomyService
from src.console.services.notifications import NotificationCenterService


class NotificationCenterServiceTests(unittest.TestCase):
    def service(self, root, *, audits=None, clock=None):
        audits = audits if audits is not None else []
        return NotificationCenterService(
            state_file=lambda: Path(root) / "notifications.json",
            review_queue_payload=lambda status="": {"reviews": [{
                "id": "review-a",
                "title": "Review failed eval",
                "status": "open",
                "severity": "high",
                "reason": "eval_failure",
                "created_at": 1000,
                "evidence": {"prompt": "secret prompt", "cost": 1.2},
            }]},
            provider_health_payload=lambda: {"generated_at": 1001, "findings": [{"type": "provider_outage", "title": "Provider outage", "severity": "critical", "detail": "incident", "failure_categories": {"provider_outage": 2}}]},
            release_candidate_payload=lambda: {"generated_at": 1002, "checks": [{"id": "coverage", "title": "Coverage", "status": "failed", "blocking": True, "evidence": {"token": "secret"}}]},
            automation_payload=lambda: {"executions": [{"id": "automation-a", "created_at": 1003, "dry_run": False, "matched_count": 1, "event": {"event": "eval_failure"}, "matched_rules": [{"actions": [{"type": "webhook", "ok": False}]}]}]},
            list_eval_runs=lambda limit=25: [{"id": "run-a", "dataset": "smoke", "created_at": 1004, "summary": [{"model": "model-a", "failures": 2}]}],
            dedicated_events=lambda limit=80: [{"ts": 1005, "state": "unhealthy", "severity": "error", "message": "Endpoint down", "details": {"secret": "hidden"}}],
            cost_summary_payload=lambda: {"checked_at": 1006, "dedicated_runtime": {"budget_state": {"warning": True, "critical": False, "percent": 80.0}}},
            cost_anomaly_payload=lambda: {"generated_at": 1006, "anomalies": [{"id": "cost-a", "title": "Spend Usd Anomaly", "metric": "spend_usd", "severity": "high", "status": "new", "current": 15, "baseline": 2, "unit": "usd", "evidence": {"top_model": {"key": "model-a"}}}]},
            quota_planner_payload=lambda: {"quotas": [{"source": "action", "name": "chat", "window": "daily", "metric": "requests", "limit": 10, "used": 10}]},
            audit_rows=lambda limit=200: [{"ts": 1007, "action": "auth.session", "outcome": "failed", "status": 403, "request": {"authorization": "secret"}}],
            failure_taxonomy=FailureTaxonomyService(),
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=clock or (lambda: 2000),
        )

    def test_payload_derives_major_categories_and_redacts_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            payload = service.payload()

        categories = {item["category"] for item in payload["notifications"]}
        self.assertTrue({"review", "provider", "release", "quality", "automation", "dedicated", "cost", "security"}.issubset(categories))
        self.assertGreaterEqual(payload["summary"]["critical"], 2)
        text = str(payload["notifications"])
        self.assertNotIn("secret prompt", text)
        self.assertNotIn("hidden", text)
        self.assertIn("Spend Usd Anomaly", text)
        self.assertIn("Provider outage", text)

    def test_filter_and_update_notification_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            audits = []
            service = self.service(tmp, audits=audits)
            review_id = next(item["id"] for item in service.payload()["notifications"] if item["category"] == "review")
            updated = service.update({"id": review_id, "status": "acknowledged", "notes": "triaged"}, actor={"id": "operator"})
            filtered = service.payload({"status": "acknowledged"})

        self.assertTrue(any(item["id"] == review_id and item["status"] == "acknowledged" for item in updated["notifications"]))
        self.assertEqual([item["id"] for item in filtered["notifications"]], [review_id])
        self.assertEqual(audits[0][0][0], "notification.update")

    def test_retention_drops_old_resolved_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, clock=lambda: 4000000)
            state = service.default_state()
            state["states"] = {
                "old": {"status": "resolved", "resolved_at": 1},
                "active": {"status": "acknowledged", "acknowledged_at": 1},
            }
            compacted = service.compact_state(state)

        self.assertNotIn("old", compacted["states"])
        self.assertIn("active", compacted["states"])


if __name__ == "__main__":
    unittest.main()
