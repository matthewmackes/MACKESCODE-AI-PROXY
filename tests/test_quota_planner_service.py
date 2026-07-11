import tempfile
import unittest
from pathlib import Path

from src.console.services.quota_planner import QuotaPlannerService


class QuotaPlannerServiceTests(unittest.TestCase):
    def service(self, config=None, now=1700000000):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "quotas.jsonl"
        audits = []
        traces = []
        service = QuotaPlannerService(
            config=config or {
                "enabled": True,
                "warn_fraction": 0.8,
                "default_policy": {"daily": {"requests": 3, "usd": 10}, "monthly": {"requests": 10}},
                "roles": {"viewer": {"daily": {"requests": 2}}},
                "actions": {"chat": {"daily": {"requests": 2, "usd": 1}}},
                "models": {"model-a": {"daily": {"requests": 1}}},
                "projects": {"project-a": {"daily": {"requests": 1}}},
            },
            quota_file=lambda: path,
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            append_trace=lambda record: traces.append(record) or {"trace_id": "trace-a"},
            clock=lambda: now,
        )
        self.addCleanup(tmp.cleanup)
        return service, path, audits, traces

    def test_accounts_by_actor_role_action_model_and_project(self):
        service, _, audits, traces = self.service()
        actor = {"id": "alice", "roles": ["viewer"], "source": "token"}
        data = {"model": "model-a", "project": "project-a", "forecast": {"estimated_total_usd": 0.25}}

        first = service.consume("/api/chat", data, actor=actor, actor_key="token:a")
        second = service.preview("/api/chat", data, actor=actor, actor_key="token:a")

        self.assertTrue(first["allowed"])
        self.assertFalse(second["allowed"])
        sources = {(block["source"], block["name"]) for block in second["blocks"]}
        self.assertIn(("model", "model-a"), sources)
        self.assertIn(("project", "project-a"), sources)
        self.assertEqual(first["actor"]["actor_key"], "token:a")
        self.assertEqual(first["actor"]["actor_roles"], ["viewer"])
        self.assertEqual(first["policy_decision"]["domain"], "quota")
        self.assertTrue(first["policy_decision"]["allowed"])
        self.assertFalse(second["policy_decision"]["allowed"])
        self.assertEqual(len(audits), 1)
        self.assertEqual(traces[0]["action"], "quota.decision")
        self.assertEqual(traces[0]["quota"]["policy_decision"]["domain"], "quota")

    def test_soft_warning_allows_request_and_records_ledger(self):
        service, path, _, _ = self.service(config={
            "enabled": True,
            "warn_fraction": 0.5,
            "actions": {"image": {"daily": {"requests": 2, "usd": 1}}},
        })

        decision = service.consume("/api/generate", {"forecast": {"estimated_total_usd": 0.5}}, actor={"id": "ops"}, actor_key="actor:ops")

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["status"], "warning")
        self.assertTrue(decision["warnings"])
        self.assertIn('"action": "image"', path.read_text(encoding="utf-8"))

    def test_hard_block_does_not_append_usage(self):
        service, path, audits, _ = self.service(config={
            "enabled": True,
            "actions": {"eval": {"daily": {"requests": 1}}},
        })

        allowed = service.consume("/api/evals/run", {}, actor={"id": "ops"}, actor_key="actor:ops")
        blocked = service.consume("/api/evals/run", {}, actor={"id": "ops"}, actor_key="actor:ops")

        self.assertTrue(allowed["allowed"])
        self.assertFalse(blocked["allowed"])
        self.assertEqual(path.read_text(encoding="utf-8").count('"action": "eval"'), 1)
        self.assertEqual(audits[-1][1]["status"], 429)

    def test_daily_reset_ignores_previous_window(self):
        service, _, _, _ = self.service(now=1700086500, config={
            "enabled": True,
            "default_policy": {"daily": {"requests": 1}},
        })
        service.append_entry({
            "ts": service.window_start("daily") - 1,
            "actor_key": "actor:ops",
            "actor_roles": ["operator"],
            "action": "chat",
            "requests": 1,
            "usd": 0,
        })

        decision = service.consume("/api/chat", {}, actor={"id": "ops", "roles": ["operator"]}, actor_key="actor:ops")

        self.assertTrue(decision["allowed"])
        daily = [check for check in decision["checks"] if check["window"] == "daily"][0]
        self.assertEqual(daily["used"], 0.0)
        self.assertGreater(daily["reset_at"], 1700086500)

    def test_monthly_usage_blocks_inside_same_month(self):
        service, _, _, _ = self.service(now=1700086500, config={
            "enabled": True,
            "default_policy": {"monthly": {"usd": 1}},
        })
        service.append_entry({
            "ts": service.window_start("monthly") + 10,
            "actor_key": "actor:ops",
            "actor_roles": ["operator"],
            "action": "chat",
            "requests": 1,
            "usd": 0.75,
        })

        decision = service.preview("/api/chat", {"forecast": {"estimated_total_usd": 0.5}}, actor={"id": "ops", "roles": ["operator"]}, actor_key="actor:ops")

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["blocks"][0]["window"], "monthly")
        self.assertEqual(decision["blocks"][0]["metric"], "usd")


if __name__ == "__main__":
    unittest.main()
