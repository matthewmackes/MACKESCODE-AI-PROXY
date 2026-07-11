"""Handler-level tests for do-anthropic-proxy.py image budget/allowlist gating
and the request-thread fail-safe."""
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_proxy_module():
    spec = importlib.util.spec_from_file_location("do_anthropic_proxy_image", ROOT / "do-anthropic-proxy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proxy = load_proxy_module()


def make_server(tmp, models=("stable-diffusion-3.5-large",), budgets=None, usage_rows=()):
    cost_file = Path(tmp) / "usage.jsonl"
    budget_file = Path(tmp) / "budgets.json"
    cost_file.write_text("".join(json.dumps(r) + "\n" for r in usage_rows), encoding="utf-8")
    budget_file.write_text(json.dumps(budgets or {}), encoding="utf-8")
    return SimpleNamespace(
        models=list(models),
        model_aliases={},
        model_registry_records=[{"id": m, "type": "image", "enabled": True} for m in models],
        cost_file=str(cost_file),
        budget_file=str(budget_file),
        provider="test",
        log_file=str(Path(tmp) / "proxy.jsonl"),
        images_url="http://upstream.invalid/v1/images/generations",
        default_model="stable-diffusion-3.5-large",
        costs={},
    )


class FakeImageHandler(proxy.Handler):
    def __init__(self, server, path, body, headers=None):
        self.server = server
        self.path = path
        self._body = body
        self.headers = headers or {}
        self.responses = []
        self._responded = False

    def _refresh_models(self, force=False):
        pass

    def _refresh_gateway_policy(self):
        pass

    def _read_json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return dict(self._body)

    def _token(self):
        return "test-token"

    def _json(self, status, payload):
        self._responded = True
        self.responses.append((status, payload))


def make_chat_server(tmp, models=("deepseek-3.2",), budgets=None, usage_rows=()):
    cost_file = Path(tmp) / "usage.jsonl"
    budget_file = Path(tmp) / "budgets.json"
    cost_file.write_text("".join(json.dumps(r) + "\n" for r in usage_rows), encoding="utf-8")
    budget_file.write_text(json.dumps(budgets or {}), encoding="utf-8")
    return SimpleNamespace(
        models=list(models),
        model_aliases={},
        model_registry_records=[{"id": m, "type": "text", "enabled": True} for m in models],
        cost_file=str(cost_file),
        budget_file=str(budget_file),
        usage_aggregator=proxy._UsageAggregator(),
        provider="test",
        log_file=str(Path(tmp) / "proxy.jsonl"),
        trace_file=str(Path(tmp) / "traces.jsonl"),
        chat_url="http://upstream.invalid/v1/chat/completions",
        default_model="deepseek-3.2",
        costs={"deepseek-3.2": {"input": 1.0, "output": 2.0}},
        capabilities={},
        gateway_policy=proxy.DEFAULT_GATEWAY_POLICY,
        gateway_cache={},
        gateway_circuit_state={},
        gateway_rate_counters={},
        gateway_policy_loaded=True,
    )


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeStreamResp:
    def __init__(self, status_code, lines, text=""):
        self.status_code = status_code
        self._lines = lines
        self.text = text

    def iter_lines(self):
        for line in self._lines:
            yield line if isinstance(line, bytes) else line.encode("utf-8")


class StreamHandler(proxy.Handler):
    def __init__(self, server, path, body):
        self.server = server
        self.path = path
        self._body = body
        self._responded = False
        self.wfile = io.BytesIO()
        self._headers = []

    def _refresh_models(self, force=False):
        pass

    def _refresh_gateway_policy(self):
        pass

    def _read_json(self):
        return dict(self._body)

    def _token(self):
        return "t"

    def send_response(self, code, message=None):
        self._status = code

    def send_header(self, k, v):
        self._headers.append((k, v))

    def end_headers(self):
        pass

    def _json(self, status, payload):
        self._responded = True
        self.wfile.write(json.dumps(payload).encode("utf-8"))
        self._status = status


class StreamingTests(unittest.TestCase):
    def _sse(self, wire):
        # Parse the emitted Anthropic SSE bytes into (event, data-dict) pairs.
        out = []
        blocks = wire.decode("utf-8").split("\n\n")
        for b in blocks:
            if "event:" not in b:
                continue
            ev = None
            data = None
            for line in b.splitlines():
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
            out.append((ev, data))
        return out

    def test_streaming_forwards_text_deltas_incrementally(self):
        lines = [
            'data: {"choices":[{"delta":{"role":"assistant","content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2}}',
            'data: [DONE]',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            handler = StreamHandler(server, "/v1/messages", {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "hi"}], "stream": True})
            with patch.object(proxy.requests, "post", return_value=FakeStreamResp(200, lines)), \
                    patch.object(proxy, "_trace_request", return_value={"trace_id": "t"}):
                handler.do_POST()
            events = self._sse(handler.wfile.getvalue())
            cost_log = Path(server.cost_file).read_text().strip()
        names = [e for e, _ in events]
        self.assertEqual(names[0], "message_start")
        self.assertIn("content_block_start", names)
        deltas = [d["delta"]["text"] for e, d in events if e == "content_block_delta" and d["delta"].get("type") == "text_delta"]
        self.assertEqual(deltas, ["Hel", "lo"])  # two separate deltas, not one burst
        self.assertEqual(names[-1], "message_stop")
        stop = [d for e, d in events if e == "message_delta"][0]
        self.assertEqual(stop["delta"]["stop_reason"], "end_turn")
        # cost tracked for budget (a record was appended for the streamed request)
        self.assertTrue(cost_log)

    def test_streaming_tool_call_emits_input_json_delta(self):
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"get_weather","arguments":"{\\"city\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"NYC\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
            'data: [DONE]',
        ]
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            handler = StreamHandler(server, "/v1/messages", {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "w?"}], "stream": True})
            with patch.object(proxy.requests, "post", return_value=FakeStreamResp(200, lines)), \
                    patch.object(proxy, "_trace_request", return_value={"trace_id": "t"}):
                handler.do_POST()
            events = self._sse(handler.wfile.getvalue())
        starts = [d for e, d in events if e == "content_block_start" and d["content_block"]["type"] == "tool_use"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["content_block"]["name"], "get_weather")
        partials = "".join(d["delta"]["partial_json"] for e, d in events if e == "content_block_delta" and d["delta"].get("type") == "input_json_delta")
        self.assertEqual(json.loads(partials), {"city": "NYC"})
        stop = [d for e, d in events if e == "message_delta"][0]
        self.assertEqual(stop["delta"]["stop_reason"], "tool_use")

    def test_streaming_upstream_error_falls_back_to_json_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            handler = StreamHandler(server, "/v1/messages", {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "hi"}], "stream": True})
            with patch.object(proxy.requests, "post", return_value=FakeStreamResp(503, [], text="upstream down")), \
                    patch.object(proxy, "_trace_request", return_value={"trace_id": "t"}), \
                    patch.object(proxy, "_attach_trace", side_effect=lambda payload, trace: payload):
                handler.do_POST()
            body = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(handler._status, 503)
        self.assertEqual(body["type"], "error")


