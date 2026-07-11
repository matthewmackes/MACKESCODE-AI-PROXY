import tempfile
import unittest
from pathlib import Path

from backend.v2.services import research_search as research_search_module
from backend.v2.services.research_search import ResearchSearchService


class FakeRagService:
    def __init__(self, matches=None):
        self.matches = matches or []

    def payload(self):
        documents = len(self.matches)
        return {"index": [{"id": "docs", "name": "Docs", "documents": documents, "files": 1 if documents else 0}] if documents else []}

    def search(self, request):
        return {"query": request.get("query"), "collections": ["docs"] if self.matches else [], "matches": self.matches}


class FakeShowcaseService:
    def payload(self):
        return {
            "models": [
                {
                    "id": "openai-gpt-oss-20b",
                    "display_name": "Openai Gpt Oss 20b",
                    "type": "text",
                    "company": "OpenAI",
                    "family": "GPT",
                    "training_nation": "United States",
                    "route_enabled": True,
                    "context_window": 128000,
                    "pricing": {"input": 0.05, "output": 0.45},
                    "cost_label": "$0.05 input / 1M tokens ; $0.45 output / 1M tokens",
                    "use_case": "fast general research",
                },
                {
                    "id": "mimo-v2.5",
                    "display_name": "Mimo V2.5",
                    "type": "text",
                    "company": "Xiaomi",
                    "family": "MiMo",
                    "training_nation": "China",
                    "route_enabled": True,
                    "context_window": 128000,
                    "pricing": {"input": 0.105, "output": 0.28},
                    "cost_label": "$0.105 input / 1M tokens ; $0.28 output / 1M tokens",
                    "use_case": "fast independent analysis",
                },
                {
                    "id": "mistral-3-14B",
                    "display_name": "Mistral 3 14B",
                    "type": "text",
                    "company": "Mistral AI",
                    "family": "Mistral",
                    "training_nation": "France",
                    "route_enabled": True,
                    "context_window": 128000,
                    "pricing": {"input": 0.2, "output": 0.2},
                    "cost_label": "$0.2 input / 1M tokens ; $0.2 output / 1M tokens",
                    "use_case": "fast verification",
                },
                {
                    "id": "nvidia-nemotron-3-super-120b",
                    "display_name": "Nvidia Nemotron 3 Super 120b",
                    "type": "text",
                    "company": "NVIDIA",
                    "family": "Nemotron",
                    "training_nation": "United States",
                    "route_enabled": True,
                    "context_window": 128000,
                    "pricing": {"input": 0.21, "output": 0.455},
                    "cost_label": "$0.21 input / 1M tokens ; $0.455 output / 1M tokens",
                    "use_case": "fast coordination",
                },
                {
                    "id": "expensive-slow",
                    "display_name": "Expensive Slow",
                    "type": "text",
                    "company": "Example",
                    "family": "Slow",
                    "training_nation": "United States",
                    "route_enabled": True,
                    "context_window": 128000,
                    "pricing": {"input": 0.49, "output": 0.51},
                    "cost_label": "$0.51 output / 1M tokens",
                    "use_case": "too expensive",
                },
                {
                    "id": "deepseek-r1",
                    "display_name": "DeepSeek R1",
                    "type": "text",
                    "company": "DeepSeek",
                    "family": "Reasoning",
                    "training_nation": "China",
                    "route_enabled": True,
                    "context_window": 128000,
                    "use_case": "reasoning and research",
                }
            ]
        }


