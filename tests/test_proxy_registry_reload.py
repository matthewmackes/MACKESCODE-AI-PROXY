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
                "context_window": 8192,
                "max_output_tokens": 2048,
                "supports_tools": True,
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
    def test_request_timeout_seconds_clamps_to_existing_proxy_ceiling(self):
        self.assertEqual(proxy._request_timeout_seconds({"request_timeout_seconds": 7}), 7)
        self.assertEqual(proxy._request_timeout_seconds({"timeout_seconds": "9"}), 9)
        self.assertEqual(proxy._request_timeout_seconds({"request_timeout_seconds": 900}), 600)
        self.assertEqual(proxy._request_timeout_seconds({"request_timeout_seconds": "bad"}), 600)

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
        self.assertEqual(available["data"][0]["context_window"], 8192)
        self.assertTrue(available["data"][0]["tool_support"])
        self.assertEqual(available["data"][0]["pricing"]["input"], 0.11)
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
        self.assertTrue(policy["slo_routing"]["enabled"])
        self.assertEqual(policy["slo_routing"]["default_goal"], "balanced")

    def test_gateway_policy_bad_schema_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy_file = Path(tmp) / "gateway-policy.json"
            policy_file.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

            policy, loaded, error = proxy._load_gateway_policy(str(policy_file))

        self.assertFalse(loaded)
        self.assertIn("schema_version", error)
        self.assertEqual(policy["schema_version"], 1)
        self.assertTrue(policy["budget"]["trace_budget_blocks"])

    def test_gateway_rate_limit_blocks_over_limit_chat_request(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "rate_limits": {
                    "enabled": True,
                    "global_per_minute": 1,
                    "per_model_per_minute": {},
                    "per_session_per_minute": {},
                },
            },
            gateway_policy_file="/tmp/policy.json",
            gateway_rate_counters={},
        )
        body = {"model": "model-a", "messages": [{"role": "user", "content": "hi"}]}

        first = proxy._gateway_rate_limit_error(server, body, "model-a", "chat", now=1000)
        second = proxy._gateway_rate_limit_error(server, body, "model-a", "chat", now=1001)

        self.assertIsNone(first)
        self.assertEqual(second["type"], "rate_limit_exceeded")
        self.assertEqual(second["scope"], "global")
        self.assertEqual(second["route"], "chat")
        self.assertEqual(second["retry_after_seconds"], 59)

    def test_gateway_rate_limit_tracks_model_and_session_limits(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "rate_limits": {
                    "enabled": True,
                    "global_per_minute": 0,
                    "per_model_per_minute": {"model-a": 1},
                    "per_session_per_minute": {"session-1": 1},
                },
            },
            gateway_policy_file="/tmp/policy.json",
            gateway_rate_counters={},
        )
        body = {
            "model": "model-a",
            "metadata": {"session_id": "session-1"},
            "messages": [{"role": "user", "content": "hi"}],
        }

        self.assertIsNone(proxy._gateway_rate_limit_error(server, body, "model-a", "chat", now=1000))
        model_block = proxy._gateway_rate_limit_error(server, body, "model-a", "chat", now=1002)
        other_model = proxy._gateway_rate_limit_error(server, body, "model-b", "chat", now=1003)

        self.assertEqual(model_block["scope"], "model")
        self.assertEqual(model_block["key"], "model-a")
        self.assertEqual(other_model["scope"], "session")
        self.assertEqual(other_model["key"], "session-1")

    def test_gateway_cache_respects_route_policy_and_returns_clone(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "cache": {
                    "enabled": True,
                    "ttl_seconds": 30,
                    "routes": {"chat": True, "images": False},
                },
            },
            gateway_policy_file="/tmp/policy.json",
            gateway_cache={},
        )
        request = {"model": "model-a", "messages": [{"role": "user", "content": "hi"}]}
        response = {"id": "msg-1", "content": [{"type": "text", "text": "hello"}], "claude_do": {"trace_id": "old"}}

        stored = proxy._gateway_cache_store(server, "chat", "model-a", request, response, now=1000)
        disabled_store = proxy._gateway_cache_store(server, "images", "model-a", request, response, now=1000)
        hit = proxy._gateway_cache_get(server, "chat", "model-a", request, now=1010)
        hit["content"][0]["text"] = "mutated"
        second_hit = proxy._gateway_cache_get(server, "chat", "model-a", request, now=1011)

        self.assertTrue(stored)
        self.assertFalse(disabled_store)
        self.assertEqual(hit["claude_do"]["gateway_cache"]["route"], "chat")
        self.assertNotIn("trace_id", second_hit["claude_do"])
        self.assertEqual(second_hit["content"][0]["text"], "hello")

    def test_gateway_cache_expires_entries(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "cache": {
                    "enabled": True,
                    "ttl_seconds": 5,
                    "routes": {"chat": True},
                },
            },
            gateway_policy_file="/tmp/policy.json",
            gateway_cache={},
        )
        request = {"model": "model-a", "messages": []}

        self.assertTrue(proxy._gateway_cache_store(server, "chat", "model-a", request, {"id": "msg"}, now=1000))
        self.assertIsNotNone(proxy._gateway_cache_get(server, "chat", "model-a", request, now=1004))
        self.assertIsNone(proxy._gateway_cache_get(server, "chat", "model-a", request, now=1006))

    def test_gateway_circuit_breaker_opens_after_threshold(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "circuit_breakers": {
                    "enabled": True,
                    "failure_window_seconds": 60,
                    "failure_threshold": 2,
                    "cooldown_seconds": 30,
                    "tracked_statuses": [502],
                },
            },
            gateway_policy_file="/tmp/policy.json",
            gateway_circuit_state={},
        )

        proxy._gateway_record_circuit_result(server, "chat", "model-a", 502, now=1000)
        self.assertIsNone(proxy._gateway_circuit_open_error(server, "chat", "model-a", now=1001))
        opened = proxy._gateway_record_circuit_result(server, "chat", "model-a", 502, now=1002)
        error = proxy._gateway_circuit_open_error(server, "chat", "model-a", now=1003)

        self.assertEqual(opened["open_until"], 1032)
        self.assertEqual(error["type"], "circuit_open")
        self.assertEqual(error["retry_after_seconds"], 29)
        self.assertIsNone(proxy._gateway_circuit_open_error(server, "chat", "model-a", now=1033))

    def test_gateway_circuit_success_clears_failures(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "circuit_breakers": {
                    "enabled": True,
                    "failure_window_seconds": 60,
                    "failure_threshold": 2,
                    "cooldown_seconds": 30,
                    "tracked_statuses": [502],
                },
            },
            gateway_policy_file="/tmp/policy.json",
            gateway_circuit_state={},
        )

        proxy._gateway_record_circuit_result(server, "images", "image-a", 502, now=1000)
        cleared = proxy._gateway_record_circuit_result(server, "images", "image-a", 200, now=1001)
        proxy._gateway_record_circuit_result(server, "images", "image-a", 502, now=1002)

        self.assertEqual(cleared["failures"], [])
        self.assertIsNone(proxy._gateway_circuit_open_error(server, "images", "image-a", now=1003))

    def test_gateway_failover_policy_selects_next_text_model(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "failover": {"enabled": True, "serverless_fallback": True},
                "retries": {"retry_statuses": [429, 500, 502]},
            },
            models=["model-a", "stable-diffusion-3.5-large", "model-b"],
        )

        self.assertTrue(proxy._gateway_should_failover(server, 502))
        self.assertFalse(proxy._gateway_should_failover(server, 403))
        self.assertEqual(proxy._gateway_text_failover_model(server, "model-a"), "model-b")
        self.assertIsNone(proxy._gateway_text_failover_model(server, "model-a", attempted={"model-a", "model-b"}))

    def test_gateway_failover_policy_can_be_disabled(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "failover": {"enabled": False, "serverless_fallback": True},
                "retries": {"retry_statuses": [502]},
            },
            models=["model-a", "model-b"],
        )

        self.assertFalse(proxy._gateway_should_failover(server, 502))

    def test_slo_routing_selects_cheapest_acceptable_model(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "slo_routing": {
                    "enabled": True,
                    "default_goal": "cheapest",
                    "router_models": ["router:slo", "router:cheapest"],
                    "constraints": {"modality": "text", "min_context_window": 4096},
                    "quality_scores": {},
                    "latency_targets_ms": {},
                },
            },
            gateway_policy_file="/tmp/policy.json",
            models=["expensive-fast", "cheap-good"],
            costs={
                "expensive-fast": {"input": 1.0, "output": 2.0},
                "cheap-good": {"input": 0.1, "output": 0.2},
            },
            model_registry_records=[
                {"id": "expensive-fast", "type": "text", "context_window": 8192, "pricing": {"input": 1.0, "output": 2.0}},
                {"id": "cheap-good", "type": "text", "context_window": 8192, "pricing": {"input": 0.1, "output": 0.2}},
            ],
            gateway_model_stats={},
        )

        selected, proof, error = proxy._gateway_select_slo_model(
            server,
            "router:cheapest",
            "router:cheapest",
            {"model": "router:cheapest", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 512},
        )

        self.assertIsNone(error)
        self.assertEqual(selected, "cheap-good")
        self.assertEqual(proof["decision"], "slo_route_selected")
        self.assertEqual(proof["selected"]["model"], "cheap-good")
        self.assertEqual(proof["goal"], "cheapest")

    def test_slo_routing_rejects_candidates_before_provider_call(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "slo_routing": {
                    "enabled": True,
                    "default_goal": "context_fit",
                    "router_models": ["router:slo"],
                    "constraints": {"modality": "text", "min_context_window": 100000},
                },
            },
            models=["small-context"],
            costs={"small-context": {"input": 0.1, "output": 0.2}},
            model_registry_records=[{"id": "small-context", "type": "text", "context_window": 4096}],
            gateway_model_stats={},
        )

        selected, proof, error = proxy._gateway_select_slo_model(
            server,
            "router:slo",
            "router:slo",
            {"model": "router:slo", "messages": [{"role": "user", "content": "hello"}]},
        )

        self.assertEqual(selected, "router:slo")
        self.assertEqual(proof["decision"], "slo_route_rejected")
        self.assertEqual(error["type"], "slo_route_rejected")
        self.assertEqual(proof["rejections"][0]["reasons"], ["context_window_too_small"])

    def test_slo_routing_uses_latency_stats_and_quality_scores(self):
        server = SimpleNamespace(
            gateway_policy={
                "enabled": True,
                "slo_routing": {
                    "enabled": True,
                    "default_goal": "fastest",
                    "router_models": ["router:fastest", "router:quality"],
                    "constraints": {"modality": "text"},
                    "quality_scores": {"slow-better": 0.99, "fast-ok": 0.2},
                },
            },
            models=["slow-better", "fast-ok"],
            costs={"slow-better": {"input": 0.1, "output": 0.2}, "fast-ok": {"input": 0.2, "output": 0.4}},
            model_registry_records=[
                {"id": "slow-better", "type": "text", "context_window": 8192},
                {"id": "fast-ok", "type": "text", "context_window": 8192},
            ],
            gateway_model_stats={
                "slow-better": {"requests": 2, "errors": 0, "total_latency_ms": 2000},
                "fast-ok": {"requests": 2, "errors": 0, "total_latency_ms": 200},
            },
        )

        fastest, fast_proof, _ = proxy._gateway_select_slo_model(server, "router:fastest", "router:fastest", {"messages": [{"role": "user", "content": "hello"}]})
        quality, quality_proof, _ = proxy._gateway_select_slo_model(server, "router:quality", "router:quality", {"messages": [{"role": "user", "content": "hello"}]})

        self.assertEqual(fastest, "fast-ok")
        self.assertEqual(fast_proof["selected"]["avg_latency_ms"], 100)
        self.assertEqual(quality, "slow-better")
        self.assertEqual(quality_proof["goal"], "highest_quality")

    def test_slo_trace_metadata_and_model_stats_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_file = Path(tmp) / "traces.jsonl"
            server = SimpleNamespace(provider="matts-value-set", trace_file=str(trace_file), gateway_model_stats={})
            proof = {"decision": "slo_route_selected", "selected_model": "model-a", "goal": "balanced"}

            stats = proxy._gateway_record_model_result(server, "model-a", 200, latency_ms=120, cost={"total_cost_usd": 0.01})
            trace = proxy._trace_request(
                server,
                action="proxy.chat",
                status=200,
                body={"messages": [{"role": "user", "content": "hello"}]},
                requested_model="router:slo",
                routed_model="model-a",
                endpoint_mode="serverless",
                routing_reason="",
                started_at=time.time(),
                extra={"gateway_policy": proof},
            )
            row = json.loads(trace_file.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(stats["avg_latency_ms"], 120)
        self.assertEqual(stats["total_cost_usd"], 0.01)
        self.assertEqual(trace["gateway_policy"]["decision"], "slo_route_selected")
        self.assertEqual(row["gateway_policy"]["selected_model"], "model-a")


if __name__ == "__main__":
    unittest.main()
