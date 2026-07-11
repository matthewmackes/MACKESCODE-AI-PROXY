import unittest

from src.console.services.streaming_metrics import StreamingMetricsService


class StreamingMetricsServiceTests(unittest.TestCase):
    def test_final_metrics_use_usage_tokens_and_cost(self):
        metrics = StreamingMetricsService(clock=lambda: 11).finalize(
            started_at=1,
            first_token_at=3,
            completed_at=11,
            usage={"completion_tokens": 80},
            cost={"total_cost_usd": 0.04},
            stream_requested=True,
            client_streaming=True,
            provider_streaming=True,
            chunk_count=8,
        )

        self.assertEqual(metrics["elapsed_ms"], 10000)
        self.assertEqual(metrics["first_token_latency_ms"], 2000)
        self.assertEqual(metrics["output_tokens"], 80)
        self.assertEqual(metrics["tokens_per_second"], 10.0)
        self.assertEqual(metrics["estimated_cost_usd"], 0.04)
        self.assertEqual(metrics["route_health"], "streaming")

    def test_non_streaming_fallback_estimates_output_tokens_without_text_storage(self):
        metrics = StreamingMetricsService(clock=lambda: 5).finalize(
            started_at=1,
            completed_at=5,
            output_text="hello world from a buffered response",
            stream_requested=False,
            client_streaming=False,
            provider_streaming=False,
        )

        self.assertEqual(metrics["route_health"], "non_streaming")
        self.assertGreater(metrics["output_tokens"], 0)
        self.assertGreater(metrics["tokens_per_second"], 0)


if __name__ == "__main__":
    unittest.main()