class MessageTranslationTests(unittest.TestCase):
    def run_chat(self, server, body, upstream):
        handler = FakeImageHandler(server, "/v1/messages", body)
        with patch.object(proxy.requests, "post", return_value=upstream), \
                patch.object(proxy, "_trace_request", return_value={"trace_id": "t"}), \
                patch.object(proxy, "_attach_trace", side_effect=lambda payload, trace: payload):
            handler.do_POST()
        return handler.responses[-1]

    def test_openai_completion_is_translated_to_anthropic_message(self):
        upstream = FakeResp(200, {
            "id": "cmpl-1",
            "choices": [{"message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            status, payload = self.run_chat(server, {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}, upstream)
        self.assertEqual(status, 200)
        self.assertEqual(payload["type"], "message")
        self.assertEqual(payload["role"], "assistant")
        self.assertEqual(payload["content"][0]["type"], "text")
        self.assertEqual(payload["content"][0]["text"], "hello there")
        self.assertEqual(payload["stop_reason"], "end_turn")
        self.assertEqual(payload["usage"]["input_tokens"], 10)
        self.assertEqual(payload["usage"]["output_tokens"], 5)

    def test_openai_tool_call_is_translated_to_tool_use_block(self):
        upstream = FakeResp(200, {
            "id": "cmpl-2",
            "choices": [{
                "message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'}}
                ]},
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        })
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            status, payload = self.run_chat(server, {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "weather?"}], "max_tokens": 50}, upstream)
        self.assertEqual(status, 200)
        tool_uses = [b for b in payload["content"] if b.get("type") == "tool_use"]
        self.assertEqual(len(tool_uses), 1)
        self.assertEqual(tool_uses[0]["name"], "get_weather")
        self.assertEqual(tool_uses[0]["input"], {"city": "NYC"})
        self.assertEqual(payload["stop_reason"], "tool_use")

    def test_over_budget_chat_is_blocked_before_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp, budgets={"total_usd": 0.01}, usage_rows=[{"ts": 1_900_000_000, "cost": {"total_cost_usd": 0.5}}])
            # requests.post must never be called; if it is, this errors loudly.
            handler = FakeImageHandler(server, "/v1/messages", {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "hi"}]})
            with patch.object(proxy.requests, "post", side_effect=AssertionError("upstream must not be called when over budget")), \
                    patch.object(proxy, "_trace_request", return_value={"trace_id": "t"}), \
                    patch.object(proxy, "_attach_trace", side_effect=lambda payload, trace: payload):
                handler.do_POST()
            status, payload = handler.responses[-1]
        self.assertEqual(status, 402)
        self.assertEqual(payload["error"]["type"], "budget_exceeded")


