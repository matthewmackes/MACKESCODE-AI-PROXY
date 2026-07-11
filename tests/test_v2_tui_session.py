import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.v2.services.proxy_cli import ProxyTuiAudit
from backend.v2.services.tui_session import GlobalTuiSession


class V2TuiSessionTests(unittest.TestCase):
    def audit_events(self, path):
        return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]

    def test_active_controller_lease_denies_competing_client_and_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            session = GlobalTuiSession(command=["/bin/false"], audit=ProxyTuiAudit(audit_path))

            first = session.acquire_control("client-a")
            second = session.acquire_control("client-b")

            self.assertEqual(first["holder"], "client-a")
            self.assertEqual(second["holder"], "client-a")
            events = self.audit_events(audit_path)
            self.assertEqual(events[0]["action"], "tui.control_acquired")
            self.assertEqual(events[1]["action"], "tui.control_denied")
            self.assertEqual(events[1]["payload"]["reason"], "lease_held")

    def test_release_denied_for_non_holder_and_force_release_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            session = GlobalTuiSession(command=["/bin/false"], audit=ProxyTuiAudit(audit_path))
            session.acquire_control("client-a")

            still_held = session.release_control("client-b")
            released = session.release_control("admin", force=True)

            self.assertEqual(still_held["holder"], "client-a")
            self.assertFalse(released["active"])
            actions = [event["action"] for event in self.audit_events(audit_path)]
            self.assertEqual(actions, ["tui.control_acquired", "tui.release_denied", "tui.control_released"])

    def test_read_only_write_is_denied_without_starting_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            session = GlobalTuiSession(command=["/bin/false"], audit=ProxyTuiAudit(audit_path))

            ok = session.write("viewer", b"x")

            self.assertFalse(ok)
            self.assertFalse(session.status()["running"])
            events = self.audit_events(audit_path)
            self.assertEqual(events[0]["action"], "tui.write_denied")
            self.assertEqual(events[0]["payload"]["reason"], "control_lease_required")

    def test_controller_write_sends_bytes_to_pty_fd(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            read_fd, write_fd = os.pipe()
            session = GlobalTuiSession(command=["/bin/false"], audit=ProxyTuiAudit(audit_path))
            session.acquire_control("client-a")
            session._master_fd = write_fd
            session.ensure_started = lambda: None
            try:
                self.assertTrue(session.write("client-a", b"hello"))
                self.assertEqual(os.read(read_fd, 5), b"hello")
            finally:
                os.close(read_fd)
                try:
                    os.close(write_fd)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
