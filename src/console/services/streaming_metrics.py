"""Streaming response metric calculations."""
import math
import time


class StreamingMetricsService:
    """Compute provider/client streaming telemetry without storing full text."""

    def __init__(self, clock=None):
        self.clock = clock or time.time

    def estimate_tokens(self, text):
        text = str(text or "")
        if not text:
            return 0
        return max(1, int(math.ceil(max(len(text.split()) * 1.3, len(text) / 4.0))))

    def output_tokens(self, usage=None, output_text=""):
        usage = usage if isinstance(usage, dict) else {}
        for key in ("completion_tokens", "output_tokens"):
            try:
                value = int(usage.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        return self.estimate_tokens(output_text)

    def finalize(
        self,
        *,
        started_at,
        first_token_at=None,
        completed_at=None,
        usage=None,
        output_text="",
        cost=None,
        stream_requested=False,
        client_streaming=False,
        provider_streaming=False,
        chunk_count=0,
    ):
        completed = float(completed_at or self.clock())
        started = float(started_at or completed)
        first = float(first_token_at or completed)
        elapsed = max(0.0, completed - started)
        generation = max(0.001, completed - first)
        tokens = self.output_tokens(usage, output_text)
        cost = cost if isinstance(cost, dict) else {}
        route_health = "streaming" if provider_streaming else "client_streamed_from_buffer" if client_streaming else "non_streaming"
        return {
            "stream_requested": bool(stream_requested),
            "client_streaming": bool(client_streaming),
            "provider_streaming": bool(provider_streaming),
            "route_health": route_health,
            "elapsed_ms": int(elapsed * 1000),
            "first_token_latency_ms": int(max(0.0, first - started) * 1000),
            "generation_ms": int(generation * 1000),
            "chunk_count": max(0, int(chunk_count or 0)),
            "output_tokens": tokens,
            "tokens_per_second": round(tokens / generation, 4),
            "estimated_cost_usd": cost.get("total_cost_usd"),
        }