class ProxyInboundAuthTests(unittest.TestCase):
    def test_loopback_bind_remains_compatible_without_token(self):
        allowed, reason = proxy._proxy_bind_allowed("127.0.0.1", "", False)
        self.assertTrue(allowed)
        self.assertEqual(reason, "loopback")

    def test_non_loopback_bind_requires_token_or_explicit_override(self):
        allowed, reason = proxy._proxy_bind_allowed("0.0.0.0", "", False)
        self.assertFalse(allowed)
        self.assertIn("inbound-auth-token", reason)
        self.assertTrue(proxy._proxy_bind_allowed("0.0.0.0", "secret", False)[0])
        self.assertTrue(proxy._proxy_bind_allowed("0.0.0.0", "", True)[0])

    def test_required_inbound_token_rejects_missing_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            server.inbound_auth_token = "secret"
            handler = FakeImageHandler(server, "/v1/messages/count_tokens", {"model": "deepseek-3.2"})
            handler.do_POST()
        status, payload = handler.responses[-1]
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["type"], "unauthorized")

    def test_required_inbound_token_accepts_proxy_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            server.inbound_auth_token = "secret"
            handler = FakeImageHandler(
                server,
                "/v1/messages/count_tokens",
                {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "hello"}]},
                headers={"x-matts-proxy-token": "secret"},
            )
            handler.do_POST()
        status, payload = handler.responses[-1]
        self.assertEqual(status, 200)
        self.assertGreater(payload["input_tokens"], 0)

    def test_required_inbound_token_accepts_bearer_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_chat_server(tmp)
            server.inbound_auth_token = "secret"
            handler = FakeImageHandler(
                server,
                "/v1/messages/count_tokens",
                {"model": "deepseek-3.2", "messages": [{"role": "user", "content": "hello"}]},
                headers={"Authorization": "Bearer secret"},
            )
            handler.do_POST()
        self.assertEqual(handler.responses[-1][0], 200)


