import os
import unittest

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2CreateApiTests(unittest.TestCase):
    def test_create_payload_exposes_research_source_classes(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        try:
            os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
            client = TestClient(create_app())

            response = client.get("/v2/create")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            source_classes = {row["id"]: row for row in payload["research_source_classes"]}
            for source_id in ["images", "examples", "mapping", "wikipedia", "technical-docs"]:
                self.assertIn(source_id, source_classes)
                self.assertEqual(source_classes[source_id]["engine_id"], source_id)
                self.assertTrue(source_classes[source_id]["label"])
                self.assertTrue(source_classes[source_id]["detail"])
        finally:
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth


if __name__ == "__main__":
    unittest.main()
