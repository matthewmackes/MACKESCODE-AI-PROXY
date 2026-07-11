import tempfile
import unittest
from pathlib import Path

from src.console.services.replay import ReplayService


class ReplayServiceTests(unittest.TestCase):
    def service(self, root, traces=None, chats=None, calls=None):
        traces = traces if traces is not None else []
        chats = chats if chats is not None else {}
        calls = calls if calls is not None else []

        def chat_completion(data):
            calls.append(data)
            model = data["model"]
            return 200, {
                "text": "answer from " + model,
                "routing": {"requested": model, "used": model, "backend": "serverless"},
                "usage": {"input_tokens": 4, "output_tokens": 5},
                "cost": {"total_cost_usd": 0.01},
                "trace_id": "trace-" + model,
            }

        return ReplayService(
            read_traces=lambda **kwargs: traces,
            load_chat=lambda chat_id: chats.get(chat_id),
            chat_completion=chat_completion,
            default_text_model=lambda: "model-default",
            text_models=lambda: ["model-a", "model-b", "model-default"],
            replay_file=lambda: Path(root) / "replays.jsonl",
            append_trace=lambda record: record,
            clock=lambda: 1000.0,
        )

    def test_chat_snapshot_replays_selected_comparison_and_records_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            service = self.service(tmp, chats={
                "chat-a": {
                    "id": "chat-a",
                    "model": "model-a",
                    "messages": [
                        {"role": "system", "content": "Be terse"},
                        {"role": "user", "content": "Say ok"},
                        {"role": "assistant", "content": "ok"},
                    ],
                }
            }, calls=calls)

            replay = service.replay({"source": {"type": "chat", "id": "chat-a"}, "target": "comparison", "models": ["model-a", "model-b"], "baseline_text": "ok"})

            self.assertEqual([call["model"] for call in calls], ["model-a", "model-b"])
            self.assertEqual(replay["summary"]["models"], 2)
            self.assertTrue(replay["results"][0]["diff"]["changed"])
            self.assertEqual(service.list_records()[0]["id"], replay["id"])

    def test_trace_snapshot_reports_redaction_limitations(self):
        service = self.service("/tmp", traces=[{
            "trace_id": "trace-a",
            "requested_model": "model-a",
            "message_summary": {"last_user_preview": "Summarize this", "last_user_chars": 200},
        }])

        snapshot = service.snapshot({"type": "trace", "id": "trace-a"})

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["redaction"], "trace_summary")
        self.assertTrue(snapshot["limitations"])
        self.assertEqual(snapshot["messages"][0]["content"], "Summarize this")

    def test_replay_rejects_unavailable_targets_and_missing_prompt(self):
        service = self.service("/tmp", traces=[{"trace_id": "trace-a", "requested_model": "model-a", "message_summary": {}}])

        with self.assertRaises(ValueError):
            service.replay({"source": {"type": "trace", "id": "trace-a"}})
        with self.assertRaises(ValueError):
            service.replay({"snapshot": {"available": True, "model": "model-a", "messages": [{"role": "user", "content": "hi"}]}, "target": "selected", "models": ["missing"]})


if __name__ == "__main__":
    unittest.main()
