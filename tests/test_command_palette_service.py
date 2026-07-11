import unittest

from src.console.services.command_palette import CommandPaletteService


class CommandPaletteServiceTests(unittest.TestCase):
    def test_search_filters_commands_and_marks_context_ready(self):
        service = CommandPaletteService(clock=lambda: 1000.0)

        payload = service.payload(query="snapshot", actor={"permissions": ["tmux_control"]}, context={"session": "work"})

        self.assertEqual(payload["commands"][0]["id"], "agent.snapshot")
        self.assertTrue(payload["commands"][0]["available"])
        self.assertTrue(payload["commands"][0]["context_ready"])
        self.assertEqual(payload["shortcut"], "Ctrl+K or Command+K")

    def test_permissions_hide_dispatch_for_unallowed_actor(self):
        service = CommandPaletteService(clock=lambda: 1000.0)
        payload = service.payload(query="sync", actor={"permissions": ["view_console"]}, context={})

        self.assertFalse(payload["commands"][0]["available"])
        with self.assertRaisesRegex(PermissionError, "permission denied"):
            service.dispatch({"id": "proxy.sync", "actor": {"permissions": ["view_console"]}})

    def test_contextual_commands_require_matching_context(self):
        service = CommandPaletteService(clock=lambda: 1000.0)

        missing = service.payload(query="replay", actor={"permissions": ["replay_run"]}, context={})
        ready = service.payload(query="replay", actor={"permissions": ["replay_run"]}, context={"trace_id": "trace-a"})

        self.assertFalse(missing["commands"][0]["available"])
        self.assertFalse(missing["commands"][0]["context_ready"])
        self.assertTrue(ready["commands"][0]["available"])
        self.assertTrue(ready["commands"][0]["context_ready"])
        with self.assertRaisesRegex(ValueError, "context unavailable"):
            service.dispatch({"id": "trace.replay", "actor": {"permissions": ["replay_run"]}, "context": {}})

    def test_dispatch_returns_action_and_audits(self):
        audits = []
        service = CommandPaletteService(append_audit=lambda *args, **kwargs: audits.append((args, kwargs)), clock=lambda: 1000.0)

        result = service.dispatch({"id": "traces.open", "actor": {"id": "viewer", "permissions": ["view_traces"]}, "context": {"trace_id": "trace-a"}})

        self.assertEqual(result["action"]["type"], "console_view")
        self.assertEqual(result["command"]["id"], "traces.open")
        self.assertEqual(audits[0][0][0], "command_palette.dispatch")
        self.assertEqual(audits[0][1]["permission"], "view_traces")

    def test_unknown_command_raises(self):
        with self.assertRaisesRegex(ValueError, "command not found"):
            CommandPaletteService().dispatch({"id": "missing", "actor": {"permissions": ["*"]}})


if __name__ == "__main__":
    unittest.main()
