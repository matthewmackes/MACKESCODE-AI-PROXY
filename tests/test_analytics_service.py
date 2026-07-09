import datetime
import unittest

from src.console.services.analytics import AnalyticsService


class AnalyticsServiceTests(unittest.TestCase):
    def test_payload_aggregates_traces_usage_latency_and_csv(self):
        now = datetime.datetime(2026, 7, 9, tzinfo=datetime.timezone.utc).timestamp()
        traces = [
            {"timestamp": now, "status": "success", "requested_model": "model-a", "routed_model": "model-a", "cost_usd": 0.1, "latency_ms": 900},
            {"timestamp": now - 60, "status": "error", "requested_model": "model-a", "routed_model": "model-b", "cost_usd": 0.2, "latency_ms": 3200},
            {"timestamp": now - 9 * 86400, "status": "success", "requested_model": "old", "cost_usd": 9, "latency_ms": 1},
        ]

        service = AnalyticsService(
            read_traces=lambda limit=2000: traces,
            local_usage_report=lambda start, end: {"total_usd": 0.3, "daily": [{"date": start.isoformat(), "amount_usd": 0.3}], "by_model": []},
            cost_summary_payload=lambda: {"last_24h_total_usd": 0.35},
            clock=lambda: now,
        )

        payload = service.payload(days=7)

        self.assertEqual(payload["summary"]["requests"], 2)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["summary"]["avg_latency_ms"], 2050)
        self.assertEqual(payload["summary"]["local_cost_usd"], 0.3)
        self.assertEqual(payload["models"][0]["model"], "model-b")
        self.assertIn("model,model-b,1,1,0.2,3200", payload["export_csv"])
        self.assertEqual(sum(row["count"] for row in payload["latency_buckets"]), 2)


if __name__ == "__main__":
    unittest.main()
