"""Chat routing helpers for serverless and Dedicated requests."""
import re
import time
from http import HTTPStatus


TOOL_PROMPT_LEAK_PATTERNS = (
    "<tools>",
    "</tools>",
    "<tool_call",
    "FunctionCall",
    "pydantic model json schema",
    "You are a function calling AI model",
)


def _chat_output_diagnostics(text, raw_response=None):
    text = text if isinstance(text, str) else ""
    raw_response = raw_response if isinstance(raw_response, dict) else {}
    warnings = []
    issue = ""
    stop_reason = str(raw_response.get("stop_reason") or raw_response.get("finish_reason") or "")
    if not text.strip() and stop_reason == "max_tokens":
        warnings.append({
            "code": "empty_max_tokens",
            "message": "The upstream model returned no visible text and stopped at the token limit.",
        })
        issue = issue or "empty_max_tokens"
    if any(pattern.lower() in text.lower() for pattern in TOOL_PROMPT_LEAK_PATTERNS):
        warnings.append({
            "code": "tool_prompt_leak",
            "message": "The model emitted function-calling XML or tool schema instructions as answer text.",
        })
        issue = issue or "tool_prompt_leak"
    empty_fences = re.fullmatch(r"\s*(?:```\s*){2,}", text or "")
    if empty_fences:
        warnings.append({
            "code": "blank_code_fences",
            "message": "The model returned only empty fenced-code blocks.",
        })
        issue = issue or "blank_code_fences"
    return {
        "warnings": warnings,
        "output_format_issue": issue,
        "stop_reason": stop_reason,
        "raw_available": bool(raw_response),
    }


