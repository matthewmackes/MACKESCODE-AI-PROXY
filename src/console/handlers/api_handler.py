"""JSON API route dispatcher for the console HTTP handler."""
from src.console.utils.errors import error_payload


class ConsoleApiHandler:
    """Dispatch JSON API paths to injected application services."""

    def __init__(self, **deps):
        self.deps = deps

    def call(self, name, *args, **kwargs):
        return self.deps[name](*args, **kwargs)

    def error(self, status, message, code=None, category=None, details=None):
        return True, int(status), error_payload(message, status, code=code, category=category, details=details)

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
            return True, 200 if result.get("ok") else 502, payload
        if path == "/api/model-access-key":
            return True, 200, {"key": self.call("active_model_access_key_info")}
        if path == "/api/proxy/status":
            return True, 200, self.call("proxy_sync_payload", force=False)
        if path == "/api/cost-summary":
            return True, 200, self.call("cost_summary_payload")
        if path == "/api/wallpaper":
            return True, 200, self.call("wallpaper_payload", randomize=(query.get("random") or ["0"])[0] == "1")
        if path == "/api/dedicated/status":
            return True, 200, self.call("dedicated_status_payload", poll=True)
        if path == "/api/dedicated/events":
            return True, 200, {"events": self.call("dedicated_events")}
        if path == "/api/dedicated/sizes":
            status, payload = self.call("dedicated_discovery", "/v2/dedicated-inferences/sizes")
            return True, status, payload
        if path == "/api/dedicated/gpu-model-config":
            status, payload = self.call("dedicated_discovery", "/v2/dedicated-inferences/gpu-model-config")
            return True, status, payload
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
            return True, status, payload
        if path == "/api/chat":
            status, payload = self.call("chat_completion", data)
            return True, status, payload
        if path == "/api/chat/save":
            return True, 200, self.call("save_chat", data)
        if path == "/api/chat/delete":
            return True, 200, {"deleted": self.call("delete_chat", data.get("id"))}
        if path == "/api/delete":
            return True, 200, {"deleted": self.call("delete_history_item", data.get("id"))}
        if path == "/api/models":
            status, payload = self.call("save_models_payload", data)
            return True, status, payload
        if path == "/api/proxy/sync":
            return True, 200, self.call("proxy_sync_payload", force=True)
        if path == "/api/model-access-audit":
            return True, 200, self.call("audit_model_access_key")
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
            return True, status, payload
        if path == "/api/dedicated/teardown":
            status, payload = self.call("dedicated_teardown", data)
            return True, status, payload
        if path == "/api/dedicated/resume":
            status, payload = self.call("dedicated_build", data)
            return True, status, payload
        if path == "/api/dedicated/policy":
            status, payload = self.call("dedicated_policy", data)
            return True, status, payload
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
            return True, status, payload
        if path == "/api/tmux/capture":
            status, payload = self.call("tmux_capture", data.get("name"))
            return True, status, payload
        if path == "/api/tmux/send":
            status, payload = self.call("tmux_send_text", data.get("name"), data.get("text") or "", bool(data.get("enter")))
            return True, status, payload
        if path == "/api/tmux/key":
            status, payload = self.call("tmux_send_key", data.get("name"), data.get("key"))
            return True, status, payload
        if path == "/api/tmux/stop":
            status, payload = self.call("tmux_stop", data.get("name"))
            return True, status, payload
        if path == "/api/tmux/rename":
            status, payload = self.call("tmux_rename_session", data.get("old_name"), data.get("new_name"), data.get("display_name"))
            return True, status, payload
        if path == "/api/terminal/start":
            status, payload = self.call("terminal_start", data)
            return True, status, payload
        if path == "/api/terminal/read":
            status, payload = self.call("terminal_read", data.get("id"))
            return True, status, payload
        if path == "/api/terminal/write":
            status, payload = self.call("terminal_write", data.get("id"), data.get("text") or "")
            return True, status, payload
        if path == "/api/terminal/stop":
            status, payload = self.call("terminal_stop", data.get("id"))
            return True, status, payload
        return False, 404, {}
