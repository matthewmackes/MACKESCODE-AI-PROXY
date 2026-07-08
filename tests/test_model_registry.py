import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_studio_module():
    spec = importlib.util.spec_from_file_location("image_studio_registry", ROOT / "image-studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


studio = load_studio_module()


class ModelRegistryTests(unittest.TestCase):
    def test_model_enabled_by_default_requires_all_prices_below_threshold(self):
        self.assertTrue(studio.model_enabled_by_default({"input": 0.05, "output": 0.40}))
        self.assertFalse(studio.model_enabled_by_default({"input": 0.05, "output": 0.45}))
        self.assertFalse(studio.model_enabled_by_default({"input": 0.05, "output": 0.55}))
        self.assertFalse(studio.model_enabled_by_default({}))

    def test_serverless_text_models_require_successful_access_audit_to_route(self):
        allowed = {"enabled": True, "serverless": True, "type": "text", "access_status": "ok"}
        forbidden = {"enabled": True, "serverless": True, "type": "text", "access_status": "forbidden"}
        unchecked = {"enabled": True, "serverless": True, "type": "text"}
        image = {"enabled": True, "serverless": True, "type": "image"}

        self.assertTrue(studio.model_route_enabled(allowed))
        self.assertFalse(studio.model_route_enabled(forbidden))
        self.assertFalse(studio.model_route_enabled(unchecked))
        self.assertTrue(studio.model_route_enabled(image))

    def test_registry_round_trip_filters_route_enabled_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            models = [
                {"id": "allowed-text", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "forbidden-text", "type": "text", "enabled": True, "serverless": True, "access_status": "forbidden", "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "image-ok", "type": "image", "enabled": True, "pricing": {"image": 0.08}},
                {"id": "disabled-text", "type": "text", "enabled": False, "pricing": {"input": 0.1}},
            ]

            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}):
                saved = studio.save_model_registry(models)
                all_models = studio.load_model_registry(include_disabled=True)
                active = studio.load_model_registry(include_disabled=False)

        self.assertEqual([model["id"] for model in saved], ["allowed-text", "forbidden-text", "image-ok", "disabled-text"])
        self.assertEqual([model["id"] for model in all_models], ["allowed-text", "forbidden-text", "image-ok", "disabled-text"])
        self.assertEqual([model["id"] for model in active], ["allowed-text", "image-ok"])

    def test_registry_normalization_drops_token_endpoint_and_secret_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            models = [{
                "id": "safe-model",
                "type": "text",
                "enabled": True,
                "pricing": {"input": 0.1},
                "access_token": "secret",
                "endpoint": "https://example.invalid",
                "public_endpoint_fqdn": "example.invalid",
                "private_endpoint_fqdn": "internal.example.invalid",
                "api_key": "secret",
                "password": "secret",
            }]

            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}):
                saved = studio.save_model_registry(models)
                raw_text = path.read_text(encoding="utf-8")

        forbidden_keys = {"access_token", "endpoint", "public_endpoint_fqdn", "private_endpoint_fqdn", "api_key", "password"}
        self.assertTrue(saved)
        self.assertTrue(forbidden_keys.isdisjoint(saved[0].keys()))
        for key in forbidden_keys:
            self.assertNotIn(key, raw_text)
        self.assertIn("safe-model", raw_text)

    def test_selectable_text_models_includes_managed_dedicated_model_even_when_disabled(self):
        registry = [
            {"id": "serverless-ok", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1}},
            {"id": "dedicated-building", "type": "text", "enabled": False, "dedicated": {"managed": True, "state": "provisioning"}, "pricing": {"hourly": 2.59}},
        ]
        with patch.object(studio, "TEXT_MODELS", ["serverless-ok"]), \
             patch.object(studio, "load_model_registry", return_value=registry):
            self.assertEqual(studio.selectable_text_models(), ["serverless-ok", "dedicated-building"])

    def test_model_options_enrich_cost_origin_status_and_disabled_state(self):
        registry = [
            {"id": "openai-gpt-5-nano", "display_name": "GPT 5 Nano", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.05, "output": 0.40}},
            {"id": "haiku-4-5", "display_name": "Haiku 4.5", "type": "text", "enabled": True, "serverless": True, "access_status": "forbidden", "pricing": {"input": 0.25, "output": 1.25}},
        ]
        with patch.object(studio, "load_model_registry", return_value=registry):
            options = studio.model_options("text", include_disabled=True)

        by_id = {item["id"]: item for item in options}
        self.assertIn("OpenAI", by_id["openai-gpt-5-nano"]["label"])
        self.assertIn("Training origin: United States", by_id["openai-gpt-5-nano"]["label"])
        self.assertIn("$0.05 input / 1M tokens", by_id["openai-gpt-5-nano"]["cost_label"])
        self.assertFalse(by_id["openai-gpt-5-nano"]["disabled"])
        self.assertTrue(by_id["haiku-4-5"]["disabled"])
        self.assertIn("Unavailable for this key", by_id["haiku-4-5"]["label"])

    def test_catalog_sync_marks_missing_serverless_models_removed(self):
        catalog = {
            "ok": True,
            "source": "test",
            "fetched_at": 1,
            "payload": {
                "data": [
                    {"id": "still-listed", "created": 1, "owned_by": "digitalocean", "max_output_tokens": 128},
                    {"id": "new-cheap", "created": 2, "owned_by": "digitalocean", "max_output_tokens": 128},
                ]
            },
        }
        initial = [
            {"id": "still-listed", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1, "output": 0.2}},
            {"id": "removed-model", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1, "output": 0.2}},
            {"id": "dedicated-building", "type": "text", "enabled": False, "dedicated": {"managed": True}, "pricing": {"hourly": 2.59}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}), \
                 patch.object(studio, "serverless_catalog_payload", return_value=catalog), \
                 patch.object(studio, "proxy_sync_payload", return_value={"in_sync": True}):
                studio.save_model_registry(initial)
                result = studio.sync_serverless_model_catalog(force=True, validate_access=False)
                models = {model["id"]: model for model in studio.load_model_registry(include_disabled=True)}
                active_ids = [model["id"] for model in studio.load_model_registry(include_disabled=False)]

        self.assertEqual(result["removed"], 1)
        self.assertIn("new-cheap", models)
        self.assertFalse(models["removed-model"]["enabled"])
        self.assertEqual(models["removed-model"]["access_status"], "removed")
        self.assertIn("no longer lists", models["removed-model"]["last_error"])
        self.assertNotIn("removed-model", active_ids)
        self.assertIn("dedicated-building", models)


if __name__ == "__main__":
    unittest.main()
