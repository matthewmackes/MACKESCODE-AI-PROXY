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
            service = ModelShowcaseService(model_config=path, model_access_state=access_state, clock=lambda: 1000)

            payload = service.payload()
            whats_new = service.whats_new()

        cards = {card["id"]: card for card in payload["models"]}
        self.assertEqual(cards["deepseek-r1"]["training_nation"], "China")
        self.assertEqual(cards["deepseek-r1"]["nation_palette"]["name"], "China")
        self.assertIn("deepseek", cards["deepseek-r1"]["artwork"]["logo"])
        self.assertEqual(cards["deepseek-r1"]["artwork"]["background"], "brand_nation_panel")
        self.assertIn("deepseek.com", cards["deepseek-r1"]["artwork"]["brand_url"])
        self.assertGreaterEqual(len(cards["deepseek-r1"]["artwork"]["sources"]), 3)
        self.assertIn("policy_notes", cards["deepseek-r1"]["artwork"])
        self.assertTrue(cards["deepseek-r1"]["route_enabled"])
        self.assertEqual(cards["llama-4"]["training_nation"], "United States")
        self.assertFalse(cards["llama-4"]["route_enabled"])
        self.assertGreaterEqual(whats_new["summary"]["new_models"], 1)
        self.assertTrue(whats_new["digitalocean"]["links"])

    def test_payload_records_generated_fallback_when_logo_missing(self):
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
            service = ModelShowcaseService(model_config=path, model_access_state=access_state, clock=lambda: 1000)

            payload = service.payload()

        card = payload["models"][0]
        self.assertEqual(card["company"], "Zhipu AI")
        self.assertEqual(card["artwork"]["logo"], "")
        self.assertEqual(card["artwork"]["sources"][0]["kind"], "fallback")
        self.assertIn("generated family initial", card["artwork"]["sources"][0]["usage_notes"])


if __name__ == "__main__":
    unittest.main()
