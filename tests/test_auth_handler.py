import unittest

from src.console.handlers.auth_handler import AuthHandler


class AuthHandlerTests(unittest.TestCase):
    def handler(self, enabled=True, token="secret", role_tokens=None):
        return AuthHandler(auth_enabled=lambda: enabled, auth_token=lambda: token, role_tokens=lambda: role_tokens or {})

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


if __name__ == "__main__":
    unittest.main()
