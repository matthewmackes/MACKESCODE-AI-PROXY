import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def load_proxy_module():
    spec = importlib.util.spec_from_file_location("do_anthropic_proxy_registry", ROOT / "do-anthropic-proxy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proxy = load_proxy_module()


def write_registry(path, model_id):
    path.write_text(json.dumps({
        "schema_version": 1,
        "models": [{
            "id": model_id,
            "type": "text",
            "enabled": True,
            "serverless": True,
            "access_status": "ok",
            "aliases": ["primary"],
            "pricing": {"input": 0.11, "output": 0.22},
        }]
    }), encoding="utf-8")
    now = time.time() + 0.01
    path.touch()
    return now


def write_mixed_registry(path):
    path.write_text(json.dumps({
        "schema_version": 1,
        "models": [
            {
                "id": "routeable-model",
                "display_name": "Routeable Model",
                "type": "text",
                "enabled": True,
                "serverless": True,
                "access_status": "ok",
                "aliases": ["primary"],
                "pricing": {"input": 0.11, "output": 0.22},
            },
            {
                "id": "forbidden-model",
                "display_name": "Forbidden Model",
                "type": "text",
                "enabled": True,
                "serverless": True,
                "access_status": "forbidden",
                "pricing": {"input": 0.11, "output": 0.22},
            },
            {
                "id": "disabled-image",
                "display_name": "Disabled Image",
                "type": "image",
                "enabled": False,
                "pricing": {"image": 0.08},
            },
        ]
    }), encoding="utf-8")
    path.touch()


def server_for(path):
    return SimpleNamespace(
        model_config_file=str(path),
        fallback_models=["fallback-model"],
        fallback_model_aliases={"fallback": "fallback-model"},
        fallback_costs={"fallback-model": {"input": 1.0, "output": 2.0}},
        models=["fallback-model"],
        model_aliases={"fallback": "fallback-model"},
        costs={"fallback-model": {"input": 1.0, "output": 2.0}},
        model_registry_records=[],
        default_model="fallback-model",
        model_config_loaded=False,
        model_config_fingerprint=None,
        model_config_last_check_at=0,
        model_config_last_loaded_at=0,
        model_config_last_error="",
    )


class ProxyRegistryReloadTests(unittest.TestCase):
    def test_refresh_tracks_fingerprint_and_skips_unchanged_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            write_registry(path, "model-a")
            server = server_for(path)

            proxy._refresh_model_registry(server, force=True)
            first_loaded_at = server.model_config_last_loaded_at
            proxy._refresh_model_registry(server)

        self.assertEqual(server.models, ["model-a"])
        self.assertEqual(server.model_aliases["primary"], "model-a")
        self.assertEqual(server.costs["model-a"]["input"], 0.11)
        self.assertEqual(server.model_config_last_loaded_at, first_loaded_at)
        self.assertTrue(server.model_config_loaded)

    def test_refresh_reloads_when_registry_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            write_registry(path, "model-a")
            server = server_for(path)
            proxy._refresh_model_registry(server, force=True)

            time.sleep(0.01)
            write_registry(path, "model-b")
            stale_state = proxy._model_config_state(server)
            proxy._refresh_model_registry(server)
            fresh_state = proxy._model_config_state(server)

        self.assertTrue(stale_state["stale"])
        self.assertEqual(server.models, ["model-b"])
        self.assertEqual(server.model_aliases["primary"], "model-b")
        self.assertFalse(fresh_state["stale"])
        self.assertTrue(fresh_state["loaded"])

    def test_missing_registry_reports_load_error_and_uses_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-models.json"
            server = server_for(path)
            proxy._refresh_model_registry(server, force=True)
            state = proxy._model_config_state(server)

        self.assertFalse(state["loaded"])
        self.assertIn("No such file", state["last_error"])
        self.assertEqual(server.models, ["fallback-model"])
        self.assertEqual(server.model_aliases["fallback"], "fallback-model")

    def test_unsupported_registry_schema_reports_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            path.write_text(json.dumps({"schema_version": 99, "models": []}), encoding="utf-8")
            server = server_for(path)
            proxy._refresh_model_registry(server, force=True)
            state = proxy._model_config_state(server)

        self.assertFalse(state["loaded"])
        self.assertIn("schema_version 99 is not supported", state["last_error"])
        self.assertEqual(server.models, ["fallback-model"])

    def test_models_payload_filters_available_unavailable_and_all_registry_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            write_mixed_registry(path)
            server = server_for(path)
            proxy._refresh_model_registry(server, force=True)

        available = proxy._models_payload(
            server.models,
            aliases=server.model_aliases,
            records=server.model_registry_records,
            routeable=server.models,
            availability_filter="available",
        )
        unavailable = proxy._models_payload(
            server.models,
            aliases=server.model_aliases,
            records=server.model_registry_records,
            routeable=server.models,
            availability_filter="unavailable",
        )
        all_models = proxy._models_payload(
            server.models,
            aliases=server.model_aliases,
            records=server.model_registry_records,
            routeable=server.models,
            availability_filter="all",
        )

        self.assertEqual([item["id"] for item in available["data"]], ["routeable-model", "primary"])
        self.assertTrue(available["data"][0]["available"])
        self.assertEqual({item["id"] for item in unavailable["data"]}, {"forbidden-model", "disabled-image"})
        self.assertTrue(all(not item["available"] for item in unavailable["data"]))
        self.assertEqual({item["id"] for item in all_models["data"]}, {"routeable-model", "forbidden-model", "disabled-image", "primary"})
        self.assertEqual(unavailable["available_filter"], "unavailable")

    def test_proxy_trace_request_persists_redacted_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_file = Path(tmp) / "traces.jsonl"
            server = SimpleNamespace(provider="matts-value-set", trace_file=str(trace_file))

            trace = proxy._trace_request(
                server,
                action="proxy.chat",
                status=200,
                body={"messages": [{"role": "user", "content": "hello private prompt"}]},
                requested_model="alias-a",
                routed_model="model-a",
                endpoint_mode="serverless",
                upstream_url="https://inference.do-ai.run/v1/chat/completions",
                upstream_id="chatcmpl-1",
                usage={"prompt_tokens": 3, "completion_tokens": 4},
                cost={"total_cost_usd": 0.00001},
                started_at=time.time(),
            )

            rows = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(rows[0]["trace_id"], trace["trace_id"])
        self.assertEqual(rows[0]["action"], "proxy.chat")
        self.assertEqual(rows[0]["requested_model"], "alias-a")
        self.assertEqual(rows[0]["routed_model"], "model-a")
        self.assertEqual(rows[0]["message_summary"]["message_count"], 1)
        self.assertEqual(rows[0]["message_summary"]["last_user_preview"], "hello private prompt")
        self.assertEqual(rows[0]["cost_usd"], 0.00001)

    def test_gateway_policy_loads_defaults_and_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_file = Path(tmp) / "gateway-policy.json"
            policy_file.write_text(json.dumps({
                "schema_version": 1,
                "failover": {"max_attempts": 3},
                "rate_limits": {"enabled": True, "global_per_minute": 60},
            }), encoding="utf-8")

            policy, loaded, error = proxy._load_gateway_policy(str(policy_file))

        self.assertTrue(loaded)
        self.assertEqual(error, "")
        self.assertTrue(policy["failover"]["enabled"])
        self.assertEqual(policy["failover"]["max_attempts"], 3)
        self.assertTrue(policy["rate_limits"]["enabled"])
        self.assertEqual(policy["rate_limits"]["global_per_minute"], 60)
        self.assertIn("chat", policy["cache"]["routes"])

    def test_gateway_policy_bad_schema_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_file = Path(tmp) / "gateway-policy.json"
            policy_file.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

            policy, loaded, error = proxy._load_gateway_policy(str(policy_file))

        self.assertFalse(loaded)
        self.assertIn("schema_version", error)
        self.assertEqual(policy["schema_version"], 1)
        self.assertTrue(policy["budget"]["trace_budget_blocks"])


if __name__ == "__main__":
    unittest.main()
