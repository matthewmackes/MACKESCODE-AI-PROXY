"""Chat routing helpers for serverless and Dedicated requests."""
from http import HTTPStatus


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

    def active_text_models(self):
        return list(self.text_models() if callable(self.text_models) else self.text_models)

    def serverless_completion(self, data, model, allow_unregistered=False):
        self.start_proxy_if_needed()
        if not allow_unregistered and model not in self.active_text_models():
            return HTTPStatus.BAD_REQUEST, {"error": "unknown text model"}
        registry_issue = self.registry_sync_issue_for_model(model)
        if registry_issue and registry_issue.get("blocking"):
            return HTTPStatus.CONFLICT, {
                "error": registry_issue["message"],
                "message": registry_issue["message"],
                "registry_sync": registry_issue,
                "routing": {"requested": model, "used": None, "backend": "serverless", "reason": "registry_sync_blocked"},
            }
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        if not messages:
            return HTTPStatus.BAD_REQUEST, {"error": "message is required"}
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max(1, min(8192, int(data.get("max_tokens") or 512))),
            "stream": False,
        }
        if data.get("temperature") not in (None, ""):
            payload["temperature"] = float(data["temperature"])
        status, response = self.request_json(self.proxy_url("/v1/messages"), payload, timeout=240)
        if status >= 400:
            return status, response
        text = "".join(part.get("text", "") for part in response.get("content", []) if isinstance(part, dict))
        input_text = "\n".join(str(msg.get("content") or "") for msg in messages if isinstance(msg, dict))
        routing = {"requested": model, "used": model, "backend": "serverless"}
        if registry_issue:
            routing["reason"] = "registry_sync_warning"
            routing["registry_sync"] = registry_issue
        return HTTPStatus.OK, {
            "text": text,
            "raw": response,
            "usage": response.get("usage") or {},
            "cost": self.chat_cost_usd(model, input_text, text),
            "routing": routing,
        }

    def completion(self, data):
        model = data.get("model") or self.default_text_model()
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        if not messages:
            return HTTPStatus.BAD_REQUEST, {"error": "message is required"}
        if self.is_dedicated_model(model):
            self.dedicated_status_payload(poll=True)
            return self.dedicated_chat_completion(data, self.load_dedicated_config())
        return self.serverless_completion(data, model)

    def proxy_get(self, path):
        self.start_proxy_if_needed()
        return self.request_json(self.proxy_url(path), payload=None, timeout=10, method="GET")
