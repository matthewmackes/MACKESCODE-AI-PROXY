import datetime
import unittest

from src.console.services.model_scorecards import ModelScorecardService, health_grade, median_latency_ms


class ModelScorecardServiceTests(unittest.TestCase):
    def service(self, traces=None, eval_runs=None, usage=None, now=None):
        now = now or datetime.datetime(2026, 7, 9, tzinfo=datetime.timezone.utc).timestamp()
        models = [
            {"id": "model-a", "display_name": "Model A", "enabled": True, "type": "text", "serverless": True, "provider": "DO", "context_window": 8192, "max_output_tokens": 2048, "tool_support": True, "pricing": {"input": 1.0, "output": 2.0}, "access_status": "allowed"},
            {"id": "model-b", "display_name": "Model B", "enabled": False, "type": "text", "serverless": True, "provider": "DO", "pricing": {}},
        ]
        return ModelScorecardService(
            load_model_registry=lambda include_disabled=True: models,
            read_traces=lambda limit=5000: traces or [],
            list_eval_runs=lambda limit=50: eval_runs or [],
            local_usage_report=lambda start, end: usage or {"by_model": [], "daily": [], "total_usd": 0},
            clock=lambda: now,
        )

    def test_scorecards_combine_registry_trace_eval_and_usage_metrics(self):
        now = datetime.datetime(2026, 7, 9, tzinfo=datetime.timezone.utc).timestamp()
        traces = [
            {"timestamp": now, "status": "success", "requested_model": "model-a", "routed_model": "model-a", "cost_usd": 0.10, "latency_ms": 900},
            {"timestamp": now - 30, "status": "error", "requested_model": "model-a", "routed_model": "model-a", "cost_usd": 0.05, "latency_ms": 4000},
        ]
        eval_runs = [{"created_at": now, "summary": [{"model": "model-a", "requests": 4, "failures": 1, "total_cost_usd": 0.20, "avg_latency_ms": 1200, "pass_rate": 0.75}]}]
        usage = {"by_model": [{"model": "model-a", "amount_usd": 0.40}], "daily": [], "total_usd": 0.40}

        payload = self.service(traces=traces, eval_runs=eval_runs, usage=usage, now=now).payload(days=30)
        card = payload["by_model"]["model-a"]

        self.assertEqual(card["route"], "serverless")
        self.assertEqual(card["trace"]["requests"], 2)
        self.assertEqual(card["trace"]["error_rate"], 0.5)
        self.assertEqual(card["eval"]["pass_rate"], 0.75)
        self.assertEqual(card["usage"]["local_cost_usd"], 0.4)
        self.assertEqual(card["confidence"], "measured")
        self.assertGreater(card["score"], 0)

    def test_trace_metrics_emit_p50_latency(self):
        metrics = self.service().trace_metrics([
            {"timestamp": 1.0, "status": "success", "routed_model": "model-a", "latency_ms": 300},
            {"timestamp": 2.0, "status": "success", "routed_model": "model-a", "latency_ms": 100},
            {"timestamp": 3.0, "status": "error", "routed_model": "model-a", "latency_ms": 200},
            {"timestamp": 4.0, "status": "success", "routed_model": "model-b", "latency_ms": 100},
            {"timestamp": 5.0, "status": "success", "routed_model": "model-b", "latency_ms": 400},
            {"timestamp": 6.0, "status": "success", "routed_model": "model-c"},
        ])

        self.assertEqual(metrics["model-a"]["p50_latency_ms"], 200)
        self.assertEqual(metrics["model-b"]["p50_latency_ms"], 400)
        self.assertIsNone(metrics["model-c"]["p50_latency_ms"])
        self.assertIsNone(median_latency_ms([]))

    def test_scorecards_default_trace_shape_includes_p50(self):
        payload = self.service().payload(days=30)

        self.assertIsNone(payload["by_model"]["model-b"]["trace"]["p50_latency_ms"])
        self.assertIn("p95_latency_ms", payload["by_model"]["model-b"]["trace"])

    def test_health_grade_maps_success_and_latency_boundaries(self):
        self.assertEqual(health_grade(1.0, 900), "A")
        self.assertEqual(health_grade(0.99, 1500), "A")
        self.assertEqual(health_grade(1.0, None), "A")
        self.assertEqual(health_grade(0.99, 1501), "B")
        self.assertEqual(health_grade(0.9899, 900), "B")
        self.assertEqual(health_grade(0.97, 3000), "B")
        self.assertEqual(health_grade(0.97, 3001), "C")
        self.assertEqual(health_grade(0.9699, 900), "C")
        self.assertEqual(health_grade(0.95, 50000), "C")
        self.assertEqual(health_grade(0.5, 10000), "C")
        self.assertEqual(health_grade(None, None), "C")
        self.assertEqual(health_grade(0.89, 10001), "D")
        self.assertEqual(health_grade(0.0, 99999), "D")
        self.assertEqual(health_grade(None, 10001), "D")
        self.assertEqual(health_grade("bad", 10001), "D")

    def test_scorecards_mark_stale_and_unavailable_samples(self):
        now = datetime.datetime(2026, 7, 9, tzinfo=datetime.timezone.utc).timestamp()
        stale_ts = now - 10 * 86400
        payload = self.service(
            traces=[{"timestamp": stale_ts, "status": "success", "requested_model": "model-a", "cost_usd": 0.01, "latency_ms": 1000}],
            now=now,
        ).payload(days=30)

        self.assertEqual(payload["by_model"]["model-a"]["confidence"], "stale")
        self.assertTrue(payload["by_model"]["model-a"]["stale"])
        self.assertEqual(payload["by_model"]["model-b"]["confidence"], "unavailable")
        self.assertEqual(payload["by_model"]["model-b"]["score"], 0)


if __name__ == "__main__":
    unittest.main()
