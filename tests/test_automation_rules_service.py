import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.automation_rules import AutomationRulesService


class AutomationRulesServiceTests(unittest.TestCase):
    def service(self, root, *, http_post=None):
        root = Path(root)
        calls = {"reviews": [], "snapshots": [], "audits": [], "dedicated": [], "evals": []}
        service = AutomationRulesService(
            rules_file=lambda: root / "automation-rules.json",
            execution_log_file=lambda: root / "automation-executions.jsonl",
            create_review_item=lambda payload: calls["reviews"].append(payload) or {"review": {"id": "review-a", **payload}},
            create_session_snapshot=lambda payload: calls["snapshots"].append(payload) or {"snapshot": {"session": payload.get("session")}},
            append_audit=lambda *args, **kwargs: calls["audits"].append((args, kwargs)),
            append_dedicated_event=lambda *args, **kwargs: calls["dedicated"].append((args, kwargs)),
            run_eval=lambda payload: calls["evals"].append(payload) or {"id": "eval-run", "dataset_id": payload.get("dataset_id")},
            http_post=http_post,
            clock=lambda: 1000,
        )
        return service, calls

    def rule_config(self):
        return {
            "rules": [{
                "id": "eval-fail",
                "name": "Eval failures",
                "enabled": True,
                "trigger": {"event": "eval_failure", "source": "eval", "min_severity": "high", "field_equals": {"model": "model-a"}},
                "actions": [
                    {"type": "create_review", "severity": "high", "reason": "eval_failure"},
                    {"type": "audit_event", "action": "automation.eval_failure"},
                    {"type": "session_snapshot", "session_field": "session"},
                ],
            }]
        }

    def test_matching_executes_local_actions_and_redacts_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, calls = self.service(tmp)
            service.save_config(self.rule_config(), actor={"id": "infra"})
            result = service.run_event({"event": {"event": "eval_failure", "source": "eval", "severity": "critical", "model": "model-a", "session": "work", "token": "secret-token"}})
            log = Path(tmp, "automation-executions.jsonl").read_text(encoding="utf-8")

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(calls["reviews"][0]["reason"], "eval_failure")
        self.assertEqual(calls["snapshots"][0]["session"], "work")
        self.assertTrue(any(call[0][0] == "automation.eval_failure" for call in calls["audits"]))
        self.assertNotIn("secret-token", log)

    def test_dry_run_plans_without_side_effect_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, calls = self.service(tmp)
            service.save_config(self.rule_config())
            result = service.run_event({"event": "eval_failure", "source": "eval", "severity": "high", "model": "model-a", "session": "work"}, dry_run=True)

        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(calls["reviews"], [])
        self.assertEqual(calls["snapshots"], [])
        self.assertTrue(result["matched_rules"][0]["actions"][0]["planned"])

    def test_signed_webhook_retries_until_success(self):
        seen = []

        def http_post(url, body, headers, timeout):
            seen.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
            return (500, "fail") if len(seen) == 1 else (204, "")

        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, http_post=http_post)
            service.save_config({"rules": [{
                "id": "provider",
                "trigger": {"event": "provider_outage"},
                "actions": [{"type": "webhook", "url": "https://hooks.local/matts", "secret": "hook-secret", "max_retries": 2, "timeout_seconds": 7}],
            }]})
            result = service.run_event({"event": "provider_outage", "severity": "high", "secret": "provider-secret"})

        action = result["matched_rules"][0]["actions"][0]
        self.assertTrue(action["ok"])
        self.assertEqual(len(action["attempts"]), 2)
        self.assertEqual(seen[0]["timeout"], 7)
        self.assertTrue(seen[0]["headers"]["x-matts-signature"].startswith("sha256="))
        self.assertNotIn("provider-secret", seen[0]["body"])

    def test_run_eval_action_dispatches_on_matching_event_and_dry_run_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, calls = self.service(tmp)
            service.save_config({"rules": [{
                "id": "profile-change-eval",
                "trigger": {"event": "run_profile.changed", "source": "run"},
                "actions": [{"type": "run_eval", "dataset_id": "smoke", "models": ["model-a"]}],
            }]})
            dry_run = service.run_event({"event": "run_profile.changed", "source": "run"}, dry_run=True)
            result = service.run_event({"event": "run_profile.changed", "source": "run"})

        self.assertEqual(calls["evals"][0]["dataset_id"], "smoke")
        self.assertEqual(calls["evals"][0]["trigger"]["event"], "run_profile.changed")
        self.assertTrue(dry_run["matched_rules"][0]["actions"][0]["planned"])
        self.assertEqual(result["matched_rules"][0]["actions"][0]["result"]["id"], "eval-run")

    def test_due_scheduled_eval_runs_once_per_interval(self):
        now = {"value": 1000}
        with tempfile.TemporaryDirectory() as tmp:
            service, calls = self.service(tmp)
            service.clock = lambda: now["value"]
            service.save_config({"rules": [{
                "id": "scheduled-eval",
                "trigger": {
                    "event": "eval.scheduled",
                    "source": "schedule",
                    "schedule": {"interval_seconds": 60, "event": "eval.scheduled", "source": "schedule"},
                },
                "actions": [{"type": "run_eval", "dataset_id": "nightly", "models": ["model-a"]}],
            }]})
            dry_run = service.run_due_schedules({"dry_run": True})
            first = service.run_due_schedules({})
            second = service.run_due_schedules({})
            now["value"] = 1061
            third = service.run_due_schedules({})

        self.assertTrue(dry_run["dry_run"])
        self.assertEqual(dry_run["executed_count"], 0)
        self.assertEqual(first["executed_count"], 1)
        self.assertEqual(second["executed_count"], 0)
        self.assertEqual(third["executed_count"], 1)
        self.assertEqual([call["dataset_id"] for call in calls["evals"]], ["nightly", "nightly"])
        self.assertEqual(calls["evals"][0]["trigger"]["event"], "eval.scheduled")

    def test_redacted_webhook_secret_is_preserved_on_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp)
            service.save_config({"rules": [{
                "id": "provider",
                "trigger": {"event": "provider_outage"},
                "actions": [{"type": "webhook", "url": "https://hooks.local/matts", "secret": "hook-secret"}],
            }]})
            service.save_config({"rules": [{
                "id": "provider",
                "trigger": {"event": "provider_outage"},
                "actions": [{"type": "webhook", "url": "https://hooks.local/matts", "secret": "[redacted]"}],
            }]})
            stored = json.loads(Path(tmp, "automation-rules.json").read_text(encoding="utf-8"))

        self.assertEqual(stored["rules"][0]["actions"][0]["secret"], "hook-secret")

    def test_invalid_action_and_webhook_url_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp)
            with self.assertRaisesRegex(ValueError, "unsupported automation action"):
                service.save_config({"rules": [{"actions": [{"type": "shell"}]}]})
            with self.assertRaisesRegex(ValueError, "http"):
                service.save_config({"rules": [{"actions": [{"type": "webhook", "url": "file:///tmp/x"}]}]})


if __name__ == "__main__":
    unittest.main()
