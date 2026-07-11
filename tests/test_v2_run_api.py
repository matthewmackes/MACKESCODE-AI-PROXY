import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2RunApiTests(unittest.TestCase):
    def test_remote_browser_origin_is_allowed_by_default(self):
        old_env = os.environ.get("MATTS_V2_CORS_ORIGINS")
        os.environ.pop("MATTS_V2_CORS_ORIGINS", None)
        try:
            client = TestClient(create_app())
            response = client.options(
                "/v2/health",
                headers={
                    "origin": "http://203.0.113.10:5173",
                    "access-control-request-method": "GET",
                },
            )
        finally:
            if old_env is None:
                os.environ.pop("MATTS_V2_CORS_ORIGINS", None)
            else:
                os.environ["MATTS_V2_CORS_ORIGINS"] = old_env

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")

    def test_configured_cors_origin_is_echoed_for_remote_browser(self):
        old_env = os.environ.get("MATTS_V2_CORS_ORIGINS")
        os.environ["MATTS_V2_CORS_ORIGINS"] = "http://console.example:5173"
        try:
            client = TestClient(create_app())
            response = client.options(
                "/v2/health",
                headers={
                    "origin": "http://console.example:5173",
                    "access-control-request-method": "GET",
                },
            )
        finally:
            if old_env is None:
                os.environ.pop("MATTS_V2_CORS_ORIGINS", None)
            else:
                os.environ["MATTS_V2_CORS_ORIGINS"] = old_env

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "http://console.example:5173")

    def test_local_rag_routes_save_index_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("Gateway routing uses traces for proof.\n", encoding="utf-8")
            old_env = {key: os.environ.get(key) for key in (
                "MATTS_CONSOLE_AUTH_ENABLED",
                "MATTS_V2_RAG_PROJECT_DIR",
                "MATTS_V2_RAG_CONFIG_FILE",
                "MATTS_V2_RAG_INDEX_FILE",
            )}
            os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
            os.environ["MATTS_V2_RAG_PROJECT_DIR"] = str(root)
            os.environ["MATTS_V2_RAG_CONFIG_FILE"] = str(root / "rag-config.json")
            os.environ["MATTS_V2_RAG_INDEX_FILE"] = str(root / "rag-index.json")
            try:
                client = TestClient(create_app())

                saved = client.post("/v2/run/rag/config", json={
                    "collections": [{
                        "id": "docs",
                        "name": "Docs",
                        "include": ["docs/**/*.md"],
                        "exclude": [],
                        "max_file_bytes": 10000,
                    }]
                })
                indexed = client.post("/v2/run/rag/index", json={"collection_id": "docs"})
                searched = client.post("/v2/run/rag/search", json={"collection_id": "docs", "query": "gateway traces", "limit": 3})

                self.assertEqual(saved.status_code, 200)
                self.assertEqual(indexed.status_code, 200)
                self.assertEqual(searched.status_code, 200)
                self.assertEqual(indexed.json()["index"]["indexed"][0]["documents"], 1)
                self.assertEqual(searched.json()["results"]["matches"][0]["path"], "docs/guide.md")
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
