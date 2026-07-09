import tempfile
import unittest
from pathlib import Path

from src.console.services.model_registry import ModelRegistryService


class ModelRegistryServiceTests(unittest.TestCase):
    def service(self, threshold=0.45):
        return ModelRegistryService(
            default_registry=[{"id": "fallback", "type": "text", "enabled": True, "pricing": {"input": 0.1}}],
            model_types={"text", "image", "embedding", "rerank", "audio", "video", "router", "unknown"},
            auto_enable_max_usd=threshold,
        )

    def test_normalize_drops_secret_like_endpoint_fields(self):
        model = self.service().normalize({
            "id": "safe",
            "type": "text",
            "pricing": {"input": 0.1},
            "access_token": "secret",
            "endpoint": "https://example.invalid",
            "private_endpoint_fqdn": "internal",
        })

        self.assertEqual(model["id"], "safe")
        self.assertTrue(model["enabled"])
        self.assertNotIn("access_token", model)
        self.assertNotIn("endpoint", model)
        self.assertNotIn("private_endpoint_fqdn", model)

    def test_load_save_round_trip_filters_route_enabled(self):
        service = self.service()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            service.save(path, [
                {"id": "allowed", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1}},
                {"id": "forbidden", "type": "text", "enabled": True, "serverless": True, "access_status": "forbidden", "pricing": {"input": 0.1}},
                {"id": "image", "type": "image", "enabled": True, "pricing": {"image": 0.1}},
            ])

            active = service.load(path, include_disabled=False)

        self.assertEqual([model["id"] for model in active], ["allowed", "image"])

    def test_options_enrich_brand_cost_status_and_use_case(self):
        option = self.service().enriched_option({
            "id": "openai-gpt-5-nano",
            "display_name": "GPT 5 Nano",
            "type": "text",
            "enabled": True,
            "serverless": True,
            "access_status": "ok",
            "pricing": {"input": 0.05, "output": 0.4},
        })

        self.assertEqual(option["brand"], "OpenAI")
        self.assertEqual(option["origin"], "United States")
        self.assertIn("$0.05 input / 1M tokens", option["cost_label"])
        self.assertFalse(option["disabled"])
        self.assertIn("Fast, economical", option["use_case"])

    def test_disabled_managed_dedicated_option_is_rebuildable(self):
        option = self.service().enriched_option({
            "id": "qwen3-32b-dedicated",
            "display_name": "Qwen3-32B Dedicated",
            "type": "text",
            "enabled": False,
            "pricing": {"hourly": 2.59},
            "dedicated": {
                "managed": True,
                "state": "deleted",
                "region": "tor1",
                "model_slug": "Qwen/Qwen3-32B",
                "accelerator_slug": "gpu-mi325x1-256gb",
                "hourly_usd": 2.59,
            },
        })

        self.assertTrue(option["disabled"])
        self.assertTrue(option["dedicated_rebuildable"])
        self.assertEqual(option["dedicated"]["region"], "tor1")
        self.assertEqual(option["pricing"]["hourly"], 2.59)
        self.assertIn("$2.59 / hour", option["cost_label"])
        self.assertEqual(option["policy_decision"]["decision"], "build_server_prompt")

    def test_forbidden_serverless_option_has_policy_decision(self):
        option = self.service().enriched_option({
            "id": "haiku-4-5",
            "display_name": "Haiku 4.5",
            "type": "text",
            "enabled": True,
            "serverless": True,
            "access_status": "forbidden",
            "pricing": {"input": 0.1},
        })

        self.assertTrue(option["disabled"])
        self.assertEqual(option["policy_decision"]["decision"], "access_forbidden_rejection")
        self.assertEqual(option["policy_decision"]["access_status"], "forbidden")

    def test_catalog_pricing_detects_common_shapes(self):
        pricing = self.service().catalog_pricing_from_item({
            "pricing": {
                "input_usd_per_million": "0.12",
                "output_usd_per_million": "0.34",
            },
        })

        self.assertEqual(pricing, {"input": 0.12, "output": 0.34})


if __name__ == "__main__":
    unittest.main()
