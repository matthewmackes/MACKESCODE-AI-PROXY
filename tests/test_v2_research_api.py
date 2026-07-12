import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app
from backend.v2.api import research as research_api
from backend.v2.services.research_dossier_store import ResearchDossierStore


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
            old_store = research_api.dossier_store
            try:
                for key in SEARCH_ENV:
                    os.environ.pop(key, None)
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
                os.environ["MATTS_V2_RAG_PROJECT_DIR"] = str(root)
                os.environ["MATTS_V2_RAG_CONFIG_FILE"] = str(root / "rag-config.json")
                os.environ["MATTS_V2_RAG_INDEX_FILE"] = str(root / "rag-index.json")
                os.environ["MATTS_RESEARCH_LLM_ENABLED"] = "0"
                research_api.dossier_store = ResearchDossierStore(root / "research.sqlite3", clock=lambda: 1000.0)

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
                dossier = response.json()
                self.assertEqual(dossier["schema_version"], 2)
                self.assertTrue(dossier["dossier_id"])
                self.assertEqual(dossier["query"]["text"], "gateway traces")
                self.assertEqual(dossier["query"]["source_selection_mode"], "custom")
                evidence = dossier["evidence"]
                self.assertTrue(all(row["evidence_id"] for row in evidence))
                self.assertTrue(any(row["engine"] == "bing" and row["status"] == "needs_key" for row in evidence))
                self.assertTrue(any(row["engine"] == "local-rag" and row["path"] == "docs/guide.md" for row in evidence))
                self.assertGreaterEqual(len([engine for engine in dossier["engine_runs"] if engine["kind"] == "web"]), 2)
                self.assertEqual(len(dossier["model_audit"]["outputs"]["analysts"]), 3)
                self.assertTrue(dossier["claims"])
                self.assertIn("coordinated_answer", dossier["synthesis"])
                self.assertIn("bing", dossier["synthesis"]["degraded_engines"])
                self.assertEqual(dossier["report_packet"]["dossier_id"], dossier["dossier_id"])
                self.assertTrue(any(section["id"] == "all-evidence" for section in dossier["report_packet"]["sections"]))
                coverage = {row["engine_id"]: row for row in dossier["synthesis"]["source_coverage"]}
                for engine_id in ["images", "examples", "mapping", "wikipedia", "technical-docs"]:
                    self.assertIn(engine_id, coverage)
                    self.assertTrue(coverage[engine_id]["required"])
                    self.assertIn(coverage[engine_id]["status"], {"covered", "degraded", "no_matches", "not_selected"})
                reloaded = client.get(f"/v2/research/dossiers/{dossier['dossier_id']}")
                self.assertEqual(reloaded.status_code, 200)
                self.assertEqual(reloaded.json()["dossier_id"], dossier["dossier_id"])
                pin_id = next(row["evidence_id"] for row in evidence if row["engine"] == "local-rag")
                pinned = client.patch(f"/v2/research/dossiers/{dossier['dossier_id']}/pins", json={"evidence_ids": [pin_id]})
                self.assertEqual(pinned.status_code, 200)
                self.assertEqual(pinned.json()["pinned_evidence_ids"], [pin_id])
                report = client.get(f"/v2/research/dossiers/{dossier['dossier_id']}/report")
                self.assertEqual(report.status_code, 200)
                self.assertEqual(report.json()["pinned_evidence_ids"], [pin_id])
                self.assertTrue(any(section["id"] == "pinned-evidence" and section["items"] for section in report.json()["sections"]))
                invalid_pin = client.patch(f"/v2/research/dossiers/{dossier['dossier_id']}/pins", json={"evidence_ids": ["missing"]})
                self.assertEqual(invalid_pin.status_code, 400)
            finally:
                research_api.dossier_store = old_store
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
