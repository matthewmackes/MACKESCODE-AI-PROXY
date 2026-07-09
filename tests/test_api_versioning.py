import unittest

from src.console.handlers.api_versioning import api_version_headers, api_version_info, requested_header_version


class ApiVersioningTests(unittest.TestCase):
    def test_versioned_path_normalizes_to_legacy_dispatch_path(self):
        info = api_version_info("/api/v1/models", {})

        self.assertEqual(info["path"], "/api/models")
        self.assertEqual(info["version"], "v1")
        self.assertFalse(info["deprecated"])
        self.assertFalse(info["unsupported"])
        self.assertEqual(api_version_headers(info)["x-matts-api-version"], "v1")

    def test_legacy_path_is_v1_with_deprecation_headers(self):
        info = api_version_info("/api/models", {})
        headers = api_version_headers(info)

        self.assertEqual(info["path"], "/api/models")
        self.assertEqual(info["version"], "v1")
        self.assertTrue(info["deprecated"])
        self.assertEqual(headers["deprecation"], "true")
        self.assertIn("/api/v1/", headers["warning"])

    def test_header_and_vendor_accept_version_negotiation(self):
        self.assertEqual(requested_header_version({"x-matts-api-version": "V1"}), "v1")
        self.assertEqual(
            requested_header_version({"accept": "application/vnd.matts-value-set.v1+json"}),
            "v1",
        )

    def test_unsupported_versions_are_reported(self):
        path_info = api_version_info("/api/v2/models", {})
        header_info = api_version_info("/api/models", {"x-matts-api-version": "v9"})

        self.assertTrue(path_info["unsupported"])
        self.assertEqual(path_info["requested_version"], "v2")
        self.assertTrue(header_info["unsupported"])
        self.assertEqual(header_info["requested_version"], "v9")


if __name__ == "__main__":
    unittest.main()
