import unittest

from src.console.utils.errors import error_category, error_payload, json_error, normalize_error_payload, route_not_found_details, route_suggestions


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

    def test_normalize_error_payload_preserves_context(self):
        payload = normalize_error_payload({"error": {"message": "provider denied"}, "request_id": "req"}, 403)

        self.assertEqual(payload["error"], "provider denied")
        self.assertEqual(payload["message"], "provider denied")
        self.assertEqual(payload["category"], "permission")
        self.assertEqual(payload["status"], 403)
        self.assertEqual(payload["request_id"], "req")
        self.assertEqual(payload["details"]["upstream_error"], {"message": "provider denied"})

    def test_route_suggestions_rank_nearby_paths_without_query_values(self):
        suggestions = route_suggestions("/api/proxy/stats?token=secret", ["/api/proxy/status", "/api/models", "/api/traces"])
        details = route_not_found_details("/api/proxy/stats?token=secret", "GET", ["/api/proxy/status", "/api/models"])

        self.assertEqual(suggestions[0], "/api/proxy/status")
        self.assertEqual(details["path"], "/api/proxy/stats")
        self.assertEqual(details["method"], "GET")
        self.assertEqual(details["suggested_endpoints"][0], "/api/proxy/status")
        self.assertNotIn("secret", str(details))

    def test_route_not_found_details_report_exact_path_method_mismatch(self):
        details = route_not_found_details(
            "/v2/research/search?token=secret",
            "GET",
            ["/v2/research/search", "/v2/research/engines"],
            route_methods={"/v2/research/search": ["POST"], "/v2/research/engines": ["GET"]},
        )

        self.assertTrue(details["method_mismatch"])
        self.assertEqual(details["path"], "/v2/research/search")
        self.assertEqual(details["method"], "GET")
        self.assertEqual(details["allowed_methods"], ["POST"])
        self.assertEqual(details["suggested_endpoints"], ["/v2/research/search"])
        self.assertEqual(details["nearby_endpoints"], [{"path": "/v2/research/search", "methods": ["POST"]}])
        self.assertIn("Use POST /v2/research/search", details["suggested_fix"])
        self.assertNotIn("secret", str(details))

    def test_route_not_found_details_preserve_nearby_other_method_routes(self):
        details = route_not_found_details(
            "/v2/research/searc",
            "GET",
            ["/v2/research/search", "/v2/research/engines", "/v2/research"],
            route_methods={"/v2/research/search": ["POST"], "/v2/research/engines": ["GET"], "/v2/research": ["GET"]},
        )

        self.assertIn("/v2/research", details["suggested_endpoints"])
        self.assertIn({"path": "/v2/research/search", "methods": ["POST"]}, details["nearby_endpoints"])
        self.assertIn({"path": "/v2/research/search", "methods": ["POST"]}, details["other_method_endpoints"])


if __name__ == "__main__":
    unittest.main()
