"""JSON API route dispatcher for the console HTTP handler."""
from src.console.utils.errors import error_payload, normalize_error_payload


class ConsoleApiHandler:
    """Dispatch JSON API paths to injected application services."""

    def __init__(self, **deps):
        self.deps = deps

    def call(self, name, *args, **kwargs):
        return self.deps[name](*args, **kwargs)

    def error(self, status, message, code=None, category=None, details=None):
        return True, int(status), error_payload(message, status, code=code, category=category, details=details)

    def result(self, status, payload, code=None, category=None, default_message="request failed"):
        status = int(status)
        if status >= 400:
            payload = normalize_error_payload(payload, status, code=code, category=category, default_message=default_message)
        return True, status, payload

    def trace_action(self, action, status, payload=None, request=None):
        """Attach an operator-action trace without making tracing a hard dependency."""
        if "append_trace" not in self.deps:
            return payload
        status = int(status)
        if not isinstance(payload, dict):
            payload = {"result": payload}
        request = request if isinstance(request, dict) else {}
        routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
        cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        record = {
            "action": action,
            "status": "success" if status < 400 else "error",
            "http_status": status,
            "requested_model": request.get("model") or request.get("model_id") or payload.get("model") or routing.get("requested"),
            "routed_model": routing.get("used") or payload.get("model"),
            "provider": request.get("provider") or payload.get("provider") or "local-console",
            "endpoint_mode": routing.get("backend") or action.split(".")[0],
            "routing_reason": routing.get("reason") or "",
            "session_id": request.get("session_id") or request.get("id") or request.get("name") or payload.get("session_id"),
            "cost": cost,
            "usage": usage,
            "cost_usd": cost.get("total_cost_usd") if isinstance(cost, dict) else None,
            "human_message": payload.get("message") or payload.get("error") or "",
            "error_category": payload.get("category") or payload.get("code") or ("http_%s" % status if status >= 400 else ""),
        }
        try:
            trace = self.call("append_trace", record)
        except Exception as exc:
            payload.setdefault("trace_error", str(exc))
            return payload
        if isinstance(trace, dict):
            payload.setdefault("trace_id", trace.get("trace_id"))
            payload.setdefault("trace", {"trace_id": trace.get("trace_id"), "status": trace.get("status")})
        return payload

    def get(self, path, query=None):
        query = query or {}
        if path == "/api/history":
            return True, 200, self.call("read_history")
        if path == "/api/chat/history":
            return True, 200, self.call("list_chats")
        if path == "/api/chat/load":
            chat_id = (query.get("id") or [""])[0]
            if not chat_id:
                return self.error(400, "id query parameter is required", code="missing_chat_id")
            doc = self.call("load_chat", chat_id)
            if doc is None:
                return self.error(404, "chat not found", code="chat_not_found", details={"id": chat_id})
            return True, 200, doc
        if path == "/api/tmux/sessions":
            items = self.call("tmux_session_items")
            return True, 200, {"sessions": [item["name"] for item in items if item.get("live")], "items": items}
        if path == "/api/agentboard":
            return True, 200, self.call("agentboard_payload")
        if path == "/api/models":
            return True, 200, self.call("models_payload")
        if path == "/api/models/serverless-catalog":
            result = self.call("sync_serverless_model_catalog", force=True, validate_access=True)
            payload = self.call("models_payload", refresh_catalog=False)
            payload["serverless_catalog"] = result
            payload["proxy_sync"] = self.call("proxy_sync_payload", force=True)
            status = 200 if result.get("ok") else 502
            payload = self.trace_action("model_catalog.refresh", status, payload, {"provider": "digitalocean-serverless"})
            return True, status, payload
        if path == "/api/model-access-key":
            return True, 200, {"key": self.call("active_model_access_key_info")}
        if path == "/api/proxy/status":
            return True, 200, self.call("proxy_sync_payload", force=False)
        if path == "/api/cost-summary":
            return True, 200, self.call("cost_summary_payload")
        if path == "/api/traces":
            try:
                limit = int((query.get("limit") or ["200"])[0] or 200)
            except (TypeError, ValueError):
                limit = 200
            return True, 200, {
                "traces": self.call(
                    "read_traces",
                    limit=limit,
                    model=(query.get("model") or [""])[0] or None,
                    status=(query.get("status") or [""])[0] or None,
                    session=(query.get("session") or [""])[0] or None,
                    min_cost=(query.get("min_cost") or [""])[0] or None,
                )
            }
        if path == "/api/evals":
            return True, 200, {"datasets": self.call("list_eval_datasets"), "runs": self.call("list_eval_runs")}
        if path == "/api/wallpaper":
            return True, 200, self.call("wallpaper_payload", randomize=(query.get("random") or ["0"])[0] == "1")
        if path == "/api/dedicated/status":
            return True, 200, self.call("dedicated_status_payload", poll=True)
        if path == "/api/dedicated/events":
            return True, 200, {"events": self.call("dedicated_events")}
        if path == "/api/dedicated/sizes":
            status, payload = self.call("dedicated_discovery", "/v2/dedicated-inferences/sizes")
            return self.result(status, payload, default_message="Dedicated Inference size discovery failed")
        if path == "/api/dedicated/gpu-model-config":
            status, payload = self.call("dedicated_discovery", "/v2/dedicated-inferences/gpu-model-config")
            return self.result(status, payload, default_message="Dedicated Inference GPU/model discovery failed")
        if path == "/api/status":
            proxy_sync = self.call("proxy_sync_payload", force=False)
            models_status, models = self.call("proxy_get", "/v1/models")
            costs_status, costs = self.call("proxy_get", "/v1/claude-do/costs")
            budget_status, budget = self.call("proxy_get", "/v1/claude-do/budget")
            return True, 200, {
                "proxy_listening": self.call("port_open", self.call("proxy_host"), self.call("proxy_port")),
                "proxy": "http://%s:%d" % (self.call("proxy_host"), self.call("proxy_port")),
                "proxy_sync": proxy_sync,
                "token_file": str(self.call("token_file")),
                "models": models if models_status < 400 else {"error": models},
                "costs": costs if costs_status < 400 else {"error": costs},
                "budget": budget if budget_status < 400 else {"error": budget},
                "logs": self.call("tail_jsonl", self.call("log_file")),
                "tmux_sessions": self.call("tmux_sessions"),
                "launcher": self.call("launcher_health"),
                "model_registry": self.call("models_payload"),
                "dedicated_inference": self.call("dedicated_status_payload", poll=False),
            }
        return False, 404, {}

    def post(self, path, data):
        if path == "/api/generate":
            status, payload = self.call("generate_images", data)
            payload = self.trace_action("image.generate", status, payload, data)
            return self.result(status, payload, default_message="image generation failed")
        if path == "/api/chat":
            status, payload = self.call("chat_completion", data)
            return self.result(status, payload, default_message="chat request failed")
        if path == "/api/chat/compare":
            models = data.get("models") if isinstance(data.get("models"), list) else []
            models = [str(model) for model in models if str(model or "").strip()]
            if not models or len(models) > 5:
                return self.error(400, "Select between one and five models for comparison.", code="invalid_comparison_models")
            active = set(self.call("text_models"))
            unavailable = [model for model in models if model not in active]
            if unavailable:
                return self.error(400, "Unavailable comparison models: " + ", ".join(unavailable), code="unavailable_comparison_model", details={"models": unavailable})
            messages = data.get("messages") if isinstance(data.get("messages"), list) else []
            prompt = str(data.get("prompt") or "").strip()
            if prompt:
                messages = messages + [{"role": "user", "content": prompt}]
            if not messages:
                return self.error(400, "comparison prompt is required", code="missing_comparison_prompt")
            results = []
            total_cost = 0.0
            saved_messages = list(messages)
            for model in models:
                status, payload = self.call("chat_completion", {
                    "model": model,
                    "messages": messages,
                    "max_tokens": data.get("max_tokens"),
                    "temperature": data.get("temperature"),
                })
                cost = payload.get("cost") if isinstance(payload, dict) and isinstance(payload.get("cost"), dict) else {}
                total_cost += float(cost.get("total_cost_usd") or 0.0)
                result = {
                    "model": model,
                    "status": int(status),
                    "ok": int(status) < 400,
                    "text": payload.get("text") if isinstance(payload, dict) else "",
                    "routing": payload.get("routing") if isinstance(payload, dict) else {},
                    "usage": payload.get("usage") if isinstance(payload, dict) else {},
                    "cost": cost,
                    "trace_id": payload.get("trace_id") if isinstance(payload, dict) else "",
                    "error": (payload.get("message") or payload.get("error") or "") if isinstance(payload, dict) and int(status) >= 400 else "",
                }
                results.append(result)
                saved_messages.append({"role": "assistant", "content": result["text"] or result["error"], "model": (result.get("routing") or {}).get("used") or model, "meta": {"comparison": True, "requested_model": model, "routing": result.get("routing"), "usage": result.get("usage"), "cost": result.get("cost"), "trace": {"trace_id": result.get("trace_id")}}})
            chat = self.call("save_chat", {"model": "comparison", "title": "Comparison: " + str(messages[-1].get("content") or "")[:48], "messages": saved_messages})
            return True, 200, {"models": models, "results": results, "total_cost_usd": round(total_cost, 8), "chat": {"id": chat.get("id"), "title": chat.get("title"), "message_count": len(chat.get("messages") or [])}}
        if path == "/api/evals/run":
            try:
                return True, 200, self.call("run_eval", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="eval_run_invalid")
        if path == "/api/chat/save":
            return True, 200, self.call("save_chat", data)
        if path == "/api/chat/delete":
            return True, 200, {"deleted": self.call("delete_chat", data.get("id"))}
        if path == "/api/delete":
            return True, 200, {"deleted": self.call("delete_history_item", data.get("id"))}
        if path == "/api/models":
            status, payload = self.call("save_models_payload", data)
            return self.result(status, payload, default_message="model registry update failed")
        if path == "/api/proxy/sync":
            return True, 200, self.call("proxy_sync_payload", force=True)
        if path == "/api/model-access-audit":
            payload = self.call("audit_model_access_key")
            return True, 200, self.trace_action("model_access.audit", 200, payload, data)
        if path == "/api/dedicated/preflight":
            preflight = self.call("dedicated_preflight", data)
            payload = self.call("dedicated_status_payload", poll=False)
            payload["preflight"] = preflight
            payload["dedicated"] = preflight.get("config") or payload.get("dedicated")
            if preflight.get("errors"):
                self.call("append_dedicated_event", "preflight", "Dedicated preflight needs attention", "warning", {"errors": preflight.get("errors"), "warnings": preflight.get("warnings")})
            else:
                self.call("append_dedicated_event", "preflight", "Dedicated preflight passed", "success", {"warnings": preflight.get("warnings")})
            payload["events"] = self.call("dedicated_events")
            return True, 200, payload
        if path == "/api/dedicated/build":
            status, payload = self.call("dedicated_build", data)
            payload = self.trace_action("dedicated.build", status, payload, data)
            return self.result(status, payload, default_message="Dedicated Inference build failed")
        if path == "/api/dedicated/teardown":
            status, payload = self.call("dedicated_teardown", data)
            payload = self.trace_action("dedicated.teardown", status, payload, data)
            return self.result(status, payload, default_message="Dedicated Inference teardown failed")
        if path == "/api/dedicated/resume":
            status, payload = self.call("dedicated_build", data)
            return self.result(status, payload, default_message="Dedicated Inference resume failed")
        if path == "/api/dedicated/policy":
            status, payload = self.call("dedicated_policy", data)
            return self.result(status, payload, default_message="Dedicated Inference policy update failed")
        if path == "/api/dedicated/keep-alive":
            status, payload = self.call("dedicated_keep_alive", data)
            return self.result(status, payload, default_message="Dedicated Inference keep-alive failed")
        if path == "/api/budget":
            return True, 200, {"budgets": self.call("save_budget", data)}
        if path == "/api/reporting":
            return True, 200, self.call("digitalocean_report", data)
        if path == "/api/test-models":
            results = []
            for model in self.deps["text_models"]():
                status, payload = self.call("chat_completion", {"model": model, "messages": [{"role": "user", "content": "Reply only ok"}], "max_tokens": 8})
                results.append({"model": model, "status": int(status), "ok": int(status) < 400, "response": payload})
            image_model = self.call("default_image_model")
            status, payload = self.call("generate_images", {"model": image_model, "prompt": "small smoke test tile with the word OK", "size": "512x512", "count": 1, "style": "technical"})
            results.append({"model": image_model, "status": int(status), "ok": int(status) < 400, "response": payload})
            return True, 200, {"results": results}
        if path == "/api/tmux/start":
            status, payload = self.call("tmux_start", data)
            payload = self.trace_action("tmux.start", status, payload, data)
            return self.result(status, payload, default_message="tmux session start failed")
        if path == "/api/tmux/capture":
            status, payload = self.call("tmux_capture", data.get("name"))
            return self.result(status, payload, default_message="tmux capture failed")
        if path == "/api/tmux/send":
            status, payload = self.call("tmux_send_text", data.get("name"), data.get("text") or "", bool(data.get("enter")))
            return self.result(status, payload, default_message="tmux send failed")
        if path == "/api/tmux/key":
            status, payload = self.call("tmux_send_key", data.get("name"), data.get("key"))
            return self.result(status, payload, default_message="tmux key send failed")
        if path == "/api/tmux/stop":
            status, payload = self.call("tmux_stop", data.get("name"))
            return self.result(status, payload, default_message="tmux stop failed")
        if path == "/api/tmux/rename":
            status, payload = self.call("tmux_rename_session", data.get("old_name"), data.get("new_name"), data.get("display_name"))
            return self.result(status, payload, default_message="tmux rename failed")
        if path == "/api/terminal/start":
            status, payload = self.call("terminal_start", data)
            return self.result(status, payload, default_message="terminal start failed")
        if path == "/api/terminal/read":
            status, payload = self.call("terminal_read", data.get("id"))
            return self.result(status, payload, default_message="terminal read failed")
        if path == "/api/terminal/write":
            status, payload = self.call("terminal_write", data.get("id"), data.get("text") or "")
            return self.result(status, payload, default_message="terminal write failed")
        if path == "/api/terminal/stop":
            status, payload = self.call("terminal_stop", data.get("id"))
            return self.result(status, payload, default_message="terminal stop failed")
        return False, 404, {}
