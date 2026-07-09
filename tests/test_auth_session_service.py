import tempfile
import unittest
from pathlib import Path

from src.console.services.auth_session import AuthSessionService


class AuthSessionServiceTests(unittest.TestCase):
    def service(self, tmp, now=None, secret="owner-secret"):
        now = now if now is not None else [1000]
        return AuthSessionService(
            session_file=lambda: Path(tmp) / "auth-sessions.json",
            secret=lambda: secret,
            clock=lambda: now[0],
            token_urlsafe=lambda size: "tok-%d-%s" % (size, now[0]),
            access_ttl=60,
            refresh_ttl=600,
        ), now

    def test_create_verify_refresh_and_revoke_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, now = self.service(tmp)
            created = service.create_session({"id": "operator-a", "roles": ["operator"], "permissions": ["view_console"], "source": "role-token"})

            verified = service.verify_access(created["access_token"])
            self.assertEqual(verified["id"], "operator-a")
            self.assertEqual(verified["source"], "jwt-session")
            self.assertEqual(verified["permissions"], ["view_console"])
            self.assertEqual(len(service.active_sessions()), 1)

            now[0] = 1010
            refreshed_status, refreshed = service.refresh(created["refresh_token"])
            self.assertEqual(refreshed_status, 200)
            self.assertNotEqual(refreshed["refresh_token"], created["refresh_token"])
            replay_status, _ = service.refresh(created["refresh_token"])
            self.assertEqual(replay_status, 401)

            self.assertTrue(service.revoke(created["session_id"]))
            self.assertIsNone(service.verify_access(refreshed["access_token"]))
            self.assertEqual(service.active_sessions(), [])

    def test_invalid_signature_and_expiration_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, now = self.service(tmp)
            created = service.create_session({"id": "owner", "roles": ["owner"], "permissions": ["*"]})
            other, _ = self.service(tmp, now=now, secret="rotated-secret")

            self.assertIsNone(other.verify_access(created["access_token"]))
            now[0] = 2000
            self.assertIsNone(service.verify_access(created["access_token"]))
            status, _ = service.refresh(created["refresh_token"])
            self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
