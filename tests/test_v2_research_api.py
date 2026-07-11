import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app


SEARCH_ENV = (
    "BING_SEARCH_API_KEY",
    "BING_SEARCH_KEY",
    "AZURE_BING_SEARCH_KEY",
    "GOOGLE_SEARCH_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_PROGRAMMABLE_SEARCH_API_KEY",
    "GOOGLE_SEARCH_CX",
    "GOOGLE_CSE_ID",
    "GOOGLE_PROGRAMMABLE_SEARCH_CX",
    "BRAVE_SEARCH_API_KEY",
    "BRAVE_SEARCH_TOKEN",
)


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2ResearchApiTests(unittest.TestCase):
    def test_research_catalog_alias_exposes_source_classes(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        try:
            os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
            client = TestClient(create_app())

            canonical = client.get("/v2/research")
            alias = client.get("/v2/research/engines")

            self.assertEqual(canonical.status_code, 200)
            self.assertEqual(alias.status_code, 200)
            canonical_payload = canonical.json()
            alias_payload = alias.json()
            self.assertEqual(
                [engine["id"] for engine in canonical_payload["engines"]],
                [engine["id"] for engine in alias_payload["engines"]],
            )
            source_classes = {row["id"]: row for row in alias_payload["source_classes"]}
            for source_id in ["images", "examples", "mapping", "wikipedia", "technical-docs"]:
                self.assertIn(source_id, source_classes)
                self.assertEqual(source_classes[source_id]["engine_id"], source_id)
                self.assertTrue(source_classes[source_id]["label"])
                self.assertTrue(source_classes[source_id]["detail"])
            self.assertEqual(source_classes["images"]["kind"], "image")
            self.assertEqual(source_classes["examples"]["kind"], "examples")
            self.assertEqual(source_classes["mapping"]["kind"], "mapping")
            self.assertEqual(source_classes["wikipedia"]["kind"], "knowledge")
            self.assertEqual(source_classes["technical-docs"]["kind"], "technical_docs")
        finally:
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth

    def test_research_search_uses_local_rag_and_degrades_missing_external_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("Gateway traces prove routing decisions for research.\n", encoding="utf-8")
            env_keys = (
                "MATTS_CONSOLE_AUTH_ENABLED",
                "MATTS_V2_RAG_PROJECT_DIR",
                "MATTS_V2_RAG_CONFIG_FILE",
                "MATTS_V2_RAG_INDEX_FILE",
                "MATTS_RESEARCH_LLM_ENABLED",
            ) + SEARCH_ENV
            old_env = {key: os.environ.get(key) for key in env_keys}
            try:
                for key in SEARCH_ENV:
                    os.environ.pop(key, None)
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
                os.environ["MATTS_V2_RAG_PROJECT_DIR"] = str(root)
                os.environ["MATTS_V2_RAG_CONFIG_FILE"] = str(root / "rag-config.json")
                os.environ["MATTS_V2_RAG_INDEX_FILE"] = str(root / "rag-index.json")
                os.environ["MATTS_RESEARCH_LLM_ENABLED"] = "0"

                client = TestClient(create_app())
                client.post("/v2/run/rag/config", json={
                    "collections": [{
                        "id": "docs",
                        "name": "Docs",
                        "include": ["docs/**/*.md"],
                        "exclude": [],
                        "max_file_bytes": 10000,
                    }]
                })
                client.post("/v2/run/rag/index", json={"collection_id": "docs"})

                payload = client.get("/v2/research")
                response = client.post("/v2/research/search", json={
                    "query": "gateway traces",
                    "engines": ["bing", "local-rag"],
                })

                self.assertEqual(payload.status_code, 200)
                engines = {engine["id"]: engine for engine in payload.json()["engines"]}
                self.assertEqual(engines["bing"]["status"], "needs_key")
                self.assertEqual(engines["local-rag"]["status"], "indexed")
                self.assertIn("model_strategy", payload.json())

                self.assertEqual(response.status_code, 200)
                results = response.json()["results"]
                self.assertTrue(any(row["engine"] == "bing" and row["status"] == "needs_key" for row in results))
                self.assertTrue(any(row["engine"] == "local-rag" and row["path"] == "docs/guide.md" for row in results))
                self.assertGreaterEqual(len([engine for engine in response.json()["engines"] if engine["kind"] == "web"]), 2)
                self.assertEqual(len(response.json()["model_outputs"]["analysts"]), 3)
                self.assertIn("coordinated_answer", response.json()["synthesis"])
                self.assertIn("bing", response.json()["synthesis"]["degraded_engines"])
                coverage = {row["engine_id"]: row for row in response.json()["synthesis"]["source_coverage"]}
                for engine_id in ["images", "examples", "mapping", "wikipedia", "technical-docs"]:
                    self.assertIn(engine_id, coverage)
                    self.assertTrue(coverage[engine_id]["required"])
                    self.assertIn(coverage[engine_id]["status"], {"covered", "degraded", "no_matches", "not_selected"})
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    def test_research_search_rejects_explicit_empty_engine_selection(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        old_llm = os.environ.get("MATTS_RESEARCH_LLM_ENABLED")
        try:
            os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
            os.environ["MATTS_RESEARCH_LLM_ENABLED"] = "0"
            client = TestClient(create_app())

            response = client.post("/v2/research/search", json={
                "query": "DigitalOcean LLM models",
                "engines": [],
            })

            self.assertEqual(response.status_code, 400)
            detail = response.json()["detail"]
            self.assertEqual(detail["code"], "invalid_engines")
            self.assertIn("at least one valid research engine", detail["message"])
        finally:
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth
            if old_llm is None:
                os.environ.pop("MATTS_RESEARCH_LLM_ENABLED", None)
            else:
                os.environ["MATTS_RESEARCH_LLM_ENABLED"] = old_llm


if __name__ == "__main__":
    unittest.main()
