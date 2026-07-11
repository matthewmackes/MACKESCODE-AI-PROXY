import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.config_drift import ConfigDriftService


class ConfigDriftServiceTests(unittest.TestCase):
    def service(self, root, audits=None):
        root = Path(root)
        audits = audits if audits is not None else []
        model = root / "models.json"
        policy = root / "gateway.json"
        budget = root / "budgets.json"
        model.write_text('{"models":[]}', encoding="utf-8")
        policy.write_text('{"failover":{"enabled":true}}', encoding="utf-8")
        budget.write_text('{"daily_usd":5}', encoding="utf-8")
        return ConfigDriftService(
            baseline_file=lambda: root / "baseline.json",
            items=[
                {"name": "model_registry", "label": "Models", "path": lambda: model, "risk": "high", "backup_item": "model_registry"},
                {"name": "gateway_policy", "label": "Gateway", "path": lambda: policy, "risk": "high", "backup_item": "gateway_policy"},
                {"name": "budget_limits", "label": "Budgets", "path": lambda: budget, "risk": "medium", "backup_item": "budgets"},
                {"name": "missing_state", "label": "Missing", "path": lambda: root / "missing.json", "risk": "low"},
                {"name": "role_tokens", "label": "Roles", "kind": "summary", "risk": "high", "value_provider": lambda: {"source": "config", "count": 1, "profiles": [{"id": "operator", "roles": ["operator"], "permission_count": 0}]}},
            ],
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=lambda: 1000,
        )

    def test_payload_reports_unbaselined_items_and_mark_baseline_clears_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            audits = []
            service = self.service(tmp, audits)
            initial = service.payload()
            marked = service.mark_baseline({"actor": {"id": "ops", "roles": ["infra_admin"]}, "reason": "release-check passed"})
            doc = json.loads((Path(tmp) / "baseline.json").read_text(encoding="utf-8"))

        self.assertEqual(initial["summary"]["state"], "no_baseline")
        self.assertGreater(initial["summary"]["drift_count"], 0)
        self.assertEqual(marked["summary"]["state"], "clean")
        self.assertIn("model_registry", doc["items"])
        self.assertEqual(doc["actor"]["id"], "ops")
        self.assertEqual(audits[0][0][0], "config_drift.baseline.mark")

    def test_detects_changed_missing_and_acknowledged_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audits = []
            service = self.service(root, audits)
            service.mark_baseline({"actor": {"id": "ops"}})
            (root / "models.json").write_text('{"models":[{"id":"new"}]}', encoding="utf-8")
            (root / "budgets.json").unlink()
            drift = service.payload()
            acked = service.acknowledge({"actor": {"id": "ops"}, "items": ["model_registry"], "reason": "approved model sync"})

        rows = {row["name"]: row for row in drift["drift"]}
        self.assertEqual(rows["model_registry"]["status"], "changed")
        self.assertEqual(rows["budget_limits"]["status"], "existence_changed")
        self.assertEqual(drift["summary"]["highest_risk"], "high")
        ack_rows = {row["name"]: row for row in acked["drift"]}
        self.assertTrue(ack_rows["model_registry"]["acknowledged"])
        self.assertFalse(ack_rows["budget_limits"]["acknowledged"])
        self.assertEqual(audits[-1][0][0], "config_drift.acknowledge")

    def test_acknowledge_requires_baseline_and_matching_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            with self.assertRaisesRegex(ValueError, "baseline is required"):
                service.acknowledge({"items": ["model_registry"]})
            service.mark_baseline({})
            with self.assertRaisesRegex(ValueError, "no current drift items"):
                service.acknowledge({"items": ["model_registry"]})


if __name__ == "__main__":
    unittest.main()
