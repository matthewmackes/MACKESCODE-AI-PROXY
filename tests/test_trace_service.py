import tempfile
import unittest
from pathlib import Path

from src.console.services.traces import TraceService


class FakeUuid:
    hex = "abc123"


class FailingExporter:
    def export_trace(self, record):
        raise RuntimeError("collector down")


class TraceServiceTests(unittest.TestCase):
    def test_append_redacts_messages_to_summary_and_reads_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traces.jsonl"
            service = TraceService(trace_file=lambda: path, clock=lambda: 1000, uuid_factory=lambda: FakeUuid())

            summary = service.summarize_messages([
                {"role": "system", "content": "hidden"},
                {"role": "user", "content": "hello private world"},
            ])
            record = service.append({
                "action": "chat.serverless",
                "requested_model": "model-a",
                "routed_model": "model-a",
                "status": "success",
                "cost_usd": 0.02,
                "message_summary": summary,
            })

            self.assertEqual(record["trace_id"], "trace_abc123")
            self.assertEqual(record["timestamp"], 1000)
            self.assertEqual(record["message_summary"]["last_user_preview"], "hello private world")
            self.assertNotIn("hidden", path.read_text(encoding="utf-8"))
            self.assertEqual(service.read(model="model-a")[0]["trace_id"], "trace_abc123")
            self.assertEqual(service.read(model="missing"), [])
            self.assertEqual(service.read(min_cost=0.03), [])

    def test_exporter_failure_does_not_break_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traces.jsonl"
            service = TraceService(trace_file=lambda: path, clock=lambda: 1000, uuid_factory=lambda: FakeUuid(), otel_exporter=FailingExporter())

            record = service.append({"action": "chat.serverless", "status": "success"})

            self.assertEqual(record["trace_id"], "trace_abc123")
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
