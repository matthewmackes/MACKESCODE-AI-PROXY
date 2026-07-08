import unittest

from src.console.services.health import ConsoleHealthService


class ConsoleHealthServiceTests(unittest.TestCase):
    def service(self, proxy_ready=True, launcher_ok=True):
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


if __name__ == "__main__":
    unittest.main()
