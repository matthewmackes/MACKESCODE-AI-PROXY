import json
import tempfile
import time
import unittest
from pathlib import Path

from backend.v2.services.model_showcase import ModelShowcaseService


class V2ModelShowcaseServiceTests(unittest.TestCase):
    def test_payload_enriches_origin_artwork_and_whats_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            access_state = Path(tmp) / "model-access-state.json"
            now = time.time()
            path.write_text(json.dumps({
                "schema_version": 1,
                "models": [
                    {
                        "id": "deepseek-r1",
                        "display_name": "DeepSeek R1",
                        "type": "text",
                        "provider": "DigitalOcean",
                        "enabled": True,
                        "serverless": True,
                        "pricing": {"input": 0.1, "output": 0.2},
                        "created": now,
                    },
                    {
                        "id": "llama-4",
                        "display_name": "Llama 4",
                        "type": "text",
                        "provider": "DigitalOcean",
                        "enabled": False,
                        "serverless": True,
                    },
                ],
            }), encoding="utf-8")
            access_state.write_text(json.dumps({"schema_version": 1, "models": {
                "deepseek-r1": {"access_status": "ok"},
                "llama-4": {"access_status": "forbidden"},
            }}), encoding="utf-8")
            service = ModelShowcaseService(model_config=path, model_access_state=access_state, clock=lambda: 1000, read_traces=lambda limit=2000: [])

            payload = service.payload()
            whats_new = service.whats_new()

        cards = {card["id"]: card for card in payload["models"]}
        self.assertEqual(cards["deepseek-r1"]["training_nation"], "China")
        self.assertEqual(cards["deepseek-r1"]["nation_palette"]["name"], "China")
        self.assertIn("deepseek", cards["deepseek-r1"]["artwork"]["logo"])
        self.assertEqual(cards["deepseek-r1"]["artwork"]["background"], "brand_nation_panel")
        self.assertEqual(cards["deepseek-r1"]["artwork"]["render"]["mode"], "bundled_svg")
        self.assertEqual(cards["deepseek-r1"]["artwork"]["render"]["key"], "deepseek")
        self.assertIn("deepseek.com", cards["deepseek-r1"]["artwork"]["brand_url"])
        self.assertGreaterEqual(len(cards["deepseek-r1"]["artwork"]["sources"]), 3)
        self.assertIn("policy_notes", cards["deepseek-r1"]["artwork"])
        self.assertTrue(cards["deepseek-r1"]["route_enabled"])
        self.assertEqual(cards["llama-4"]["training_nation"], "United States")
        self.assertFalse(cards["llama-4"]["route_enabled"])
        self.assertGreaterEqual(whats_new["summary"]["new_models"], 1)
        self.assertTrue(whats_new["digitalocean"]["links"])

    def _write_registry(self, tmp):
        path = Path(tmp) / "models.json"
        access_state = Path(tmp) / "model-access-state.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "models": [
                {"id": "deepseek-r1", "display_name": "DeepSeek R1", "type": "text", "provider": "DigitalOcean", "enabled": True, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "llama-4", "display_name": "Llama 4", "type": "text", "provider": "DigitalOcean", "enabled": True, "serverless": True},
                {"id": "glm-4.5", "display_name": "GLM 4.5", "type": "text", "provider": "DigitalOcean", "enabled": True, "serverless": True},
            ],
        }), encoding="utf-8")
        access_state.write_text(json.dumps({"schema_version": 1, "models": {
            "deepseek-r1": {"access_status": "ok"},
            "llama-4": {"access_status": "ok"},
            "glm-4.5": {"access_status": "ok"},
        }}), encoding="utf-8")
        return path, access_state

    def _read_trace_file(self, trace_path):
        def read_traces(limit=2000):
            return [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return read_traces

    def test_model_cards_attach_measured_health_from_recent_traces(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, access_state = self._write_registry(tmp)
            trace_path = Path(tmp) / "traces.jsonl"
            trace_path.write_text("\n".join(json.dumps(row) for row in [
                {"status": "success", "requested_model": "claude-code", "routed_model": "deepseek-r1", "latency_ms": 400},
                {"status": "success", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 500},
                {"status": "success", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 600},
                {"status": "error", "requested_model": "llama-4", "routed_model": "", "latency_ms": 12000},
            ]) + "\n", encoding="utf-8")
            service = ModelShowcaseService(
                model_config=config,
                model_access_state=access_state,
                clock=lambda: 1000,
                read_traces=self._read_trace_file(trace_path),
                trace_file=lambda: trace_path,
            )

            cards = {card["id"]: card for card in service.payload()["models"]}

        self.assertEqual(cards["deepseek-r1"]["health"], {"grade": "A", "success_rate": 1.0, "p50_latency_ms": 500, "requests": 3, "measured": True})
        self.assertEqual(cards["llama-4"]["health"], {"grade": "D", "success_rate": 0.0, "p50_latency_ms": 12000, "requests": 1, "measured": True})
        self.assertEqual(cards["glm-4.5"]["health"], {"grade": None, "success_rate": None, "p50_latency_ms": None, "requests": 0, "measured": False})
        for key in (
            "id", "display_name", "type", "provider", "owned_by", "enabled", "route_enabled", "access_status",
            "pricing", "cost_label", "context_window", "max_output_tokens", "created", "new_until", "is_new",
            "family", "company", "training_nation", "nation_palette", "style", "artwork", "use_case",
            "serverless", "pricing_source", "last_error", "health",
        ):
            self.assertIn(key, cards["deepseek-r1"])

    def test_health_is_unmeasured_for_empty_or_unreadable_traces(self):
        def boom(limit=2000):
            raise OSError("trace file unavailable")

        unmeasured = {"grade": None, "success_rate": None, "p50_latency_ms": None, "requests": 0, "measured": False}
        with tempfile.TemporaryDirectory() as tmp:
            config, access_state = self._write_registry(tmp)
            empty = ModelShowcaseService(model_config=config, model_access_state=access_state, clock=lambda: 1000, read_traces=lambda limit=2000: [], trace_file=lambda: Path(tmp) / "empty.jsonl")
            unreadable = ModelShowcaseService(model_config=config, model_access_state=access_state, clock=lambda: 1000, read_traces=boom, trace_file=lambda: Path(tmp) / "missing.jsonl")

            empty_cards = empty.payload()["models"]
            unreadable_cards = unreadable.payload()["models"]

        for card in empty_cards + unreadable_cards:
            self.assertEqual(card["health"], unmeasured)

    def test_health_cache_reuses_reads_and_refreshes_when_trace_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, access_state = self._write_registry(tmp)
            trace_path = Path(tmp) / "traces.jsonl"
            trace_path.write_text("\n".join(json.dumps(row) for row in [
                {"status": "success", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 400},
                {"status": "success", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 500},
            ]) + "\n", encoding="utf-8")
            read_calls = []
            read_file = self._read_trace_file(trace_path)

            def read_traces(limit=2000):
                read_calls.append(limit)
                return read_file(limit=limit)

            service = ModelShowcaseService(
                model_config=config,
                model_access_state=access_state,
                clock=lambda: 1000,
                read_traces=read_traces,
                trace_file=lambda: trace_path,
            )

            first = {card["id"]: card for card in service.payload()["models"]}["deepseek-r1"]["health"]
            second = {card["id"]: card for card in service.payload()["models"]}["deepseek-r1"]["health"]
            self.assertEqual(first["grade"], "A")
            self.assertEqual(second, first)
            self.assertEqual(len(read_calls), 1)

            trace_path.write_text("\n".join(json.dumps(row) for row in [
                {"status": "success", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 400},
                {"status": "error", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 12000},
                {"status": "error", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 12000},
                {"status": "error", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 12000},
                {"status": "error", "requested_model": "deepseek-r1", "routed_model": "deepseek-r1", "latency_ms": 12000},
            ]) + "\n", encoding="utf-8")

            third = {card["id"]: card for card in service.payload()["models"]}["deepseek-r1"]["health"]

        self.assertEqual(third, {"grade": "D", "success_rate": 0.2, "p50_latency_ms": 12000, "requests": 5, "measured": True})
        self.assertEqual(len(read_calls), 2)

    def test_payload_records_bundled_art_when_public_logo_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            access_state = Path(tmp) / "model-access-state.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "models": [
                    {
                        "id": "glm-4.5",
                        "display_name": "GLM 4.5",
                        "type": "text",
                        "provider": "DigitalOcean",
                        "enabled": True,
                        "serverless": True,
                    },
                ],
            }), encoding="utf-8")
            access_state.write_text(json.dumps({"schema_version": 1, "models": {"glm-4.5": {"access_status": "ok"}}}), encoding="utf-8")
            service = ModelShowcaseService(model_config=path, model_access_state=access_state, clock=lambda: 1000, read_traces=lambda limit=2000: [])

            payload = service.payload()

        card = payload["models"][0]
        self.assertEqual(card["company"], "Zhipu AI")
        self.assertEqual(card["artwork"]["logo"], "")
        self.assertEqual(card["artwork"]["render"]["mode"], "bundled_svg")
        self.assertEqual(card["artwork"]["render"]["key"], "zhipu")
        self.assertEqual(card["artwork"]["sources"][0]["kind"], "fallback")
        self.assertEqual(card["artwork"]["sources"][0]["source"], "Local bundled brand art")
        self.assertIn("local bundled brand art", card["artwork"]["sources"][0]["usage_notes"])


if __name__ == "__main__":
    unittest.main()
