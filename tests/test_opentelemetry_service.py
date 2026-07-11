import json
import unittest

from src.console.services.opentelemetry import OpenTelemetryExporter


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class OpenTelemetryExporterTests(unittest.TestCase):
    def test_disabled_exporter_is_noop(self):
        calls = []
        exporter = OpenTelemetryExporter(config={"enabled": False, "endpoint": "http://collector:4318"}, urlopen_func=lambda *args, **kwargs: calls.append(args))

        self.assertFalse(exporter.export_trace({"trace_id": "trace-a"}))
        self.assertEqual(calls, [])

    def test_trace_payload_redacts_prompt_preview_and_maps_attributes(self):
        exporter = OpenTelemetryExporter(config={"enabled": True, "endpoint": "http://collector:4318", "service_name": "console-test"}, clock=lambda: 100.0)
        payload = exporter.trace_payload({
            "trace_id": "trace-a",
            "timestamp": 100.0,
            "action": "chat.serverless",
            "status": "success",
            "requested_model": "model-a",
            "routed_model": "model-b",
            "latency_ms": 25,
            "cost_usd": 0.02,
            "message_summary": {
                "message_count": 2,
                "last_user_chars": 32,
                "last_user_preview": "do not export this prompt",
            },
            "gateway_policy": {"decision": "fallback"},
        })

        raw = json.dumps(payload)
        self.assertIn("resourceSpans", payload)
        self.assertIn("console-test", raw)
        self.assertIn("service.namespace", raw)
        self.assertIn('"mde"', raw)
        self.assertIn("gen_ai.request.model", raw)
        self.assertIn("model-a", raw)
        self.assertIn("matts.last_user.chars", raw)
        self.assertNotIn("do not export this prompt", raw)

    def test_metrics_payload_maps_status_and_request_counts(self):
        exporter = OpenTelemetryExporter(config={"enabled": True, "endpoint": "http://collector:4318"}, clock=lambda: 100.0)
        payload = exporter.metrics_payload(
            {"status": "ok", "uptime_seconds": 42, "proxy": {"listening": True}},
            {"GET": 3, "POST": 1},
            2,
        )

        raw = json.dumps(payload)
        self.assertIn("resourceMetrics", payload)
        self.assertIn("mde-llm-proxy-console", raw)
        self.assertIn("matts.console.ready", raw)
        self.assertIn("matts.console.requests", raw)
        self.assertIn("http.request.method", raw)

    def test_export_failure_is_recorded_not_raised(self):
        def fail(_request, timeout):
            raise OSError("collector down")

        exporter = OpenTelemetryExporter(config={"enabled": True, "endpoint": "http://collector:4318"}, urlopen_func=fail)

        self.assertFalse(exporter.export_trace({"trace_id": "trace-a"}))
        self.assertIn("collector down", exporter.last_error)

    def test_export_posts_signal_specific_endpoint_and_headers(self):
        calls = []

        def capture(request, timeout):
            calls.append((request, timeout))
            return FakeResponse()

        exporter = OpenTelemetryExporter(
            config={
                "enabled": True,
                "endpoint": "http://collector:4318",
                "timeout_seconds": 1.5,
                "headers": {"x-api-key": "secret"},
            },
            urlopen_func=capture,
        )

        self.assertTrue(exporter.export_trace({"trace_id": "trace-a"}))
        self.assertEqual(calls[0][0].full_url, "http://collector:4318/v1/traces")
        self.assertEqual(calls[0][1], 1.5)
        self.assertEqual(calls[0][0].headers["X-api-key"], "secret")


if __name__ == "__main__":
    unittest.main()
