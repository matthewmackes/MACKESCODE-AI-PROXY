import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.policy_as_code import PolicyAsCodeService


class PolicyAsCodeServiceTests(unittest.TestCase):
    def service(self, root, audits=None):
        root = Path(root)
        audits = audits if audits is not None else []
        (root / "gateway.json").write_text(json.dumps({"schema_version": 1, "failover": {"enabled": True}}), encoding="utf-8")
        (root / "budgets.json").write_text(json.dumps({"daily_usd": 10}), encoding="utf-8")
        (root / "automation.json").write_text(json.dumps({"schema_version": 1, "rules": []}), encoding="utf-8")
        return PolicyAsCodeService(
            policy_file=lambda: root / "policies.json",
            history_file=lambda: root / "policy-history.jsonl",
            gateway_policy_file=lambda: root / "gateway.json",
            budget_file=lambda: root / "budgets.json",
            automation_rules_file=lambda: root / "automation.json",
            role_permissions=lambda: {"viewer": {"view_console"}, "infra_admin": {"policy_admin"}},
            quota_config=lambda: {"default_policy": {"daily": {"requests": 10}}},
            eval_gate_policy=lambda: {"schema_version": 1, "default_policy": {"require_pass": False}},
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=lambda: 1234.0,
        )

    def test_preview_detects_changes_and_secret_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            bundle = service.current_bundle()
            bundle["policies"]["budgets"]["daily_usd"] = 20
            preview = service.preview({"bundle": bundle, "sections": ["budgets"]})
            bundle["policies"]["automation"]["webhook_secret"] = "secret"
            blocked = service.preview({"bundle": bundle})

        self.assertFalse(preview["blocking"])
        self.assertTrue(preview["changes"][0]["changed"])
        self.assertTrue(blocked["blocking"])
        self.assertEqual(blocked["issues"][0]["section"], "automation")

    def test_apply_writes_active_sections_audits_and_rollback_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            audits = []
            service = self.service(tmp, audits=audits)
            bundle = service.current_bundle()
            bundle["policies"]["budgets"]["daily_usd"] = 25
            applied = service.apply({"bundle": bundle, "sections": ["budgets"], "actor": {"id": "ops"}})
            self.assertEqual(json.loads(Path(tmp, "budgets.json").read_text(encoding="utf-8"))["daily_usd"], 25)

            rolled = service.rollback({"version_id": applied["history"]["id"], "sections": ["budgets"], "actor": {"id": "ops"}})
            restored_daily = json.loads(Path(tmp, "budgets.json").read_text(encoding="utf-8"))["daily_usd"]

        self.assertTrue(applied["applied"])
        self.assertTrue(rolled["rolled_back"])
        self.assertEqual(restored_daily, 10)
        self.assertEqual([entry[0][0] for entry in audits], ["policy.apply", "policy.rollback"])

    def test_payload_includes_history_and_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            bundle = service.current_bundle()
            service.apply({"bundle": bundle})
            payload = service.payload()

        self.assertEqual(payload["bundle"]["schema_version"], 1)
        self.assertEqual(len(payload["history"]), 1)
        self.assertIn("fingerprint", payload["preview"])


if __name__ == "__main__":
    unittest.main()
