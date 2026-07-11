import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.onboarding import OnboardingChecklistService


class OnboardingChecklistServiceTests(unittest.TestCase):
    def service(self, root, **overrides):
        root = Path(root)
        deps = {
            "state_file": lambda: root / "onboarding.json",
            "project_dir": lambda: root,
            "token_file": lambda: root / "token",
            "digitalocean_token": lambda: "",
            "digitalocean_token_paths": lambda: [root / "do-token"],
            "active_model_access_key_info": lambda: {"configured": False, "source": "missing"},
            "port_open": lambda host, port: False,
            "proxy_host": lambda: "127.0.0.1",
            "proxy_port": lambda: 18081,
            "proxy_sync_payload": lambda force=False: {"in_sync": False},
            "models_payload": lambda refresh_catalog=False: {"text_model_options": [], "registry_status": {"valid": True}},
            "budget_file": lambda: root / "budgets.json",
            "auth_enabled": lambda: True,
            "role_token_summary": lambda: {"count": 0, "source": "config", "profiles": []},
            "rollback_targets_payload": lambda: {"summary": {"runtime_archives": 0}, "procedures": {"runtime_state": "backup command"}},
            "dedicated_status_payload": lambda poll=False: {"dedicated": {"state": "not_configured"}},
            "serverless_catalog_payload": lambda force=False: {"catalog": {"status": "missing"}},
            "clock": lambda: 1234.0,
        }
        deps.update(overrides)
        return OnboardingChecklistService(**deps)

    def test_payload_detects_incomplete_first_run_without_token_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.service(root, digitalocean_token=lambda: "dop_v1_secret_value")

            payload = service.payload()
            text = json.dumps(payload)

            self.assertTrue(payload["first_run"])
            self.assertFalse(payload["complete"])
            self.assertGreater(payload["summary"]["incomplete"], 0)
            self.assertIn("model_access_token", [row["id"] for row in payload["checks"]])
            self.assertNotIn("dop_v1_secret_value", text)
            self.assertIn(str(root / "do-token"), text)

    def test_completion_state_is_persisted_and_marks_check_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            for name in ("release-check.sh", "browser-smoke.py", "v2-browser-smoke.py", "runtime-state.py"):
                (root / "scripts" / name).write_text("#!/bin/sh\n", encoding="utf-8")
            (root / "budgets.json").write_text('{"daily_usd": 10}\n', encoding="utf-8")
            service = self.service(
                root,
                active_model_access_key_info=lambda: {"configured": True, "source": "file"},
                port_open=lambda host, port: True,
                proxy_sync_payload=lambda force=False: {"in_sync": True},
                models_payload=lambda refresh_catalog=False: {"text_model_options": [{"id": "model-a", "enabled": True, "access_status": "ok"}], "registry_status": {"valid": True}},
                role_token_summary=lambda: {"count": 1, "source": "config", "profiles": [{"id": "operator"}]},
                rollback_targets_payload=lambda: {"summary": {"runtime_archives": 1}, "procedures": {"runtime_state": "backup command"}},
            )

            payload = service.complete({"id": "release_smoke", "actor": {"id": "owner"}, "note": "ran release check"})

            release = [row for row in payload["checks"] if row["id"] == "release_smoke"][0]
            self.assertTrue(release["completed"])
            self.assertEqual(release["status"], "passed")
            state = json.loads((root / "onboarding.json").read_text(encoding="utf-8"))
            self.assertEqual(state["completed"]["release_smoke"]["actor_id"], "owner")

    def test_missing_completion_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "item id is required"):
                self.service(tmp).complete({})


if __name__ == "__main__":
    unittest.main()