class V2ResearchSearchServiceTests(unittest.TestCase):
    def test_missing_keys_degrade_without_blocking_catalog_and_local_results(self):
        service = ResearchSearchService(
            env={},
            clock=lambda: 1000.0,
            rag_service_factory=lambda: FakeRagService(matches=[{
                "score": 19,
                "collection_id": "docs",
                "collection_name": "Docs",
                "path": "docs/research.md",
                "chunk": 2,
                "text": "DigitalOcean LLM model routing notes.",
            }]),
            showcase_service=FakeShowcaseService(),
        )

        payload = service.search({"query": "DigitalOcean LLM models", "engines": ["bing", "digitalocean-docs", "local-rag"], "limit": 10})

        statuses = {row["engine"]: row["status"] for row in payload["results"]}
        self.assertEqual(statuses["bing"], "needs_key")
        self.assertGreaterEqual(len([engine for engine in payload["engines"] if engine["kind"] == "web"]), 2)
        self.assertIn("DigitalOcean model: DeepSeek R1", [row["title"] for row in payload["results"]])
        self.assertTrue(any(row["engine"] == "local-rag" and row["status"] == "local" for row in payload["results"]))
        self.assertIn("bing", payload["synthesis"]["degraded_engines"])
        self.assertEqual(len(payload["model_outputs"]["analysts"]), 3)
        self.assertIn("coordinated", str(payload["synthesis"]).lower())

    def test_research_team_uses_fast_low_cost_models(self):
        service = ResearchSearchService(
            env={"MATTS_RESEARCH_LLM_ENABLED": "0"},
            clock=lambda: 1000.0,
            rag_service_factory=lambda: FakeRagService(),
            showcase_service=FakeShowcaseService(),
        )

        strategy = service.model_strategy()
        roles = strategy["analysts"] + [strategy["coordinator"]]

        self.assertEqual(len(strategy["analysts"]), 3)
        self.assertTrue(all(role["status"] == "selected" for role in roles))
        self.assertTrue(all(float(role["max_text_price_usd"]) < 0.50 for role in roles))
        self.assertTrue(all(role["fast_response"]["eligible"] for role in roles))
        self.assertNotIn("expensive-slow", [role.get("model_id") for role in roles])

    def test_research_llm_calls_use_bounded_timeout_and_degrade_fast(self):
        calls = []

        def chat_completion(payload):
            calls.append(payload)
            return 504, {"message": "research role timed out"}

        service = ResearchSearchService(
            env={"MATTS_RESEARCH_LLM_TIMEOUT_SECONDS": "7"},
            clock=lambda: 1000.0,
            rag_service_factory=lambda: FakeRagService(),
            showcase_service=FakeShowcaseService(),
            chat_completion=chat_completion,
        )

        payload = service.search({"query": "DigitalOcean LLM models", "engines": ["digitalocean-docs"], "limit": 2})

        self.assertEqual(payload["model_strategy"]["policy"]["llm_timeout_seconds"], 7)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(call["request_timeout_seconds"] == 7 for call in calls))
        self.assertTrue(all(call["trace_status_on_error"] == "fallback" for call in calls))
        self.assertTrue(all(call["trace_origin"] == "research_llm" for call in calls))
        self.assertEqual(len(payload["model_outputs"]["analysts"]), 3)
        self.assertTrue(all(row["status"] == "fallback" for row in payload["model_outputs"]["analysts"]))
        self.assertEqual(payload["model_outputs"]["coordinator"]["status"], "fallback")
        self.assertIn("research role timed out", payload["model_outputs"]["analysts"][0]["text"])

    def test_explicit_empty_or_invalid_engine_selection_is_rejected(self):
        service = ResearchSearchService(
            env={"MATTS_RESEARCH_LLM_ENABLED": "0"},
            clock=lambda: 1000.0,
            rag_service_factory=lambda: FakeRagService(),
            showcase_service=FakeShowcaseService(),
        )

        with self.assertRaisesRegex(ValueError, "at least one valid research engine"):
            service.search({"query": "DigitalOcean LLM models", "engines": []})
        with self.assertRaisesRegex(ValueError, "at least one valid research engine"):
            service.search({"query": "DigitalOcean LLM models", "engines": ["not-a-real-engine"]})

    def test_research_source_classes_include_images_examples_maps_wikipedia_and_docs(self):
        calls = []

        def fake_http_get(url, headers=None, timeout=8.0):
            calls.append(url)
            if "nominatim.openstreetmap.org" in url:
                return {"features": [{
                    "properties": {"geocoding": {"label": "New York, United States"}},
                    "geometry": {"coordinates": [-74.006, 40.7128]},
                }]}
            if "prop=pageimages" in url or "prop=pageimages%7Cinfo" in url:
                return {"query": {"pages": {"1": {
                    "title": "Research image",
                    "fullurl": "https://en.wikipedia.org/wiki/Research",
                    "thumbnail": {"source": "https://upload.wikimedia.org/research.jpg"},
                }}}}
            if "list=search" in url:
                return {"query": {"search": [{
                    "title": "Research",
                    "pageid": 42,
                    "snippet": "Research <span>gateway</span> article",
                    "timestamp": "2026-07-09T00:00:00Z",
                }]}}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "backend").mkdir()
            (root / "frontend" / "src" / "api").mkdir(parents=True)
            (root / "README.md").write_text("Research gateway usage example.\n```bash\ncurl /v2/research/search\n```\n", encoding="utf-8")
            (root / "docs" / "research.md").write_text("Technical documentation for research gateway evidence.\n", encoding="utf-8")
            (root / "backend" / "research_service.py").write_text("# research gateway technical implementation\n", encoding="utf-8")

            old_project_dir = research_search_module.PROJECT_DIR
            try:
                research_search_module.PROJECT_DIR = root
                service = ResearchSearchService(
                    env={"MATTS_RESEARCH_LLM_ENABLED": "0"},
                    clock=lambda: 1000.0,
                    http_get=fake_http_get,
                    rag_service_factory=lambda: FakeRagService(),
                    showcase_service=FakeShowcaseService(),
                )

                payload = service.search({
                    "query": "research gateway New York",
                    "engines": ["images", "examples", "mapping", "wikipedia", "technical-docs"],
                    "limit": 3,
                })
            finally:
                research_search_module.PROJECT_DIR = old_project_dir

        result_engines = {row["engine"] for row in payload["results"]}
        for engine_id in ["images", "examples", "mapping", "wikipedia", "technical-docs"]:
            self.assertIn(engine_id, result_engines)
            self.assertGreaterEqual(payload["synthesis"]["source_engine_counts"][engine_id], 1)
        coverage = {row["engine_id"]: row for row in payload["synthesis"]["source_coverage"]}
        for engine_id in ["images", "examples", "mapping", "wikipedia", "technical-docs"]:
            self.assertIn(engine_id, coverage)
            self.assertTrue(coverage[engine_id]["required"])
            self.assertEqual(coverage[engine_id]["status"], "covered")
            self.assertGreaterEqual(coverage[engine_id]["usable_count"], 1)
        self.assertGreaterEqual(len([engine for engine in payload["engines"] if engine["kind"] == "web"]), 2)
        self.assertEqual(payload["synthesis"]["source_kind_counts"]["image"], 1)
        self.assertEqual(payload["synthesis"]["source_kind_counts"]["mapping"], 1)
        self.assertGreaterEqual(payload["synthesis"]["source_kind_counts"]["examples"], 1)
        self.assertGreaterEqual(payload["synthesis"]["source_kind_counts"]["technical_docs"], 1)
        self.assertTrue(any(row.get("thumbnail_url") for row in payload["results"] if row["engine"] == "images"))
        self.assertTrue(any(row.get("coordinates") == "40.71280, -74.00600" for row in payload["results"]))
        self.assertIn("Wikipedia", payload["synthesis"]["summary"])
        self.assertTrue(any("w/api.php" in url for url in calls))

    def test_required_source_coverage_marks_custom_omissions_without_overriding_selection(self):
        service = ResearchSearchService(
            env={"MATTS_RESEARCH_LLM_ENABLED": "0"},
            clock=lambda: 1000.0,
            rag_service_factory=lambda: FakeRagService(),
            showcase_service=FakeShowcaseService(),
        )

        payload = service.search({"query": "gateway routing", "engines": ["bing"], "limit": 2})

        engine_ids = [engine["id"] for engine in payload["engines"]]
        self.assertIn("bing", engine_ids)
        self.assertIn("google", engine_ids)
        self.assertNotIn("images", engine_ids)
        coverage = {row["engine_id"]: row for row in payload["synthesis"]["source_coverage"]}
        for engine_id in ["images", "examples", "mapping", "wikipedia", "technical-docs"]:
            self.assertEqual(coverage[engine_id]["status"], "not_selected")
            self.assertEqual(coverage[engine_id]["result_count"], 0)
            self.assertEqual(coverage[engine_id]["usable_count"], 0)

    def test_live_provider_adapters_normalize_without_leaking_keys(self):
        calls = []

        def fake_http_get(url, headers=None, timeout=8.0):
            calls.append({"url": url, "headers": headers or {}, "timeout": timeout})
            if "bing.microsoft.com" in url:
                return {"webPages": {"value": [{"name": "Bing title", "url": "https://example.com/bing", "snippet": "Bing snippet", "dateLastCrawled": "2026-07-09"}]}}
            if "googleapis.com" in url:
                return {"items": [{"title": "Google title", "link": "https://example.com/google", "snippet": "Google snippet"}]}
            if "search.brave.com" in url:
                return {"web": {"results": [{"title": "Brave title", "url": "https://example.com/brave", "description": "Brave snippet", "age": "1 day ago"}]}}
            return {}

        env = {
            "BING_SEARCH_API_KEY": "bing-secret",
            "GOOGLE_SEARCH_API_KEY": "google-secret",
            "GOOGLE_SEARCH_CX": "google-cx",
            "BRAVE_SEARCH_API_KEY": "brave-secret",
        }
        service = ResearchSearchService(
            env=env,
            clock=lambda: 1000.0,
            http_get=fake_http_get,
            rag_service_factory=lambda: FakeRagService(),
            showcase_service=FakeShowcaseService(),
        )

        payload = service.search({"query": "gateway routing", "engines": ["bing", "google", "brave"], "limit": 3})

        self.assertEqual([row["status"] for row in payload["results"]], ["live", "live", "live"])
        self.assertEqual([row["title"] for row in payload["results"]], ["Bing title", "Google title", "Brave title"])
        self.assertEqual(payload["synthesis"]["live_result_count"], 3)
        self.assertNotIn("bing-secret", str(payload))
        self.assertNotIn("google-secret", str(payload))
        self.assertNotIn("brave-secret", str(payload))
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
