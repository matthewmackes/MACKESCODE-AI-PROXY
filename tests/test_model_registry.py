import importlib.util
import json
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


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


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

    def test_default_models_follow_active_registry_lists(self):
        with patch.object(studio, "TEXT_MODELS", ["registry-text-a", "registry-text-b"]), \
             patch.object(studio, "IMAGE_MODELS", ["registry-image-a"]):
            self.assertEqual(studio.default_text_model(), "registry-text-a")
            self.assertEqual(studio.default_image_model(), "registry-image-a")

    def test_catalog_pricing_from_item_detects_common_pricing_shapes(self):
        self.assertEqual(
            studio.catalog_pricing_from_item({"pricing": {"input_usd_per_million": "0.12", "output_usd_per_million": 0.34}}),
            {"input": 0.12, "output": 0.34},
        )
        self.assertEqual(
            studio.catalog_pricing_from_item({"rates": {"price_per_image": "0.08"}}),
            {"image": 0.08},
        )

    def test_documented_serverless_pricing_comes_from_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            path.write_text(json.dumps({"models": [
                {"id": "priced", "type": "text", "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "local", "type": "text", "serverless": False, "pricing": {"input": 9}},
                {"id": "unpriced", "type": "text", "serverless": True},
            ]}), encoding="utf-8")
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}):
                pricing = studio.documented_serverless_pricing()

        self.assertEqual(pricing, {"priced": {"input": 0.1, "output": 0.2}})

    def test_registry_round_trip_filters_route_enabled_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            access_state = Path(tmp) / "model-access-state.json"
            models = [
                {"id": "allowed-text", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "forbidden-text", "type": "text", "enabled": True, "serverless": True, "access_status": "forbidden", "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "image-ok", "type": "image", "enabled": True, "pricing": {"image": 0.08}},
                {"id": "disabled-text", "type": "text", "enabled": False, "pricing": {"input": 0.1}},
            ]

            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path), "MATTS_MODEL_ACCESS_STATE_FILE": str(access_state)}):
                saved = studio.save_model_registry(models)
                raw = json.loads(path.read_text(encoding="utf-8"))
                access_state.write_text(json.dumps({"schema_version": 1, "models": {
                    "allowed-text": {"access_status": "ok", "last_checked_at": 1000},
                    "forbidden-text": {"access_status": "forbidden", "last_checked_at": 1000},
                }}), encoding="utf-8")
                all_models = studio.load_model_registry(include_disabled=True)
                active = studio.load_model_registry(include_disabled=False)

        self.assertEqual([model["id"] for model in saved], ["allowed-text", "forbidden-text", "image-ok", "disabled-text"])
        self.assertEqual([model["id"] for model in all_models], ["allowed-text", "forbidden-text", "image-ok", "disabled-text"])
        self.assertEqual([model["id"] for model in active], ["allowed-text", "image-ok"])
        self.assertEqual(raw["schema_version"], 1)
        self.assertNotIn("access_status", json.dumps(raw))

    def test_registry_status_reports_legacy_and_malformed_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            path.write_text(json.dumps([{"id": "legacy-text", "type": "text", "enabled": True}]), encoding="utf-8")
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}):
                legacy = studio.model_registry_status(include_disabled=True)

            self.assertTrue(legacy["valid"])
            self.assertEqual(legacy["models"][0]["id"], "legacy-text")
            self.assertIn("legacy list format", legacy["issues"][0])

            path.write_text(json.dumps({"schema_version": 99, "models": []}), encoding="utf-8")
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}):
                malformed = studio.model_registry_status(include_disabled=True)

            self.assertTrue(malformed["valid"])
            self.assertFalse(malformed["snapshot_valid"])
            self.assertEqual(malformed["source"], "operational_db")
            self.assertIn("schema_version 99 is not supported", malformed["issues"][0])
            self.assertEqual(malformed["models"][0]["id"], "legacy-text")

    def test_admin_save_models_payload_persists_edits_and_syncs_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            models = [
                {"id": "admin-text", "display_name": "Admin Text", "type": "text", "enabled": True, "pricing": {"input": 0.12, "output": 0.34}, "aliases": ["admin"]},
                {"id": "admin-image", "display_name": "Admin Image", "type": "image", "enabled": False, "pricing": {"image": 0.08}},
            ]
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}), \
                 patch.object(studio, "proxy_sync_payload", return_value={"in_sync": True}) as sync:
                status, payload = studio.save_models_payload({"models": models})
                saved = studio.load_model_registry(include_disabled=True)

        self.assertEqual(status, studio.HTTPStatus.OK)
        self.assertEqual([model["id"] for model in saved], ["admin-text", "admin-image"])
        self.assertEqual(payload["models"][0]["display_name"], "Admin Text")
        self.assertEqual(payload["active_text_models"], ["admin-text"])
        self.assertEqual(payload["proxy_sync"], {"in_sync": True})
        sync.assert_called_once_with(force=True)

    def test_admin_save_models_payload_rejects_duplicate_ids_and_no_text_model(self):
        duplicate = [{"id": "dup", "type": "text", "enabled": True}, {"id": "dup", "type": "text", "enabled": True}]
        status, payload = studio.save_models_payload({"models": duplicate})
        self.assertEqual(status, studio.HTTPStatus.BAD_REQUEST)
        self.assertIn("unique", payload["error"])

        status, payload = studio.save_models_payload({"models": [{"id": "image-only", "type": "image", "enabled": True}]})
        self.assertEqual(status, studio.HTTPStatus.BAD_REQUEST)
        self.assertIn("text model", payload["error"])

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

    def test_catalog_sync_adds_new_models_with_default_policy_and_metadata(self):
        catalog = {
            "ok": True,
            "source": "test",
            "fetched_at": 1,
            "payload": {
                "data": [
                    {"id": "openai-cheap-new", "created": 1, "owned_by": "openai", "context_length": 8192, "max_output_tokens": 256},
                    {"id": "expensive-new", "created": 2, "owned_by": "digitalocean", "context_length": 4096, "max_output_tokens": 128},
                ]
            },
        }
        pricing = {
            "openai-cheap-new": {"input": 0.10, "output": 0.40},
            "expensive-new": {"input": 0.10, "output": 0.50},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}), \
                 patch.object(studio, "serverless_catalog_payload", return_value=catalog), \
                 patch.object(studio, "documented_serverless_pricing", return_value=pricing), \
                 patch.object(studio, "proxy_sync_payload", return_value={"in_sync": True}):
                result = studio.sync_serverless_model_catalog(force=True, validate_access=False)
                models = {model["id"]: model for model in studio.load_model_registry(include_disabled=True)}
                options = {item["id"]: item for item in studio.model_options("text", include_disabled=True)}
                active_ids = [model["id"] for model in studio.load_model_registry(include_disabled=False)]

        self.assertEqual(result["added"], 2)
        self.assertTrue(models["openai-cheap-new"]["enabled"])
        self.assertFalse(models["expensive-new"]["enabled"])
        self.assertEqual(models["openai-cheap-new"]["pricing_source"], "digitalocean_pricing_docs_2026_07_01")
        self.assertEqual(models["openai-cheap-new"]["context_window"], 8192)
        self.assertEqual(models["openai-cheap-new"]["display_name"], "Openai Cheap New")
        self.assertEqual(options["openai-cheap-new"]["brand"], "OpenAI")
        self.assertIn("Training origin: United States", options["openai-cheap-new"]["label"])
        self.assertIn("$0.4 output / 1M tokens", options["openai-cheap-new"]["cost_label"])
        self.assertIn("style", options["openai-cheap-new"])
        self.assertIn("new_until", options["openai-cheap-new"])
        self.assertNotIn("openai-cheap-new", active_ids)

    def test_serverless_registry_entry_prefers_catalog_pricing_then_existing_registry(self):
        catalog_priced = studio.serverless_registry_entry({
            "id": "openai-gpt-5-nano",
            "pricing": {"input": 0.01, "output": 0.02},
        })
        self.assertEqual(catalog_priced["pricing"], {"input": 0.01, "output": 0.02})
        self.assertEqual(catalog_priced["pricing_source"], "digitalocean_catalog")

        existing_priced = studio.serverless_registry_entry(
            {"id": "unknown-catalog-model"},
            existing={"pricing": {"input": 0.33, "output": 0.44}, "pricing_source": "operator"},
        )
        self.assertEqual(existing_priced["pricing"], {"input": 0.33, "output": 0.44})
        self.assertEqual(existing_priced["pricing_source"], "operator")

    def test_fetch_serverless_catalog_uses_digitalocean_models_api(self):
        captured = {}

        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["authorization"] = req.get_header("Authorization")
            captured["user_agent"] = req.get_header("User-agent")
            captured["timeout"] = timeout
            return FakeResponse({"data": [{"id": "model-a"}]})

        with patch.object(studio, "read_model_access_token", return_value="token-123"), \
             patch.object(studio, "urlopen", side_effect=fake_urlopen):
            payload = studio.fetch_serverless_catalog()

        self.assertEqual(payload["data"][0]["id"], "model-a")
        self.assertEqual(captured["url"], "https://inference.do-ai.run/v1/models")
        self.assertEqual(captured["method"], "GET")
        self.assertEqual(captured["authorization"], "Bearer token-123")
        self.assertEqual(captured["user_agent"], "matts-console/1.0")
        self.assertEqual(captured["timeout"], 30)

    def test_serverless_catalog_payload_uses_fresh_cache_and_falls_back_after_fetch_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "serverless-model-catalog.json"
            fresh_cache = {"ok": True, "fetched_at": studio.time.time(), "source": "cache", "payload": {"data": [{"id": "cached"}]}, "error": ""}
            path.write_text(json.dumps(fresh_cache), encoding="utf-8")
            with patch.dict(studio.os.environ, {"MATTS_SERVERLESS_CATALOG_CACHE_FILE": str(path)}), \
                 patch.object(studio, "fetch_serverless_catalog") as fetch:
                cached = studio.serverless_catalog_payload(force=False)
                fetch.assert_not_called()

            stale_cache = {"ok": True, "fetched_at": 1, "source": "old-cache", "payload": {"data": [{"id": "stale"}]}, "error": ""}
            path.write_text(json.dumps(stale_cache), encoding="utf-8")
            with patch.dict(studio.os.environ, {"MATTS_SERVERLESS_CATALOG_CACHE_FILE": str(path)}), \
                 patch.object(studio, "fetch_serverless_catalog", side_effect=RuntimeError("network down")):
                fallback = studio.serverless_catalog_payload(force=True)

        self.assertEqual(cached["payload"]["data"][0]["id"], "cached")
        self.assertFalse(fallback["ok"])
        self.assertEqual(fallback["source"], "cache_after_fetch_error")
        self.assertEqual(fallback["payload"]["data"][0]["id"], "stale")
        self.assertIn("network down", fallback["error"])

    def test_proxy_sync_requires_loaded_matching_registry_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            models = [{"id": "allowed-text", "type": "text", "enabled": True, "serverless": True, "access_status": "ok"}]
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}):
                studio.save_model_registry(models)
                fingerprint = studio.model_config_fingerprint()
                payload = {
                    "provider": "matts-value-set",
                    "base_url": "https://inference.do-ai.run",
                    "models": ["allowed-text"],
                    "model_config_state": {"loaded": True, "stale": False, "fingerprint": fingerprint},
                }
                with patch.object(studio, "port_open", return_value=True), \
                     patch.object(studio, "proxy_capabilities_raw", return_value=(200, payload)), \
                     patch.object(studio, "ALL_MODELS", ["allowed-text"]):
                    ok, details = studio.proxy_in_sync()

        self.assertTrue(ok)
        self.assertEqual(details["reason"], "in sync")
        self.assertEqual(details["expected_model_config"]["mtime_ns"], fingerprint["mtime_ns"])

    def test_proxy_sync_rejects_stale_registry_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            with patch.dict(studio.os.environ, {"MATTS_MODEL_CONFIG_FILE": str(path)}):
                path.write_text('{"models":[]}', encoding="utf-8")
                fingerprint = studio.model_config_fingerprint()
                payload = {
                    "provider": "matts-value-set",
                    "base_url": "https://inference.do-ai.run",
                    "models": [],
                    "model_config_state": {"loaded": True, "stale": True, "fingerprint": fingerprint},
                }
                with patch.object(studio, "port_open", return_value=True), \
                     patch.object(studio, "proxy_capabilities_raw", return_value=(200, payload)), \
                     patch.object(studio, "ALL_MODELS", []):
                    ok, details = studio.proxy_in_sync()

        self.assertFalse(ok)
        self.assertIn("not reloaded", details["reason"])

    def test_registry_sync_issue_blocks_when_selected_model_missing_from_proxy(self):
        details = {
            "reason": "proxy has not reloaded the latest model registry file",
            "expected_models": ["new-model"],
            "capabilities": {
                "models": ["old-model"],
                "model_config_state": {"loaded": True, "stale": True},
            },
        }
        with patch.object(studio, "proxy_in_sync", return_value=(False, details)):
            issue = studio.registry_sync_issue_for_model("new-model")

        self.assertTrue(issue["blocking"])
        self.assertFalse(issue["selected_model_loaded"])
        self.assertIn("not loaded", issue["message"])

    def test_registry_sync_issue_allows_when_selected_model_is_loaded(self):
        details = {
            "reason": "proxy config differs from GUI registry",
            "expected_models": ["loaded-model", "new-model"],
            "capabilities": {
                "models": ["loaded-model"],
                "model_config_state": {"loaded": True, "stale": False},
            },
        }
        with patch.object(studio, "proxy_in_sync", return_value=(False, details)):
            issue = studio.registry_sync_issue_for_model("loaded-model")

        self.assertFalse(issue["blocking"])
        self.assertTrue(issue["selected_model_loaded"])
        self.assertIn("can continue", issue["message"])

    def test_serverless_chat_blocks_stale_selected_model_before_proxy_request(self):
        issue = {
            "blocking": True,
            "message": "The selected model 'new-model' is not loaded by the Claude Code proxy yet.",
            "selected_model": "new-model",
            "selected_model_loaded": False,
            "proxy_models": ["old-model"],
            "reason": "proxy stale",
        }
        with patch.object(studio, "TEXT_MODELS", ["new-model"]), \
             patch.object(studio, "start_proxy_if_needed", return_value=None), \
             patch.object(studio, "registry_sync_issue_for_model", return_value=issue), \
             patch.object(studio, "request_json") as request_json:
            status, payload = studio.serverless_chat_completion({"messages": [{"role": "user", "content": "hi"}]}, "new-model")

        self.assertEqual(status, studio.HTTPStatus.CONFLICT)
        self.assertEqual(payload["routing"]["reason"], "registry_sync_blocked")
        self.assertEqual(payload["registry_sync"]["selected_model"], "new-model")
        request_json.assert_not_called()

    def test_serverless_chat_attaches_nonblocking_registry_warning(self):
        issue = {
            "blocking": False,
            "message": "The proxy registry needs attention, but the selected model is already loaded.",
            "selected_model": "loaded-model",
            "selected_model_loaded": True,
            "proxy_models": ["loaded-model"],
            "reason": "proxy stale",
        }
        response = {"content": [{"type": "text", "text": "hello"}], "usage": {"input_tokens": 1, "output_tokens": 1}}
        with patch.object(studio, "TEXT_MODELS", ["loaded-model"]), \
             patch.object(studio, "start_proxy_if_needed", return_value=None), \
             patch.object(studio, "registry_sync_issue_for_model", return_value=issue), \
             patch.object(studio, "request_json", return_value=(200, response)):
            status, payload = studio.serverless_chat_completion({"messages": [{"role": "user", "content": "hi"}]}, "loaded-model")

        self.assertEqual(status, studio.HTTPStatus.OK)
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["routing"]["reason"], "registry_sync_warning")
        self.assertEqual(payload["routing"]["registry_sync"]["selected_model"], "loaded-model")


if __name__ == "__main__":
    unittest.main()
