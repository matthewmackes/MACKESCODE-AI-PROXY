import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services.tmux_control import TmuxControlService


class TmuxControlServiceTests(unittest.TestCase):
    def service(self, tmp, tmux_cmd=None, tmux_existing=None, geteuid=lambda: 1000):
        root = Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        (root / "claude-DO.sh").write_text("start_proxy()\nexec claude\n", encoding="utf-8")
        if tmux_existing is None:
            tmux_existing = set()
        records = {"upserts": [], "sleeps": []}

        def default_tmux_cmd(args, check=True):
            if args[:1] == ["new-session"]:
                tmux_existing.add(args[args.index("-s") + 1])
                return 0, "", ""
            if args[:1] == ["capture-pane"]:
                return 0, "screen", ""
            if args[:1] == ["kill-session"]:
                tmux_existing.discard(args[-1])
                return 0, "", ""
            if args[:1] in (["set-buffer"], ["paste-buffer"], ["send-keys"]):
                return 0, "", ""
            if args[:1] == ["list-sessions"]:
                return 0, "\n".join(sorted(tmux_existing)), ""
            return 1, "", "unsupported"

        service = TmuxControlService(
            script_dir=lambda: root,
            text_models=lambda: ["model-a"],
            default_text_model=lambda: "model-a",
            tmux_cmd=tmux_cmd or default_tmux_cmd,
            tmux_exists=lambda name: name in tmux_existing,
            tmux_target=lambda value, default="matts-claude": "".join(ch for ch in str(value or default) if ch.isalnum() or ch in "-_:.") or default,
            tmux_capture_target=lambda target, lines="-200": (0, "screen for %s" % target, ""),
            unique_tmux_session_name=lambda value: str(value) + "-2",
            tmux_session_name=lambda value: str(value).replace(" ", ""),
            tmux_registry_upsert=lambda *args, **kwargs: records["upserts"].append((args, kwargs)),
            tmux_session_items=lambda: [{"name": "existing"}],
            live_session_names=lambda: ["live-a"],
            clock=lambda: 1000,
            sleep=lambda seconds: records["sleeps"].append(seconds),
            geteuid=geteuid,
        )
        return service, records, tmux_existing, root

    def test_launcher_health_valid_and_heals_from_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _, root = self.service(tmp)
            self.assertEqual(service.launcher_health(), {"ok": True, "healed": False, "path": str(root / "claude-DO.sh")})

            (root / "claude-DO.sh").write_text("broken\n", encoding="utf-8")
            (root / "claude-DO.sh.backup").write_text("start_proxy()\nexec claude\n", encoding="utf-8")
            healed = service.launcher_health()

        self.assertTrue(healed["ok"])
        self.assertTrue(healed["healed"])

    def test_launcher_health_reports_missing_or_incomplete_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _, root = self.service(tmp)
            (root / "claude-DO.sh").write_text("broken\n", encoding="utf-8")
            missing = service.launcher_health()
            (root / "claude-DO.sh.backup").write_text("also broken\n", encoding="utf-8")
            incomplete = service.launcher_health()

        self.assertFalse(missing["ok"])
        self.assertFalse(incomplete["ok"])
        self.assertIn("incomplete", incomplete["error"])

    def test_claude_launch_args_cover_modes_and_root_permission_downgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _, _ = self.service(tmp, geteuid=lambda: 0)
            args = service.claude_launch_args({
                "permission_mode": "bypassPermissions",
                "setting_sources": "user",
                "safe_mode": True,
                "bare": True,
                "add_dirs": "/a\n/b",
                "allowed_tools": "Read",
                "disallowed_tools": "Bash",
                "claude_session_name": "named",
                "run_mode": "stream-json",
                "print_prompt": "hello",
                "max_budget_usd": "1.25",
                "no_session_persistence": True,
                "extra_args": "--verbose",
            })

        self.assertIn("acceptEdits", args)
        self.assertIn("--setting-sources", args)
        self.assertIn("--safe-mode", args)
        self.assertIn("--bare", args)
        self.assertEqual(args.count("--add-dir"), 2)
        self.assertIn("--output-format", args)
        self.assertIn("stream-json", args)
        self.assertIn("hello", args)
        self.assertIn("--verbose", args)

    def test_start_attaches_existing_live_session_and_records_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, records, _, _ = self.service(tmp, tmux_existing={"work"})
            status, payload = service.start({"name": "work", "display_name": "Work"})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(payload["attached"])
        self.assertEqual(records["upserts"][0][0][0], "work")

    def test_start_creates_new_session_and_records_registry(self):
        commands = []

        def tmux_cmd(args, check=True):
            commands.append(args)
            if args[:1] == ["new-session"]:
                existing.add(args[args.index("-s") + 1])
                return 0, "", ""
            if args[:1] == ["capture-pane"]:
                return 0, "running", ""
            return 0, "", ""

        existing = set()
        with tempfile.TemporaryDirectory() as tmp:
            service, records, _, _ = self.service(tmp, tmux_cmd=tmux_cmd, tmux_existing=existing)
            status, payload = service.start({"name": "work", "new_session": True, "project_dir": tmp, "run_mode": "print", "print_prompt": "hi"})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertFalse(payload["attached"])
        self.assertEqual(payload["name"], "work-2")
        self.assertTrue(any(cmd[:1] == ["new-session"] for cmd in commands))
        self.assertEqual(records["upserts"][0][0][0], "work-2")

    def test_start_rejects_bad_launcher_project_and_tmux_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _, root = self.service(tmp)
            (root / "claude-DO.sh").write_text("broken\n", encoding="utf-8")
            bad_launcher_status, _ = service.start({"name": "work", "project_dir": tmp})

        with tempfile.TemporaryDirectory() as tmp:
            service, _, _, _ = self.service(tmp)
            bad_project_status, bad_project_payload = service.start({"name": "work", "project_dir": str(Path(tmp) / "missing")})

        with tempfile.TemporaryDirectory() as tmp:
            service, _, _, _ = self.service(tmp, tmux_cmd=lambda args, check=True: (1, "", "no tmux"))
            tmux_status, tmux_payload = service.start({"name": "work", "project_dir": tmp})

        self.assertEqual(bad_launcher_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(bad_project_status, HTTPStatus.BAD_REQUEST)
        self.assertIn("project directory", bad_project_payload["error"])
        self.assertEqual(tmux_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(tmux_payload["error"], "no tmux")

    def test_capture_send_key_send_text_stop_and_sessions(self):
        commands = []

        def tmux_cmd(args, check=True):
            commands.append(args)
            if args[:1] == ["set-buffer"]:
                return 0, "", ""
            if args[:1] == ["paste-buffer"]:
                return 0, "", ""
            if args[:1] == ["send-keys"]:
                return 0, "", ""
            if args[:1] == ["kill-session"]:
                return 1, "", ""
            return 0, "", ""

        with tempfile.TemporaryDirectory() as tmp:
            service, records, _, _ = self.service(tmp, tmux_cmd=tmux_cmd)
            capture_status, capture = service.capture("work")
            text_status, _ = service.send_text("work", "hello", enter=True)
            key_status, _ = service.send_key("work", "Enter")
            bad_key_status, bad_key = service.send_key("work", "BadKey")
            stop_status, _ = service.stop("work")
            sessions = service.sessions()

        self.assertEqual(capture_status, HTTPStatus.OK)
        self.assertIn("screen for work", capture["screen"])
        self.assertEqual(text_status, HTTPStatus.OK)
        self.assertEqual(key_status, HTTPStatus.OK)
        self.assertEqual(bad_key_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(bad_key["error"], "key is not allowed")
        self.assertEqual(stop_status, HTTPStatus.OK)
        self.assertEqual(records["upserts"][-1][0][0], "work")
        self.assertEqual(sessions, ["live-a"])
        self.assertTrue(any(cmd[:1] == ["paste-buffer"] for cmd in commands))


if __name__ == "__main__":
    unittest.main()
