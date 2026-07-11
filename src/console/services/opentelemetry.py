"""Optional OpenTelemetry OTLP/HTTP export helpers."""
import hashlib
import json
import time
from urllib.request import Request, urlopen

DEFAULT_OTEL_SERVICE_NAME = "mde-llm-proxy-console"
DEFAULT_OTEL_SERVICE_NAMESPACE = "mde"


class OpenTelemetryExporter:
    """Export privacy-safe traces and metrics to an OTLP/HTTP collector."""

    def __init__(self, config=None, urlopen_func=None, clock=None):
        self.config = config if isinstance(config, dict) else {}
        self.urlopen = urlopen_func or urlopen
        self.clock = clock or time.time
        self.last_error = ""

    def enabled(self):
        return bool(self.config.get("enabled")) and bool(str(self.config.get("endpoint") or "").strip())

    def export_trace(self, trace_record):
        if not self.enabled():
            return False
        return self._post("/v1/traces", self.trace_payload(trace_record))

    def export_metrics(self, status, request_counts, tmux_session_count):
        if not self.enabled():
            return False
        return self._post("/v1/metrics", self.metrics_payload(status, request_counts, tmux_session_count))

    def trace_payload(self, trace_record):
        rec = trace_record if isinstance(trace_record, dict) else {}
        end_ns = self._unix_nano(rec.get("timestamp") or self.clock())
        latency_ms = self._number(rec.get("latency_ms"), 0)
        start_ns = max(0, end_ns - int(latency_ms * 1_000_000))
        span = {
            "traceId": self._hex_id(rec.get("trace_id"), 32),
            "spanId": self._hex_id("%s:span" % rec.get("trace_id"), 16),
            "name": str(rec.get("action") or "mde.console.request"),
            "kind": 1,
            "startTimeUnixNano": str(start_ns),
            "endTimeUnixNano": str(end_ns),
            "attributes": self._attributes(self._trace_attributes(rec)),
            "status": {"code": 2 if self._is_error(rec) else 1},
        }
        return {
            "resourceSpans": [
                {
                    "resource": {"attributes": self._resource_attributes()},
                    "scopeSpans": [{"scope": {"name": self.service_name()}, "spans": [span]}],
                }
            ]
        }

    def metrics_payload(self, status, request_counts, tmux_session_count):
        status = status if isinstance(status, dict) else {}
        proxy = status.get("proxy") if isinstance(status.get("proxy"), dict) else {}
        metrics = [
            self._gauge("matts.console.up", 1),
            self._gauge("matts.console.ready", 1 if status.get("status") == "ok" else 0),
            self._gauge("matts.console.uptime.seconds", self._number(status.get("uptime_seconds"), 0)),
            self._gauge("matts.console.proxy.listening", 1 if proxy.get("listening") else 0),
            self._gauge("matts.console.tmux.sessions", tmux_session_count),
        ]
        for method, count in sorted((request_counts or {}).items()):
            metrics.append(self._sum("matts.console.requests", self._number(count, 0), {"http.request.method": str(method)}))
        return {
            "resourceMetrics": [
                {
                    "resource": {"attributes": self._resource_attributes()},
                    "scopeMetrics": [{"scope": {"name": self.service_name()}, "metrics": metrics}],
                }
            ]
        }

    def _post(self, path, payload):
        try:
            body = json.dumps(payload).encode("utf-8")
            request = Request(self._url(path), data=body, method="POST", headers=self._headers())
            self.urlopen(request, timeout=float(self.config.get("timeout_seconds") or 3))
            self.last_error = ""
            return True
        except Exception as exc:  # pragma: no cover - exact network exceptions vary by platform
            self.last_error = str(exc)
            return False

    def _url(self, path):
        endpoint = str(self.config.get("endpoint") or "").rstrip("/")
        if endpoint.endswith("/v1/traces") or endpoint.endswith("/v1/metrics"):
            return endpoint
        return endpoint + path

    def _headers(self):
        headers = {"content-type": "application/json"}
        configured = self.config.get("headers") if isinstance(self.config.get("headers"), dict) else {}
        for key, value in configured.items():
            if str(key).strip() and value is not None:
                headers[str(key)] = str(value)
        return headers

    def _resource_attributes(self):
        return self._attributes({
            "service.name": self.service_name(),
            "service.namespace": DEFAULT_OTEL_SERVICE_NAMESPACE,
        })

    def service_name(self):
        return str(self.config.get("service_name") or DEFAULT_OTEL_SERVICE_NAME)

    def _trace_attributes(self, rec):
        summary = rec.get("message_summary") if isinstance(rec.get("message_summary"), dict) else {}
        gateway = rec.get("gateway_policy") if isinstance(rec.get("gateway_policy"), dict) else {}
        attrs = {
            "matts.trace_id": rec.get("trace_id"),
            "matts.status": rec.get("status"),
            "matts.action": rec.get("action"),
            "matts.routing.reason": rec.get("routing_reason"),
            "matts.gateway.decision": gateway.get("decision"),
            "gen_ai.request.model": rec.get("requested_model"),
            "gen_ai.response.model": rec.get("routed_model"),
            "server.address": rec.get("backend"),
            "matts.session_id": rec.get("session_id") or rec.get("chat_id") or rec.get("tmux_session"),
            "matts.cost.usd": rec.get("cost_usd"),
            "matts.latency.ms": rec.get("latency_ms"),
            "matts.messages.count": summary.get("message_count"),
            "matts.last_user.chars": summary.get("last_user_chars"),
            "matts.error.category": rec.get("error_category"),
        }
        return {key: value for key, value in attrs.items() if value not in (None, "")}

    def _attributes(self, values):
        return [{"key": key, "value": self._otel_value(value)} for key, value in values.items() if value not in (None, "")]

    def _otel_value(self, value):
        if isinstance(value, bool):
            return {"boolValue": value}
        if isinstance(value, int) and not isinstance(value, bool):
            return {"intValue": str(value)}
        if isinstance(value, float):
            return {"doubleValue": value}
        return {"stringValue": str(value)}

    def _gauge(self, name, value):
        return {
            "name": name,
            "gauge": {"dataPoints": [{"timeUnixNano": str(self._unix_nano(self.clock())), "asDouble": float(value)}]},
        }

    def _sum(self, name, value, attributes=None):
        return {
            "name": name,
            "sum": {
                "aggregationTemporality": 2,
                "isMonotonic": True,
                "dataPoints": [
                    {
                        "timeUnixNano": str(self._unix_nano(self.clock())),
                        "asDouble": float(value),
                        "attributes": self._attributes(attributes or {}),
                    }
                ],
            },
        }

    def _unix_nano(self, seconds):
        return int(float(seconds) * 1_000_000_000)

    def _hex_id(self, value, length):
        return hashlib.sha256(str(value or self.clock()).encode("utf-8")).hexdigest()[:length]

    def _number(self, value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _is_error(self, rec):
        status = str(rec.get("status") or "").lower()
        if status in {"error", "failed", "failure"}:
            return True
        try:
            return int(rec.get("http_status") or rec.get("status_code") or 0) >= 400
        except (TypeError, ValueError):
            return False