class ChatRoutingService:
    """Owns chat request validation, proxy payloads, and routing metadata."""

    def __init__(
        self,
        start_proxy_if_needed,
        request_json,
        proxy_url,
        text_models,
        default_text_model,
        registry_sync_issue_for_model,
        chat_cost_usd,
        is_dedicated_model,
        dedicated_status_payload,
        dedicated_chat_completion,
        load_dedicated_config,
        model_policy_for_model=None,
        trace_service=None,
    ):
        self.start_proxy_if_needed = start_proxy_if_needed
        self.request_json = request_json
        self.proxy_url = proxy_url
        self.text_models = text_models
        self.default_text_model = default_text_model
        self.registry_sync_issue_for_model = registry_sync_issue_for_model
        self.chat_cost_usd = chat_cost_usd
        self.is_dedicated_model = is_dedicated_model
        self.dedicated_status_payload = dedicated_status_payload
        self.dedicated_chat_completion = dedicated_chat_completion
        self.load_dedicated_config = load_dedicated_config
        self.model_policy_for_model = model_policy_for_model or (lambda model: {})
        self.trace_service = trace_service

    def active_text_models(self):
        return list(self.text_models() if callable(self.text_models) else self.text_models)

    def request_timeout_seconds(self, value):
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            return 0
        return max(2, min(600, timeout)) if timeout else 0

    def trace(self, record):
        if not self.trace_service:
            return None
        return self.trace_service.append(record)

    def trace_record(self, action, data, model, started_at, status, payload=None, backend=None, reason=None):
        payload = payload if isinstance(payload, dict) else {}
        routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
        policy_decision = routing.get("policy_decision") if isinstance(routing.get("policy_decision"), dict) else {}
        route_reason = routing.get("reason") or reason or ""
        if not policy_decision and route_reason in {"budget_blocked_fallback", "registry_sync_blocked", "registry_sync_warning", "access_forbidden", "dedicated_not_online", "dedicated_not_ready"}:
            decision = {
                "registry_sync_blocked": "stale_registry_protection",
                "registry_sync_warning": "stale_registry_warning",
                "access_forbidden": "access_forbidden_rejection",
                "dedicated_not_online": "build_server_prompt",
                "dedicated_not_ready": "dedicated_wait_not_ready",
            }.get(route_reason, route_reason)
            policy_decision = {"decision": decision, "model": model, "reason": route_reason}
        cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        claude_do = raw.get("claude_do") if isinstance(raw.get("claude_do"), dict) else {}
        streaming_metrics = payload.get("streaming_metrics") if isinstance(payload.get("streaming_metrics"), dict) else claude_do.get("streaming_metrics") if isinstance(claude_do.get("streaming_metrics"), dict) else None
        upstream_id = payload.get("id") or raw.get("id")
        status_text = "success" if int(status) < 400 else "error"
        trace_status_on_error = str(data.get("trace_status_on_error") or "").lower() if isinstance(data, dict) else ""
        if int(status) >= 400 and trace_status_on_error in {"fallback", "degraded"}:
            status_text = trace_status_on_error
        record = {
            "action": action,
            "status": status_text,
            "http_status": int(status),
            "requested_model": model,
            "routed_model": routing.get("used") or (model if int(status) < 400 else None),
            "provider": "DigitalOcean",
            "endpoint_mode": routing.get("backend") or backend or "serverless",
            "routing_reason": route_reason,
            "latency_ms": int((time.time() - started_at) * 1000),
            "message_summary": self.trace_service.summarize_messages(data.get("messages") if isinstance(data, dict) else []) if self.trace_service else {},
            "usage": usage,
            "cost": cost,
            "cost_usd": cost.get("total_cost_usd"),
            "upstream_id": upstream_id,
            "error_category": payload.get("category") or payload.get("code") or ("http_%s" % int(status) if int(status) >= 400 else ""),
            "human_message": payload.get("message") or payload.get("error") or "",
        }
        trace_origin = str(data.get("trace_origin") or "").strip() if isinstance(data, dict) else ""
        if trace_origin:
            record["trace_origin"] = trace_origin
        if policy_decision:
            record["gateway_policy"] = policy_decision
        if streaming_metrics:
            record["streaming_metrics"] = streaming_metrics
        trace = self.trace(record)
        if trace is not None:
            payload["trace_id"] = trace["trace_id"]
            payload["trace"] = {"trace_id": trace["trace_id"], "latency_ms": trace.get("latency_ms"), "status": trace.get("status")}
            routing = dict(routing)
            routing["trace_id"] = trace["trace_id"]
            payload["routing"] = routing
        return payload

    def serverless_completion(self, data, model, allow_unregistered=False):
        started_at = time.time()
        self.start_proxy_if_needed()
        if not allow_unregistered and model not in self.active_text_models():
            policy = self.model_policy_for_model(model) or {"decision": "unknown_model_rejection", "model": model}
            reason = policy.get("reason") or ("access_forbidden" if policy.get("decision") == "access_forbidden_rejection" else "unknown_model")
            payload = {"error": "unknown text model", "routing": {"requested": model, "used": None, "backend": "serverless", "reason": reason, "policy_decision": policy}}
            return HTTPStatus.BAD_REQUEST, self.trace_record("chat.serverless", data, model, started_at, HTTPStatus.BAD_REQUEST, payload, backend="serverless", reason="unknown_model")
        registry_issue = self.registry_sync_issue_for_model(model)
        if registry_issue and registry_issue.get("blocking"):
            policy = {"decision": "stale_registry_protection", "model": model, "blocking": True, "reason": registry_issue.get("reason") or "registry_sync_blocked"}
            payload = {
                "error": registry_issue["message"],
                "message": registry_issue["message"],
                "registry_sync": registry_issue,
                "routing": {"requested": model, "used": None, "backend": "serverless", "reason": "registry_sync_blocked", "policy_decision": policy},
            }
            return HTTPStatus.CONFLICT, self.trace_record("chat.serverless", data, model, started_at, HTTPStatus.CONFLICT, payload, backend="serverless", reason="registry_sync_blocked")
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        if not messages:
            payload = {"error": "message is required", "routing": {"requested": model, "used": None, "backend": "serverless", "reason": "missing_message"}}
            return HTTPStatus.BAD_REQUEST, self.trace_record("chat.serverless", data, model, started_at, HTTPStatus.BAD_REQUEST, payload, backend="serverless", reason="missing_message")
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max(1, min(8192, int(data.get("max_tokens") or 512))),
            "stream": False,
        }
        request_timeout = self.request_timeout_seconds(data.get("request_timeout_seconds"))
        if request_timeout:
            payload["request_timeout_seconds"] = request_timeout
        if data.get("temperature") not in (None, ""):
            payload["temperature"] = float(data["temperature"])
        status, response = self.request_json(self.proxy_url("/v1/messages"), payload, timeout=request_timeout + 5 if request_timeout else 240)
        if status >= 400:
            if isinstance(response, dict):
                response.setdefault("routing", {"requested": model, "used": None, "backend": "serverless", "reason": "upstream_error"})
            return status, self.trace_record("chat.serverless", data, model, started_at, status, response if isinstance(response, dict) else {"error": str(response)}, backend="serverless", reason="upstream_error")
        text = "".join(part.get("text", "") for part in response.get("content", []) if isinstance(part, dict))
        input_text = "\n".join(str(msg.get("content") or "") for msg in messages if isinstance(msg, dict))
        routing = {"requested": model, "used": model, "backend": "serverless"}
        if registry_issue:
            routing["reason"] = "registry_sync_warning"
            routing["registry_sync"] = registry_issue
            routing["policy_decision"] = {"decision": "stale_registry_warning", "model": model, "blocking": False, "reason": registry_issue.get("reason") or "registry_sync_warning"}
        claude_do = response.get("claude_do") if isinstance(response.get("claude_do"), dict) else {}
        upstream_cost = claude_do.get("cost") if isinstance(claude_do.get("cost"), dict) else None
        estimated_cost = self.chat_cost_usd(model, input_text, text)
        payload = {
            "text": text,
            "raw": response,
            "usage": response.get("usage") or {},
            "cost": upstream_cost or estimated_cost,
            "routing": routing,
            "diagnostics": _chat_output_diagnostics(text, response),
        }
        if upstream_cost:
            payload["cost_estimate"] = estimated_cost
        if isinstance(claude_do.get("streaming_metrics"), dict):
            payload["streaming_metrics"] = claude_do["streaming_metrics"]
        return HTTPStatus.OK, self.trace_record("chat.serverless", data, model, started_at, HTTPStatus.OK, payload, backend="serverless")

    def completion(self, data):
        started_at = time.time()
        model = data.get("model") or self.default_text_model()
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        if not messages:
            payload = {"error": "message is required", "routing": {"requested": model, "used": None, "backend": "chat", "reason": "missing_message"}}
            return HTTPStatus.BAD_REQUEST, self.trace_record("chat", data, model, started_at, HTTPStatus.BAD_REQUEST, payload, backend="chat", reason="missing_message")
        if self.is_dedicated_model(model):
            self.dedicated_status_payload(poll=True)
            status, payload = self.dedicated_chat_completion(data, self.load_dedicated_config())
            if isinstance(payload, dict):
                routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
                if not routing.get("policy_decision") and (routing.get("backend") in (None, "", "dedicated")):
                    routing = dict(routing)
                    routing["policy_decision"] = self.model_policy_for_model(model) or {"decision": "dedicated_online_preference", "model": model}
                    payload["routing"] = routing
            return status, self.trace_record("chat.dedicated", data, model, started_at, status, payload, backend="dedicated")
        return self.serverless_completion(data, model)

    def proxy_get(self, path):
        self.start_proxy_if_needed()
        return self.request_json(self.proxy_url(path), payload=None, timeout=10, method="GET")
