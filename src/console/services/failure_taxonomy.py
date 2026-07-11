"""Shared failure taxonomy and remediation hints."""
import re


class FailureTaxonomyService:
    """Classify console, proxy, gateway, Dedicated, eval, and provider failures."""

    SENSITIVE_PARTS = (
        "authorization",
        "api_key",
        "access_key",
        "token",
        "secret",
        "password",
        "messages",
        "prompt",
        "screen",
        "raw",
        "output",
        "body",
        "payload",
    )

    DEFINITIONS = {
        "auth": {
            "title": "Authentication failure",
            "likely_cause": "The request is missing a valid console session, provider token, or model access key.",
            "suggested_fix": "Refresh the Console session and rerun the model access key audit.",
            "operator_actions": [{"label": "Active sessions", "target": "console:auth"}, {"label": "Retry key audit", "target": "console:model-access"}],
        },
        "access": {
            "title": "Access denied",
            "likely_cause": "The operator role or provider account does not have permission for the requested model or action.",
            "suggested_fix": "Check role permissions and retry the model access audit for the requested model.",
            "operator_actions": [{"label": "Permission simulator", "target": "console:permissions"}, {"label": "Retry access audit", "target": "console:model-access"}],
        },
        "budget": {
            "title": "Budget or quota guardrail",
            "likely_cause": "A budget policy, quota, or cost guardrail blocked the request.",
            "suggested_fix": "Review quota planner and budget limits before rerunning the action.",
            "operator_actions": [{"label": "Quota Planner", "target": "console:quotas"}, {"label": "Cost report", "target": "console:costs"}],
        },
        "rate_limit": {
            "title": "Rate limit",
            "likely_cause": "The provider, gateway, or local quota policy throttled the request.",
            "suggested_fix": "Wait for the current window to reset or route through an approved fallback model.",
            "operator_actions": [{"label": "Gateway decisions", "target": "console:gateway-decisions"}, {"label": "Provider Health", "target": "console:provider-health"}],
        },
        "provider_outage": {
            "title": "Provider outage",
            "likely_cause": "DigitalOcean or the upstream inference provider is degraded or unavailable.",
            "suggested_fix": "Check provider health and use fallback routing until the incident clears.",
            "operator_actions": [{"label": "Provider Health", "target": "console:provider-health"}, {"label": "Fallback route", "target": "console:routing"}],
        },
        "context_overflow": {
            "title": "Context window overflow",
            "likely_cause": "The prompt, retrieval payload, or conversation history exceeds the model context window.",
            "suggested_fix": "Reduce retrieved context, summarize history, or select a model with a larger context window.",
            "operator_actions": [{"label": "Context inspector", "target": "console:context"}, {"label": "RAG settings", "target": "console:rag"}],
        },
        "malformed_tool_call": {
            "title": "Malformed tool call",
            "likely_cause": "The model or client returned invalid tool JSON, arguments, or function-call structure.",
            "suggested_fix": "Replay the trace with stricter tool schema instructions and inspect the redacted diagnostics.",
            "operator_actions": [{"label": "Replay trace", "target": "console:replay"}, {"label": "Review Queue", "target": "console:reviews"}],
        },
        "registry_drift": {
            "title": "Registry drift",
            "likely_cause": "The local proxy registry, serverless catalog, or access state is stale.",
            "suggested_fix": "Sync the proxy registry and rerun model catalog or access discovery.",
            "operator_actions": [{"label": "Sync registry", "target": "console:proxy-sync"}, {"label": "Model registry", "target": "console:models"}],
        },
        "dedicated_not_ready": {
            "title": "Dedicated endpoint not ready",
            "likely_cause": "The Dedicated endpoint is building, cooling down, unhealthy, or missing required provider setup.",
            "suggested_fix": "Open Dedicated lifecycle, verify readiness, then use Serverless fallback while it recovers.",
            "operator_actions": [{"label": "Dedicated lifecycle", "target": "console:dedicated"}, {"label": "Serverless fallback", "target": "console:serverless"}],
        },
        "local_proxy": {
            "title": "Local proxy issue",
            "likely_cause": "The local proxy is stopped, unreachable, misconfigured, or out of sync.",
            "suggested_fix": "Restart or sync the proxy, then rerun the failed request.",
            "operator_actions": [{"label": "Proxy status", "target": "console:proxy"}, {"label": "Sync registry", "target": "console:proxy-sync"}],
        },
        "validation": {
            "title": "Validation failure",
            "likely_cause": "The request is missing required fields or contains invalid values.",
            "suggested_fix": "Correct the request fields shown in the error and retry.",
            "operator_actions": [{"label": "Raw diagnostics", "target": "console:diagnostics"}],
        },
        "not_found": {
            "title": "Resource not found",
            "likely_cause": "The requested session, trace, model, or artifact no longer exists.",
            "suggested_fix": "Refresh the Console view and select an existing resource.",
            "operator_actions": [{"label": "Refresh view", "target": "console:refresh"}],
        },
        "unknown": {
            "title": "Unclassified failure",
            "likely_cause": "The failure did not match a known platform category.",
            "suggested_fix": "Open the redacted diagnostics and attach the trace to a review item.",
            "operator_actions": [{"label": "Review Queue", "target": "console:reviews"}, {"label": "Raw diagnostics", "target": "console:diagnostics"}],
        },
    }

    PATTERNS = [
        ("rate_limit", re.compile(r"\b(rate.?limit|too many requests|429|throttl)", re.I)),
        ("budget", re.compile(r"\b(budget|quota|spend|cost guardrail|payment due|billing|insufficient credit)", re.I)),
        ("auth", re.compile(r"\b(unauthenticated|authentication|missing token|invalid token|api key|access key|401)", re.I)),
        ("access", re.compile(r"\b(forbidden|permission|unauthorized|access denied|not entitled|403)", re.I)),
        ("provider_outage", re.compile(r"\b(outage|incident|provider unavailable|upstream unavailable|service unavailable|5\d\d|timeout)", re.I)),
        ("context_overflow", re.compile(r"\b(context window|context length|maximum context|too many tokens|token limit|input too long)", re.I)),
        ("malformed_tool_call", re.compile(r"\b(tool call|function call|invalid json|malformed|schema|arguments)", re.I)),
        ("registry_drift", re.compile(r"\b(registry drift|catalog drift|stale registry|proxy registry|model access drift|not synced|out of sync)", re.I)),
        ("dedicated_not_ready", re.compile(r"\b(dedicated|endpoint).*\b(not ready|building|cooldown|unhealthy|failed|deleted)", re.I)),
        ("local_proxy", re.compile(r"\b(local proxy|proxy).*\b(stopped|unreachable|connection refused|not listening|offline|misconfigured)", re.I)),
        ("not_found", re.compile(r"\b(not found|missing resource|404)", re.I)),
        ("validation", re.compile(r"\b(required|invalid|validation|bad request|400)", re.I)),
    ]

    CODE_ALIASES = {
        "permission": "access",
        "client": "validation",
        "server": "provider_outage",
        "auth_account_issue": "auth",
        "billing_issue": "budget",
        "local_proxy_issue": "local_proxy",
        "model_access_issue": "access",
        "model_access_drift": "registry_drift",
        "dedicated_endpoint_issue": "dedicated_not_ready",
        "rate_limited": "rate_limit",
        "rate_limit_exceeded": "rate_limit",
        "quota_exceeded": "budget",
        "budget_blocked": "budget",
    }

    def classify(self, value=None, status=None):
        source = value if isinstance(value, dict) else {"message": value}
        category, confidence, raw_category = self.category_from_source(source, status=status)
        definition = self.DEFINITIONS.get(category) or self.DEFINITIONS["unknown"]
        failure = {
            "category": category,
            "title": definition["title"],
            "likely_cause": definition["likely_cause"],
            "suggested_fix": definition["suggested_fix"],
            "operator_actions": list(definition.get("operator_actions") or []),
            "confidence": confidence,
        }
        if raw_category and raw_category != category:
            failure["raw_category"] = raw_category
        trace = source.get("trace") if isinstance(source.get("trace"), dict) else {}
        trace_id = source.get("trace_id") or trace.get("trace_id")
        if trace_id:
            failure["trace_id"] = str(trace_id)
        return failure

    def decorate(self, payload=None, status=None, trace_id=None):
        payload = dict(payload) if isinstance(payload, dict) else {"error": str(payload or "")}
        failure = self.classify(payload, status=status)
        if trace_id:
            failure["trace_id"] = str(trace_id)
        payload["failure"] = failure
        payload["category"] = failure["category"]
        diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
        diagnostics.setdefault("redacted", True)
        diagnostics.setdefault("raw", self.redact({key: value for key, value in payload.items() if key != "diagnostics"}))
        payload["diagnostics"] = diagnostics
        return payload

    def summarize(self, rows):
        counts = {}
        for row in rows or []:
            trace_status = None
            if isinstance(row, dict):
                trace_status = row.get("http_status") or row.get("status_code")
            failure = self.classify(row, status=trace_status)
            category = failure["category"]
            item = counts.setdefault(category, {"category": category, "title": failure["title"], "count": 0, "suggested_fix": failure["suggested_fix"]})
            item["count"] += 1
        return sorted(counts.values(), key=lambda item: (-item["count"], item["category"]))

    def category_from_source(self, source, status=None):
        raw_values = []
        for key in ("failure_category", "error_category", "code", "issue_type", "reason", "routing_reason", "category"):
            value = source.get(key)
            if value:
                raw_values.append(str(value))
        failure = source.get("failure")
        if isinstance(failure, dict) and failure.get("category"):
            raw_values.insert(0, str(failure.get("category")))
        gateway = source.get("gateway_policy") if isinstance(source.get("gateway_policy"), dict) else {}
        if gateway.get("decision"):
            raw_values.append(str(gateway.get("decision")))
        for raw in raw_values:
            category = self.normalize_category(raw)
            if category:
                return category, "high", raw
        text = self.text_for(source)
        for category, pattern in self.PATTERNS:
            if pattern.search(text):
                return category, "medium", ""
        try:
            code = int(status if status is not None else source.get("http_status") or source.get("status_code") or source.get("status") or 0)
        except (TypeError, ValueError):
            code = 0
        if code == 401:
            return "auth", "high", "http_401"
        if code == 403:
            return "access", "high", "http_403"
        if code == 404:
            return "not_found", "high", "http_404"
        if code == 429:
            return "rate_limit", "high", "http_429"
        if 400 <= code < 500:
            return "validation", "low", "http_%s" % code
        if code >= 500:
            return "provider_outage", "low", "http_%s" % code
        return "unknown", "low", ""

    def normalize_category(self, value):
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        text = re.sub(r"_error$", "", text)
        if text in self.DEFINITIONS:
            return text
        if text in self.CODE_ALIASES:
            return self.CODE_ALIASES[text]
        if text.startswith("http_"):
            return self.category_from_source({}, status=text.split("_", 1)[1])[0]
        return ""

    def text_for(self, value):
        if isinstance(value, dict):
            parts = []
            for key, item in value.items():
                if key == "diagnostics":
                    continue
                parts.append(str(key))
                parts.append(self.text_for(item))
            return " ".join(parts)
        if isinstance(value, list):
            return " ".join(self.text_for(item) for item in value[:20])
        return str(value or "")

    def redact(self, value):
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(part in lowered for part in self.SENSITIVE_PARTS):
                    clean[key] = "[redacted]"
                elif key == "failure":
                    clean[key] = item
                else:
                    clean[key] = self.redact(item)
            return clean
        if isinstance(value, list):
            return [self.redact(item) for item in value[:80]]
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "...[truncated]"
        return value
