import unittest

from src.console.utils.errors import error_category, error_payload, json_error


class ErrorUtilsTests(unittest.TestCase):
    def test_error_payload_keeps_legacy_error_string_and_adds_metadata(self):
        payload = error_payload("missing value", 400, code="missing_value", details={"field": "id"})

        self.assertEqual(payload["error"], "missing value")
        self.assertEqual(payload["message"], "missing value")
        self.assertEqual(payload["code"], "missing_value")
        self.assertEqual(payload["category"], "client")
        self.assertEqual(payload["status"], 400)
        self.assertEqual(payload["details"], {"field": "id"})

    def test_error_categories_cover_common_http_classes(self):
        self.assertEqual(error_category(401), "auth")
        self.assertEqual(error_category(403), "permission")
        self.assertEqual(error_category(404), "not_found")
        self.assertEqual(error_category(422), "client")
        self.assertEqual(error_category(502), "server")

    def test_json_error_returns_status_and_payload(self):
        status, payload = json_error(404, "not here", code="missing")

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not here")
        self.assertEqual(payload["code"], "missing")


if __name__ == "__main__":
    unittest.main()
