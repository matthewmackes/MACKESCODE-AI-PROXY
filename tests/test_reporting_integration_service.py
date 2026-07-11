import tempfile
import unittest
from pathlib import Path

from src.console.services.reporting_integration import ReportingIntegrationService


class FakeExporter:
    last_error = "collector unavailable"

    def enabled(self):
        return True


class ReportingIntegrationServiceTests(unittest.TestCase):
    def test_payload_reports_metrics_dashboards_exporter_and_snippets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard_dir = root / "config" / "grafana" / "dashboards"
            dashboard_dir.mkdir(parents=True)
            (dashboard_dir / "mde-llm-proxy-overview.json").write_text("{}", encoding="utf-8")
            service = ReportingIntegrationService(
                project_root=root,
                console_status=lambda: {"service": "console", "status": "ok", "uptime_seconds": 42},
                metrics_text=lambda: "matts_console_up 1\nmatts_model_requests_total 2\n",
                otel_exporter=FakeExporter(),
            )

            payload = service.payload()

            self.assertTrue(payload["metrics"]["reachable"])
            self.assertEqual(payload["metrics"]["series_count"], 2)
            self.assertEqual(payload["dashboards"][0]["path"], "config/grafana/dashboards/mde-llm-proxy-overview.json")
            self.assertIn("mde-llm-proxy-console", payload["prometheus_scrape_config"])
            self.assertIn("mde-llm-proxy-console.yml", payload["docker_compose"])
            self.assertTrue(payload["exporter"]["enabled"])
            self.assertIn("scrape_configs", payload["prometheus_scrape_config"])
            self.assertIn("grafana/grafana-oss", payload["docker_compose"])
            self.assertIn("prompts", payload["privacy"]["excluded"])


if __name__ == "__main__":
    unittest.main()
