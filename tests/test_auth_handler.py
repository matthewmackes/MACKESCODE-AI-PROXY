import unittest

from src.console.handlers.auth_handler import AuthHandler


class AuthHandlerTests(unittest.TestCase):
    def handler(self, enabled=True, token="secret"):
        return AuthHandler(auth_enabled=lambda: enabled, auth_token=lambda: token)

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


if __name__ == "__main__":
    unittest.main()
