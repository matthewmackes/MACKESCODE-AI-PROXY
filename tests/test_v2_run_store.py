import tempfile
import unittest
from pathlib import Path

from backend.v2.services.run_store import RunStore
from src.console.services.eval_gates import EvalGateBlocked


class V2RunStoreTests(unittest.TestCase):
    def test_prompt_templates_persist_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: 100.0)
            created = store.save_prompt_template({
                "name": "Review",
                "description": "Code review prompt",
                "body": "Review {{file}}",
                "variables": ["file"],
                "examples": [{"title": "Small file", "values": {"file": "app.py"}, "rendered": "Review app.py"}],
                "owner_notes": "Keep prompts secret-free.",
                "tags": ["review"],
            })
            updated = store.save_prompt_template({**created, "body": "Review {{file}} carefully"})
            versions = store.list_prompt_template_versions(created["id"])
            rolled_back = store.rollback_prompt_template(created["id"], 1)

            self.assertEqual(created["version"], 1)
            self.assertEqual(updated["version"], 2)
            self.assertEqual(updated["variables"], ["file"])
            self.assertEqual(updated["examples"][0]["title"], "Small file")
            self.assertEqual(updated["owner_notes"], "Keep prompts secret-free.")
            self.assertEqual([row["version"] for row in versions], [2, 1])
            self.assertEqual(versions[0]["body"], "Review {{file}} carefully")
            self.assertEqual(rolled_back["version"], 3)
            self.assertEqual(rolled_back["body"], "Review {{file}}")
            self.assertEqual(store.list_prompt_templates()[0]["body"], "Review {{file}}")

    def test_run_profiles_persist_settings_and_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: 200.0)
            template = store.save_prompt_template({"name": "Chat", "body": "Answer {{question}}"})
            profile = store.save_run_profile({
                "name": "Daily coding",
                "model": "deepseek-3.2",
                "template_id": template["id"],
                "settings": {"mode": "code", "temperature": 0.2},
                "tags": ["daily", "code"],
            })

            self.assertEqual(profile["settings"]["mode"], "code")
            self.assertEqual(profile["tags"], ["daily", "code"])
            self.assertEqual(store.payload()["run_profiles"][0]["template_id"], template["id"])

    def test_run_profiles_capture_prompt_system_parameters_tools_budget_and_gateway(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3")
            profile = store.save_run_profile({
                "name": "Ops profile",
                "model": "deepseek-3.2",
                "settings": {
                    "mode": "code",
                    "default_prompt": "Investigate {{issue}}",
                    "system_prompt": "Stay inside the repository.",
                    "parameters": {"temperature": 0.2, "max_tokens": 2048},
                    "tools": {"allowed": ["Read", "Edit"], "disallowed": ["Bash(rm -rf *)"]},
                    "budget": {"max_usd": 1.5},
                    "gateway_policy": {"preferred_route": "serverless", "fallback": "dedicated"},
                },
                "tags": ["ops"],
            })

            settings = profile["settings"]
            self.assertEqual(settings["default_prompt"], "Investigate {{issue}}")
            self.assertEqual(settings["system_prompt"], "Stay inside the repository.")
            self.assertEqual(settings["parameters"]["temperature"], 0.2)
            self.assertEqual(settings["parameters"]["max_tokens"], 2048)
            self.assertEqual(settings["tools"]["allowed"], ["Read", "Edit"])
            self.assertEqual(settings["budget"]["max_usd"], 1.5)
            self.assertEqual(settings["gateway_policy"]["preferred_route"], "serverless")

    def test_run_profile_activation_versions_and_rollback(self):
        ticks = iter([10.0, 20.0, 30.0, 40.0, 50.0])
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: next(ticks))
            first = store.save_run_profile({"name": "Daily coding", "model": "model-a", "settings": {"mode": "code"}})
            second = store.save_run_profile({"name": "Review only", "model": "model-b", "settings": {"mode": "review"}})
            first_v1_archived_at = store.list_run_profile_versions(first["id"])[0]["archived_at"]

            activated = store.activate_run_profile(first["id"])
            activated_v1_archived_at = store.list_run_profile_versions(first["id"])[0]["archived_at"]
            updated = store.save_run_profile({**activated, "model": "model-c", "settings": {"mode": "eval"}})
            versions = store.list_run_profile_versions(first["id"])
            rolled_back = store.rollback_run_profile(first["id"], 1)

            self.assertTrue(activated["active"])
            self.assertEqual(activated_v1_archived_at, first_v1_archived_at)
            self.assertFalse([profile for profile in store.list_run_profiles() if profile["id"] == second["id"]][0]["active"])
            self.assertEqual(updated["version"], 2)
            self.assertEqual([row["version"] for row in versions], [2, 1])
            self.assertEqual(rolled_back["version"], 3)
            self.assertEqual(rolled_back["model"], "model-a")
            self.assertEqual(rolled_back["settings"]["mode"], "code")
            self.assertTrue(rolled_back["active"])
            self.assertEqual(store.payload()["active_run_profile"]["id"], first["id"])

    def test_eval_gate_blocks_required_profile_activation_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: 1000.0)
            profile = store.save_run_profile({"name": "Protected", "model": "model-a"})

            with self.assertRaises(EvalGateBlocked):
                store.activate_run_profile(profile["id"], {"policy": {"require_pass": True}, "datasets": [{"id": "smoke", "name": "Smoke", "valid": True, "example_count": 1}]})

            self.assertIsNone(store.payload()["active_run_profile"])

    def test_eval_gate_records_template_change_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: 1000.0)
            template = store.save_prompt_template({"name": "Incident", "body": "Fix {{issue}}"})
            updated = store.save_prompt_template({
                **template,
                "body": "Fix {{issue}} carefully",
                "eval_gate": {
                    "policy": {"require_pass": True},
                    "datasets": [{"id": "prompt-regression", "name": "Prompt regression", "description": "prompt template", "valid": True, "example_count": 2}],
                    "runs": [{"id": "eval-prompt", "created_at": 999.0, "dataset": "prompt-regression", "models": ["model-a"], "summary": [{"requests": 2, "failures": 0, "pass_rate": 1.0}]}],
                },
            })
            records = store.list_eval_gate_records(template["id"])

            self.assertEqual(updated["version"], 2)
            self.assertEqual(updated["eval_gate"]["decision"], "passed")
            self.assertEqual(records[0]["target_id"], template["id"])
            self.assertEqual(records[0]["target_version"], 2)
            self.assertEqual(records[0]["gate"]["evidence"][0]["id"], "eval-prompt")

    def test_run_records_link_trace_to_profile_and_template_versions(self):
        ticks = iter([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: next(ticks))
            template = store.save_prompt_template({"name": "Incident", "body": "Fix {{issue}}"})
            profile = store.save_run_profile({
                "name": "Incident runner",
                "model": "deepseek-3.2",
                "template_id": template["id"],
                "settings": {"mode": "code"},
            })
            updated_template = store.save_prompt_template({**template, "body": "Fix {{issue}} carefully"})
            updated_profile = store.save_run_profile({**profile, "settings": {"mode": "code", "temperature": 0.2}})

            record = store.save_run_record({
                "trace_id": "trace-123",
                "session_id": "session-a",
                "profile_id": profile["id"],
                "prompt_template_id": template["id"],
                "input": {"prompt": "Fix failing release check"},
                "result": {"status": "ok"},
                "metadata": {"source": "chat"},
                "tags": ["release"],
            })

            self.assertEqual(record["title"], "trace-123")
            self.assertEqual(record["trace_id"], "trace-123")
            self.assertEqual(record["profile_id"], profile["id"])
            self.assertEqual(record["profile_version"], updated_profile["version"])
            self.assertEqual(record["prompt_template_id"], template["id"])
            self.assertEqual(record["prompt_template_version"], updated_template["version"])
            self.assertEqual(record["input"]["prompt"], "Fix failing release check")
            self.assertEqual(record["metadata"]["source"], "chat")
            self.assertEqual(store.payload()["run_records"][0]["trace_id"], "trace-123")

    def test_prompt_template_preview_renders_values_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3")
            template = store.save_prompt_template({
                "name": "Brief",
                "body": "Write for {{audience}} about {{topic}} in {{tone}} tone.",
                "variables": ["audience", "topic", "tone"],
            })

            preview = store.preview_prompt_template({
                "template_id": template["id"],
                "values": {"audience": "operators", "topic": "release gates"},
            })

            self.assertIn("operators", preview["rendered"])
            self.assertIn("release gates", preview["rendered"])
            self.assertIn("{{tone}}", preview["rendered"])
            self.assertEqual(preview["missing_variables"], ["tone"])
            self.assertEqual(preview["used_variables"], ["audience", "topic", "tone"])

    def test_validation_rejects_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3")
            with self.assertRaises(ValueError):
                store.save_prompt_template({"name": "", "body": "x"})
            with self.assertRaises(ValueError):
                store.save_prompt_template({"name": "x", "body": ""})
            with self.assertRaises(ValueError):
                store.save_run_profile({"name": ""})
            with self.assertRaises(ValueError):
                store.save_run_record({})
            with self.assertRaises(ValueError):
                store.save_conversation_branch({"title": ""})
            with self.assertRaises(ValueError):
                store.save_session_snapshot({"session_id": ""})

    def test_conversation_branches_persist_messages_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: 300.0)
            branch = store.save_conversation_branch({
                "title": "Alternative answer",
                "root_session_id": "session-a",
                "summary": "Try a shorter answer",
                "messages": [{"role": "user", "content": "hello"}],
                "metadata": {"source": "manual"},
                "tags": ["branch"],
            })
            updated = store.save_conversation_branch({**branch, "summary": "Try a direct answer"})

            self.assertEqual(updated["version"], 2)
            self.assertEqual(updated["messages"][0]["role"], "user")
            self.assertEqual(updated["metadata"]["source"], "manual")
            self.assertEqual(store.payload()["conversation_branches"][0]["summary"], "Try a direct answer")

    def test_session_snapshots_link_trace_agentboard_and_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp) / "run.sqlite3", clock=lambda: 400.0)
            snapshot = store.save_session_snapshot({
                "session_id": "session-a",
                "title": "Before refactor",
                "trace_id": "trace-1",
                "summary": "Captured active session",
                "agentboard": {"status": "working", "model": "codex"},
                "resource": {"cpu_percent": 12.5, "rss_mb": 128},
                "tags": ["snapshot"],
            })

            self.assertEqual(snapshot["trace_id"], "trace-1")
            self.assertEqual(snapshot["agentboard"]["status"], "working")
            self.assertEqual(snapshot["resource"]["rss_mb"], 128)
            self.assertEqual(store.payload()["session_snapshots"][0]["session_id"], "session-a")


if __name__ == "__main__":
    unittest.main()
