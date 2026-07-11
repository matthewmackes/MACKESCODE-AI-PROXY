import json
import tempfile
import unittest
from pathlib import Path

from backend.v2.services.proxy_cli import ProxyCliService


class ProxyCliServiceTests(unittest.TestCase):
    def test_list_models_filters_disabled_and_inaccessible_serverless(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            path.write_text(
                json.dumps(
                    {
                        "models": [
                            {"id": "enabled", "type": "text", "enabled": True},
                            {"id": "disabled", "type": "text", "enabled": False},
                            {"id": "blocked", "type": "text", "serverless": True, "access_status": "forbidden"},
                            {"id": "allowed", "type": "text", "serverless": True, "access_status": "ok"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            service = ProxyCliService(model_config_file=path)
            result = service.list_models()
        self.assertTrue(result.ok)
        self.assertEqual([row["id"] for row in result.data["models"]], ["enabled", "allowed"])

    def test_costs_totals_recent_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"cost": {"total_cost_usd": 0.25}}),
                        "not-json",
                        json.dumps({"cost_usd": 0.75}),
                    ]
                ),
                encoding="utf-8",
            )
            service = ProxyCliService(cost_file=path)
            result = service.costs()
        self.assertTrue(result.ok)
        self.assertEqual(result.data["recent_total_usd"], 1.0)
        self.assertEqual(len(result.data["records"]), 2)

    def test_status_reports_stopped_without_proxy(self):
        service = ProxyCliService(proxy_host="127.0.0.1", proxy_port=9)
        result = service.status()
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")


if __name__ == "__main__":
    unittest.main()
