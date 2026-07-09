import unittest

from src.console.handlers.auth_handler import AuthHandler


class AuthHandlerTests(unittest.TestCase):
    def handler(self, enabled=True, token="secret", role_tokens=None, session_verifier=None):
        return AuthHandler(
            auth_enabled=lambda: enabled,
            auth_token=lambda: token,
            role_tokens=lambda: role_tokens or {},
            session_verifier=session_verifier,
        )

    def test_request_token_prefers_query_then_header_then_bearer(self):
        handler = self.handler()

        self.assertEqual(
            handler.request_token("/?token=query-token", {"x-matts-console-token": "header-token", "authorization": "Bearer bearer-token"}),
            "query-token",
        )
        self.assertEqual(
            handler.request_token("/", {"x-matts-console-token": " header-token ", "authorization": "Bearer bearer-token"}),
            "header-token",
        )
        self.assertEqual(handler.request_token("/", {"authorization": "Bearer bearer-token"}), "bearer-token")
        self.assertEqual(handler.request_token("/", {}), "")

    def test_authorized_allows_disabled_auth_and_rejects_bad_tokens(self):
        self.assertTrue(self.handler(enabled=False).authorized("/", {}))
        self.assertTrue(self.handler().authorized("/?token=secret", {}))
        self.assertFalse(self.handler().authorized("/?token=wrong", {}))
        self.assertFalse(self.handler(token="").authorized("/", {}))

    def test_role_tokens_build_identity_and_permissions(self):
        handler = self.handler(role_tokens={
            "viewer-token": {"id": "viewer-a", "roles": ["viewer"]},
            "infra-token": {"id": "infra-a", "roles": ["infra_admin"]},
        })

        viewer = handler.identity("/", {"authorization": "Bearer viewer-token"})
        infra = handler.identity("/", {"authorization": "Bearer infra-token"})

        self.assertTrue(handler.authorized("/", {"authorization": "Bearer viewer-token"}))
        self.assertFalse(handler.authorized("/", {"authorization": "Bearer unknown-token"}))
        self.assertEqual(viewer["id"], "viewer-a")
        self.assertIn("view_console", viewer["permissions"])
        self.assertFalse(handler.has_permission(viewer, "dedicated_admin"))
        self.assertTrue(handler.has_permission(infra, "dedicated_admin"))
        self.assertEqual(handler.permission_for("POST", "/api/dedicated/build"), ("dedicated_admin", "dedicated.build"))

    def test_jwt_session_identity_is_authorized(self):
        handler = self.handler(session_verifier=lambda token: {
            "id": "session-user",
            "roles": ["operator"],
            "permissions": ["view_console", "tmux_control"],
            "source": "jwt-session",
            "session_id": "session-a",
        } if token == "jwt-token" else None)

        identity = handler.identity("/", {"authorization": "Bearer jwt-token"})

        self.assertTrue(handler.authorized("/", {"authorization": "Bearer jwt-token"}))
        self.assertEqual(identity["id"], "session-user")
        self.assertEqual(identity["source"], "jwt-session")
        self.assertTrue(handler.has_permission(identity, "tmux_control"))


if __name__ == "__main__":
    unittest.main()
