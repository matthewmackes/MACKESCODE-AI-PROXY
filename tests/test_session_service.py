import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.session import SessionService


class SessionServiceTests(unittest.TestCase):
    def service(self, tmp, live_output="", tmux_existing=None, now=1000):
        root = Path(tmp)
        registry_path = root / "tmux-sessions.json"
        log_path = root / "usage.jsonl"
        log_path.write_text("", encoding="utf-8")
        tmux_existing = set(tmux_existing or [])

        def tmux_cmd(args, check=True):
            if args[:2] == ["list-sessions", "-F"]:
                return (0, live_output, "")
            if args[:1] == ["rename-session"]:
                old_name = args[2]
                new_name = args[3]
                tmux_existing.discard(old_name)
                tmux_existing.add(new_name)
                return (0, "", "")
            return (1, "", "unsupported")

        return SessionService(
            registry_file=lambda: registry_path,
            log_file=lambda: log_path,
            script_dir=lambda: root,
            tmux_exists=lambda name: name in tmux_existing,
            tmux_cmd=tmux_cmd,
            model_metadata_map=lambda: {"model-a": {"display_name": "Model A", "cost_label": "$0.10 input / 1M tokens"}},
            clock=lambda: now,
        )

    def test_session_name_sanitizes_and_defaults(self):
        service = self.service(tempfile.mkdtemp())
        self.assertEqual(service.session_name("bad name!*"), "badname")
        self.assertEqual(service.session_name(""), "matts-claude")

    def test_unique_name_avoids_tmux_registry_and_reserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, tmux_existing={"work"})
            service.write_registry({"work-2": {"name": "work-2"}})

            self.assertEqual(service.unique_name("work", reserved={"work-3"}), "work-4")

    def test_upsert_and_session_items_enrich_live_rows(self):
        live = "work\t900\t980\t0\t1\n"
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, live_output=live, now=1000)
            service.upsert("work", {"display_name": "Work", "model": "model-a", "project_dir": tmp}, live=True)
            item = service.session_items()[0]

        self.assertEqual(item["display_name"], "Work")
        self.assertEqual(item["model_display"], "Model A")
        self.assertEqual(item["status"], "live")
        self.assertFalse(item["read_only"])

    def test_previous_session_rename_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            service.write_registry({"old": {"name": "old", "live": False}})

            status, payload = service.rename_session("old", "new")

        self.assertEqual(status.value, 400)
        self.assertIn("read-only", payload["error"])

    def test_proxy_usage_since_counts_matching_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            service.log_file().write_text(
                json.dumps({"ts": 900, "model": "model-a", "cost": {"total_cost_usd": 0.2, "total_tokens_est": 10}}) + "\n" +
                json.dumps({"ts": 950, "model": "model-b", "cost": {"total_cost_usd": 1.0, "total_tokens_est": 50}}) + "\n",
                encoding="utf-8",
            )

            usage = service.proxy_usage_since("model-a", 800)

        self.assertEqual(usage, {"cost_usd": 0.2, "tokens": 10, "requests": 1})


if __name__ == "__main__":
    unittest.main()
