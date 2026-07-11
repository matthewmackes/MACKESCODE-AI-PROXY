import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.session_snapshots import SessionSnapshotService


class SessionSnapshotServiceTests(unittest.TestCase):
    def service(self, root):
        root = Path(root)
        model_config = root / "models.json"
        gateway_policy = root / "gateway.json"
        model_config.write_text('{"models":[]}', encoding="utf-8")
        gateway_policy.write_text('{"enabled":true}', encoding="utf-8")

        def tail_jsonl(path, limit=500):
            return [{
                "action": "tmux.send",
                "request": {"body": {"name": "work", "token": "dop_v1_secret"}},
                "actor": {"id": "operator"},
            }]

        return SessionSnapshotService(
            snapshots_dir=lambda: root / "snapshots",
            tmux_session_items=lambda: [{"name": "work", "model": "model-a", "resource_metrics": {"cpu_percent": 12.5}, "imported_context": {"provider": "github", "owner": "acme", "repo": "app", "number": 42, "title": "Fix tests", "url": "https://github.com/acme/app/pull/42"}}],
            agentboard_payload=lambda: {"sessions": [{"name": "work", "status": "working", "last_prompt": "Deploy"}]},
            read_traces=lambda **kwargs: [{"trace_id": "trace-a", "session_id": "work", "status": "success", "requested_model": "model-a", "human_message": "Bearer secret-token"}],
            tail_jsonl=tail_jsonl,
            audit_file=lambda: root / "audit.jsonl",
            tmux_capture=lambda name: (200, {"screen": "output with sk-secretvalue"}),
            cost_summary_payload=lambda: {"total": 1.25},
            console_status=lambda: {"service": "console", "token": "secret"},
            model_config_file=lambda: model_config,
            gateway_policy_file=lambda: gateway_policy,
            clock=lambda: 1000,
        )

    def test_create_writes_redacted_json_and_markdown_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.service(tmp).create({"session": "work", "actor": {"id": "operator"}})
            json_path = Path(result["files"]["json"])
            md_path = Path(result["files"]["markdown"])
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

        self.assertTrue(json_path.name.endswith(".json"))
        self.assertTrue(md_path.name.endswith(".md"))
        self.assertEqual(doc["session"]["name"], "work")
        self.assertEqual(doc["resources"]["cpu_percent"], 12.5)
        self.assertEqual(doc["session"]["imported_context"]["repo"], "app")
        self.assertEqual(doc["config_fingerprints"]["model_registry"]["available"], True)
        self.assertIn("Session Snapshot", markdown)
        self.assertIn("Imported Repository Context", markdown)
        self.assertNotIn("dop_v1_secret", json.dumps(doc))
        self.assertNotIn("sk-secretvalue", markdown)

    def test_create_requires_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "session is required"):
                self.service(tmp).create({})


if __name__ == "__main__":
    unittest.main()