class ImageEndpointGatingTests(unittest.TestCase):
    def run_image(self, server, body):
        handler = FakeImageHandler(server, "/v1/images/generations", body)
        with patch.object(proxy, "_trace_request", return_value={"trace_id": "t"}), \
                patch.object(proxy, "_attach_trace", side_effect=lambda payload, trace: payload):
            handler.do_POST()
        return handler.responses[-1]

    def test_unknown_model_is_rejected_before_upstream_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(tmp)
            status, payload = self.run_image(server, {"model": "evil-not-configured", "prompt": "x"})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["type"], "not_found_error")

    def test_over_budget_image_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(
                tmp,
                budgets={"total_usd": 0.01},
                usage_rows=[{"ts": 1_900_000_000, "cost": {"total_cost_usd": 0.05}}],
            )
            status, payload = self.run_image(server, {"model": "stable-diffusion-3.5-large", "prompt": "x"})
        self.assertEqual(status, 402)
        self.assertEqual(payload["error"]["type"], "budget_exceeded")

    def test_configured_model_within_budget_proceeds_to_upstream(self):
        # With a valid model and no budget, gating passes and the handler reaches the
        # upstream call (which fails against the invalid URL) -> not a 404/402 rejection.
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(tmp)
            status, _ = self.run_image(server, {"model": "stable-diffusion-3.5-large", "prompt": "x"})
        self.assertNotIn(status, (402, 404))


class FailSafeTests(unittest.TestCase):
    def test_malformed_request_json_returns_502_instead_of_crashing_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(tmp)
            handler = FakeImageHandler(server, "/v1/messages", ValueError("bad json"))
            # Must not raise out of do_POST; must produce a JSON error response.
            handler.do_POST()
        self.assertTrue(handler.responses)
        status, payload = handler.responses[-1]
        self.assertEqual(status, 502)
        self.assertEqual(payload["error"]["type"], "api_error")

    def test_failsafe_does_not_double_respond_after_headers_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(tmp)
            handler = FakeImageHandler(server, "/v1/messages", {"model": "x"})
            handler._responded = True  # simulate streaming headers already flushed
            handler._fail_safe(RuntimeError("mid-stream failure"))
        # No response appended because we already committed to a response.
        self.assertEqual(handler.responses, [])


class UsageAggregatorTests(unittest.TestCase):
    def _write_rows(self, path, rows, mode="a"):
        with open(path, mode, encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_incremental_totals_match_a_full_reparse(self):
        import time as _t
        now = _t.time()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "usage.jsonl")
            rows = [{"ts": now, "cost": {"total_cost_usd": 0.10}},
                    {"ts": now, "cost": {"total_cost_usd": 0.05}}]
            self._write_rows(path, rows)
            agg = proxy._UsageAggregator()
            first = agg.totals(path)
            self.assertAlmostEqual(first["all"], 0.15, places=6)
            self.assertAlmostEqual(first["today"], 0.15, places=6)
            # Append more; a second call must only read the new bytes yet stay correct.
            self._write_rows(path, [{"ts": now, "cost": {"total_cost_usd": 0.20}}])
            second = agg.totals(path)
            self.assertAlmostEqual(second["all"], 0.35, places=6)
            # Matches an independent full re-parse.
            self.assertAlmostEqual(second["all"], proxy._usage_totals(path)["all"], places=6)

    def test_offset_advances_so_repeated_calls_do_not_double_count(self):
        import time as _t
        now = _t.time()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "usage.jsonl")
            self._write_rows(path, [{"ts": now, "cost": {"total_cost_usd": 0.10}}])
            agg = proxy._UsageAggregator()
            agg.totals(path)
            again = agg.totals(path)  # no new data
            self.assertAlmostEqual(again["all"], 0.10, places=6)

    def test_rotation_or_truncation_resets_and_reseeds(self):
        import os as _os
        import time as _t
        now = _t.time()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "usage.jsonl")
            # Seed a sizeable file, then rotate it away to a small fresh one — as
            # copytruncate (size shrinks below the offset) and as inode swap.
            self._write_rows(path, [{"ts": now, "cost": {"total_cost_usd": 0.10}} for _ in range(8)])
            agg = proxy._UsageAggregator()
            self.assertAlmostEqual(agg.totals(path)["all"], 0.80, places=6)
            _os.remove(path)  # rotation: new inode + smaller file
            self._write_rows(path, [{"ts": now, "cost": {"total_cost_usd": 0.01}}])
            after = agg.totals(path)
            self.assertAlmostEqual(after["all"], 0.01, places=6)


if __name__ == "__main__":
    unittest.main()
