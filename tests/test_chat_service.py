import unittest
from http import HTTPStatus

from src.console.services.chat import ChatRoutingService


class MemoryTraceService:
    def __init__(self):
        self.records = []

    def summarize_messages(self, messages):
        rows = messages if isinstance(messages, list) else []
        last = ""
        for msg in rows:
            if isinstance(msg, dict) and msg.get("role") == "user":
                last = msg.get("content") or ""
        return {"message_count": len(rows), "last_user_preview": last[:160], "last_user_chars": len(last)}

    def append(self, record):
        record = dict(record)
        record.setdefault("trace_id", "trace-memory")
        self.records.append(record)
        return record


class ChatRoutingServiceTests(unittest.TestCase):
    def service(self, request_json=None, text_models=None, registry_issue=None, dedicated=False, trace_service=None, dedicated_response=None, model_policy=None):
        started = []
        dedicated_polls = []

        service = ChatRoutingService(
            start_proxy_if_needed=lambda: started.append(True),
            request_json=request_json or (lambda url, payload=None, timeout=240, method="POST": (200, {
                "content": [{"type": "text", "text": "Hello"}, {"type": "text", "text": " world"}],
                "usage": {"input_tokens": 2},
            })),
            proxy_url=lambda path: "http://proxy.local" + path,
            text_models=lambda: text_models or ["model-a"],
            default_text_model=lambda: "model-a",
            registry_sync_issue_for_model=lambda model: registry_issue,
            chat_cost_usd=lambda model, input_text, output_text: {
                "model": model,
                "input": input_text,
                "output": output_text,
                "total_cost_usd": 0.01,
            },
            is_dedicated_model=lambda model: dedicated and model == "dedicated-a",
            dedicated_status_payload=lambda poll=True: dedicated_polls.append(poll),
            dedicated_chat_completion=lambda data, cfg: dedicated_response or (HTTPStatus.OK, {"text": "dedicated", "cfg": cfg}),
            load_dedicated_config=lambda: {"state": "active"},
            model_policy_for_model=model_policy or (lambda model: {}),
            trace_service=trace_service,
        )
        return service, started, dedicated_polls

    def test_serverless_success_shapes_payload_and_cost(self):
        requests = []

        def request_json(url, payload=None, timeout=240, method="POST"):
            requests.append((url, payload, timeout, method))
            return 200, {"content": [{"text": "Hi"}, {"text": " there"}], "usage": {"output_tokens": 2}}

        service, started, _ = self.service(request_json=request_json)
        status, payload = service.serverless_completion({
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": "9000",
            "temperature": "0.2",
        }, "model-a")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(started, [True])
        self.assertEqual(requests[0][0], "http://proxy.local/v1/messages")
        self.assertEqual(requests[0][1]["max_tokens"], 8192)
        self.assertEqual(requests[0][1]["temperature"], 0.2)
        self.assertEqual(payload["text"], "Hi there")
        self.assertEqual(payload["routing"], {"requested": "model-a", "used": "model-a", "backend": "serverless"})
        self.assertEqual(payload["cost"]["input"], "hello")
        self.assertEqual(payload["cost"]["output"], "Hi there")

    def test_serverless_success_emits_trace_and_response_trace_id(self):
        traces = MemoryTraceService()
        service, _, _ = self.service(trace_service=traces)

        status, payload = service.serverless_completion({"messages": [{"role": "user", "content": "hello"}]}, "model-a")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["trace_id"], "trace-memory")
        self.assertEqual(payload["routing"]["trace_id"], "trace-memory")
        self.assertEqual(traces.records[0]["requested_model"], "model-a")
        self.assertEqual(traces.records[0]["routed_model"], "model-a")
        self.assertEqual(traces.records[0]["message_summary"]["last_user_preview"], "hello")

    def test_serverless_rejects_unknown_model_and_missing_messages(self):
        service, started, _ = self.service()
        unknown_status, unknown_payload = service.serverless_completion({"messages": [{"role": "user", "content": "hi"}]}, "missing")
        missing_status, missing_payload = service.serverless_completion({"messages": []}, "model-a")

        self.assertEqual(unknown_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(unknown_payload["error"], "unknown text model")
        self.assertEqual(missing_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(missing_payload["error"], "message is required")
        self.assertEqual(started, [True, True])

    def test_registry_blocking_issue_returns_conflict_before_proxy_request(self):
        issue = {"blocking": True, "message": "Proxy is stale"}
        called = []
        service, _, _ = self.service(registry_issue=issue, request_json=lambda *args, **kwargs: called.append(True))

        status, payload = service.serverless_completion({"messages": [{"role": "user", "content": "hi"}]}, "model-a")

        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertEqual(payload["registry_sync"], issue)
        self.assertEqual(payload["routing"]["reason"], "registry_sync_blocked")
        self.assertEqual(called, [])

    def test_registry_blocking_issue_emits_error_trace(self):
        traces = MemoryTraceService()
        issue = {"blocking": True, "message": "Proxy is stale"}
        service, _, _ = self.service(
            registry_issue=issue,
            trace_service=traces,
            request_json=lambda *args, **kwargs: self.fail("proxy should not be called"),
        )

        status, payload = service.serverless_completion({"messages": [{"role": "user", "content": "hi"}]}, "model-a")

        self.assertEqual(status, HTTPStatus.CONFLICT)
        self.assertEqual(payload["trace_id"], "trace-memory")
        self.assertEqual(traces.records[0]["status"], "error")
        self.assertEqual(traces.records[0]["routing_reason"], "registry_sync_blocked")
        self.assertEqual(traces.records[0]["gateway_policy"]["decision"], "stale_registry_protection")
        self.assertEqual(traces.records[0]["error_category"], "http_409")

    def test_forbidden_model_rejection_is_policy_visible(self):
        traces = MemoryTraceService()
        service, _, _ = self.service(
            text_models=["model-a"],
            trace_service=traces,
            model_policy=lambda model: {"decision": "access_forbidden_rejection", "model": model, "reason": "access_forbidden", "access_status": "forbidden"},
        )

        status, payload = service.serverless_completion({"messages": [{"role": "user", "content": "hi"}]}, "forbidden-model")

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(payload["routing"]["reason"], "access_forbidden")
        self.assertEqual(payload["routing"]["policy_decision"]["decision"], "access_forbidden_rejection")
        self.assertEqual(traces.records[0]["gateway_policy"]["decision"], "access_forbidden_rejection")

    def test_registry_warning_attaches_routing_detail(self):
        issue = {"blocking": False, "message": "Proxy sync warning"}
        service, _, _ = self.service(registry_issue=issue)

        status, payload = service.serverless_completion({"messages": [{"role": "user", "content": "hi"}]}, "model-a")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["routing"]["reason"], "registry_sync_warning")
        self.assertEqual(payload["routing"]["registry_sync"], issue)

    def test_general_completion_routes_to_dedicated_when_selected(self):
        service, _, dedicated_polls = self.service(dedicated=True)
        status, payload = service.completion({"model": "dedicated-a", "messages": [{"role": "user", "content": "hi"}]})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["text"], "dedicated")
        self.assertEqual(payload["cfg"], {"state": "active"})
        self.assertEqual(dedicated_polls, [True])

    def test_dedicated_budget_fallback_trace_keeps_routing_reason(self):
        traces = MemoryTraceService()
        dedicated_response = (HTTPStatus.OK, {
            "text": "serverless fallback",
            "routing": {
                "requested": "dedicated-a",
                "used": "model-a",
                "backend": "serverless",
                "reason": "budget_blocked_fallback",
            },
        })
        service, _, _ = self.service(dedicated=True, trace_service=traces, dedicated_response=dedicated_response)

        status, payload = service.completion({"model": "dedicated-a", "messages": [{"role": "user", "content": "hi"}]})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["trace_id"], "trace-memory")
        self.assertEqual(payload["routing"]["reason"], "budget_blocked_fallback")
        self.assertEqual(traces.records[0]["action"], "chat.dedicated")
        self.assertEqual(traces.records[0]["endpoint_mode"], "serverless")
        self.assertEqual(traces.records[0]["routing_reason"], "budget_blocked_fallback")
        self.assertEqual(traces.records[0]["gateway_policy"]["decision"], "budget_blocked_fallback")

    def test_proxy_get_uses_get_request(self):
        requests = []

        def request_json(url, payload=None, timeout=240, method="POST"):
            requests.append((url, payload, timeout, method))
            return 200, {"ok": True}

        service, started, _ = self.service(request_json=request_json)
        status, payload = service.proxy_get("/v1/models")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(started, [True])
        self.assertEqual(requests, [("http://proxy.local/v1/models", None, 10, "GET")])


if __name__ == "__main__":
    unittest.main()
