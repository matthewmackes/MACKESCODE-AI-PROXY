import unittest

from src.console.services.health import ConsoleHealthService


class FailingMetricsExporter:
    def export_metrics(self, status, request_counts, tmux_session_count):
        raise RuntimeError("collector down")


class ConsoleHealthServiceTests(unittest.TestCase):
    def service(self, proxy_ready=True, launcher_ok=True, otel_exporter=None):
        return ConsoleHealthService(
            service="test-console",
            version="9.9.9",
            started_at=100,
            proxy_host=lambda: "127.0.0.1",
            proxy_port=lambda: 18080,
            port_open=lambda host, port: proxy_ready,
            launcher_health=lambda: {"ok": launcher_ok},
            auth_enabled=lambda: True,
            tmux_sessions=lambda: [{"name": "one"}, {"name": "two"}],
            request_counts={"GET": 3, "POST": 1},
            clock=lambda: 142,
            otel_exporter=otel_exporter,
        )

    def reporting_service(self):
        traces = [
            {
                "status": "success",
                "requested_model": "model-a",
                "routed_model": "model-b",
                "endpoint_mode": "serverless",
                "routing_reason": "gateway_fallback",
                "provider": "digitalocean",
                "latency_ms": 1200,
                "cost_usd": 0.03,
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            },
            {
                "status": "error",
                "requested_model": "model-a",
                "routed_model": "model-a",
                "endpoint_mode": "dedicated",
                "provider": "digitalocean",
                "http_status": 429,
                "error_category": "rate_limit",
            },
        ]
        return ConsoleHealthService(
            service="test-console",
            version="9.9.9",
            started_at=100,
            proxy_host=lambda: "127.0.0.1",
            proxy_port=lambda: 18080,
            port_open=lambda host, port: True,
            launcher_health=lambda: {"ok": True},
            auth_enabled=lambda: True,
            tmux_sessions=lambda: [],
            request_counts={"GET": 3},
            clock=lambda: 142,
            read_traces=lambda limit=2000: traces,
            dedicated_events=lambda limit=200: [{"type": "ready", "data": {"model": "model-b", "runtime_seconds": 3600}}],
            list_eval_runs=lambda limit=50: [{"dataset": "smoke", "summary": [{"model": "model-b", "failures": 0, "pass_rate": 1.0}]}],
            cost_summary_payload=lambda: {"last_24h_total_usd": 0.5, "month_total_usd": 4.0, "budgets": {"daily_usd": 2.0, "monthly_usd": 20.0}},
        )

    def test_status_reports_ok_only_when_proxy_and_launcher_are_ready(self):
        status = self.service(proxy_ready=True, launcher_ok=True).status()
        self.assertEqual(status["service"], "test-console")
        self.assertEqual(status["version"], "9.9.9")
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["uptime_seconds"], 42)
        self.assertTrue(status["proxy"]["listening"])
        self.assertTrue(status["auth_enabled"])

        self.assertEqual(self.service(proxy_ready=False, launcher_ok=True).status()["status"], "degraded")
        self.assertEqual(self.service(proxy_ready=True, launcher_ok=False).status()["status"], "degraded")

    def test_metrics_emit_prometheus_values(self):
        metrics = self.service().metrics_text()

        self.assertIn("matts_console_ready 1", metrics)
        self.assertIn("matts_console_uptime_seconds 42", metrics)
        self.assertIn("matts_console_proxy_listening 1", metrics)
        self.assertIn("matts_console_tmux_sessions 2", metrics)
        self.assertIn('matts_console_requests_total{method="GET"} 3', metrics)
        self.assertIn('matts_console_requests_total{method="POST"} 1', metrics)

    def test_metrics_include_grafana_reporting_families_with_bounded_labels(self):
        metrics = self.reporting_service().metrics_text()

        self.assertIn('matts_model_requests_total{model="model-b",route="serverless",status="success"} 1', metrics)
        self.assertIn('matts_model_latency_ms_bucket{le="3000",model="model-b",route="serverless"} 1', metrics)
        self.assertIn('matts_model_tokens_total{model="model-b",type="input"} 10.0', metrics)
        self.assertIn('matts_model_cost_usd_total{model="model-b",route="serverless"} 0.03', metrics)
        self.assertIn('matts_gateway_fallbacks_total{from_model="model-a",reason="gateway_fallback",to_model="model-b"} 1', metrics)
        self.assertIn('matts_provider_errors_total{category="rate_limit",model="model-a",provider="digitalocean"} 1', metrics)
        self.assertIn('matts_rate_limit_blocks_total{actor_type="operator",path="unknown"} 1', metrics)
        self.assertIn('matts_dedicated_state{model="model-b",state="ready"} 1', metrics)
        self.assertIn('matts_dedicated_runtime_seconds_total{model="model-b"} 3600.0', metrics)
        self.assertIn('matts_eval_runs_total{dataset="smoke",status="passed"} 1', metrics)
        self.assertIn('matts_eval_pass_rate{dataset="smoke",model="model-b"} 1.0', metrics)
        self.assertIn('matts_budget_used_usd{window="24h"} 0.5', metrics)
        self.assertIn('matts_budget_limit_usd{window="daily"} 2.0', metrics)

    def test_metrics_export_failure_does_not_break_prometheus_text(self):
        metrics = self.service(otel_exporter=FailingMetricsExporter()).metrics_text()

        self.assertIn("matts_console_ready 1", metrics)


if __name__ == "__main__":
    unittest.main()
