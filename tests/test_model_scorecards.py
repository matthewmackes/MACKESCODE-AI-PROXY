import datetime
import unittest

from src.console.services.model_scorecards import ModelScorecardService


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
