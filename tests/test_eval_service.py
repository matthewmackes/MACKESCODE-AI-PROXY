import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services.evals import EvalService


class FakeUuid:
    hex = "abcdef1234567890"


class EvalServiceTests(unittest.TestCase):
    def service(self, chat_completion=None, models=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        dataset_dir = root / "evals"
        run_dir = root / "runs"
        dataset_dir.mkdir()
        (dataset_dir / "smoke.json").write_text(
            '{"schema_version":1,"id":"smoke","name":"Smoke","examples":[{"id":"one","input":"Reply ok","expected":"ok"}]}',
            encoding="utf-8",
        )
        calls = []

        def default_chat(data):
            calls.append(data)
            return HTTPStatus.OK, {
                "text": "ok",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "cost": {"total_cost_usd": 0.000001},
                "trace_id": "trace-a",
            }

        service = EvalService(
            evals_dir=lambda: dataset_dir,
            runs_dir=lambda: run_dir,
            chat_completion=chat_completion or default_chat,
            active_text_models=lambda: models or ["model-a", "model-b"],
            default_text_model=lambda: "model-a",
            clock=lambda: 1000,
            uuid_factory=lambda: FakeUuid(),
        )
        return service, calls

    def test_lists_and_runs_dataset_for_selected_models(self):
        service, calls = self.service()

        datasets = service.list_datasets()
        result = service.run({"dataset_id": "smoke", "models": ["model-a", "model-b"]})

        self.assertEqual(datasets[0]["id"], "smoke")
        self.assertEqual(result["id"], "eval_1000_abcdef1234")
        self.assertEqual(result["models"], ["model-a", "model-b"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["results"][0]["selected_answer"], "model-a")
        self.assertEqual(result["summary"][0]["total_cost_usd"], 0.000001)
        self.assertEqual(result["summary"][0]["pass_rate"], 1.0)
        self.assertTrue(service.run_path(result["id"]).exists())

    def test_rejects_unavailable_models_before_running(self):
        service, calls = self.service(models=["model-a"])

        with self.assertRaisesRegex(ValueError, "Unavailable eval models"):
            service.run({"dataset_id": "smoke", "models": ["missing"]})

        self.assertEqual(calls, [])

    def test_records_failures_and_baseline_deltas(self):
        def failing_chat(data):
            if data["model"] == "model-b":
                return HTTPStatus.BAD_GATEWAY, {"error": "upstream failed", "message": "upstream failed"}
            return HTTPStatus.OK, {"text": "ok", "cost": {"total_cost_usd": 0.2}}

        service, _ = self.service(chat_completion=failing_chat)
        baseline = service.run({"dataset_id": "smoke", "models": ["model-a"]})
        current = service.run({"dataset_id": "smoke", "models": ["model-a", "model-b"], "baseline_run_id": baseline["id"]})

        self.assertEqual(current["summary"][1]["failures"], 1)
        self.assertEqual(current["results"][0]["responses"][1]["error"], "upstream failed")
        self.assertEqual(current["baseline"]["id"], baseline["id"])
        self.assertEqual(current["baseline"]["deltas"][0]["model"], "model-a")

    def test_builder_requires_redaction_and_preserves_runtime_metadata(self):
        service, calls = self.service()

        with self.assertRaisesRegex(ValueError, "requires redaction_reviewed"):
            service.build_dataset({
                "id": "from-trace",
                "examples": [{"source_type": "trace", "input": "private prompt"}],
            })

        dataset = service.build_dataset({
            "id": "from-trace",
            "name": "From Trace",
            "operator_notes": "Reviewed by operator",
            "examples": [
                {
                    "source_type": "trace",
                    "redaction_reviewed": True,
                    "input": "Redacted user goal",
                    "expected": "Expected answer",
                    "trace": {
                        "trace_id": "trace-a",
                        "requested_model": "model-a",
                        "routed_model": "model-b",
                        "routing_reason": "fallback",
                        "cost_usd": 0.02,
                    },
                    "tags": ["trace"],
                }
            ],
        })
        result = service.run({"dataset_id": "from-trace", "models": ["model-a"]})

        self.assertEqual(dataset["id"], "from-trace")
        self.assertEqual(dataset["metadata"]["source_types"], ["trace"])
        self.assertEqual(dataset["examples"][0]["input"], "Redacted user goal")
        self.assertEqual(dataset["examples"][0]["metadata"]["source_trace_id"], "trace-a")
        self.assertEqual(dataset["examples"][0]["metadata"]["requested_model"], "model-a")
        self.assertEqual(dataset["examples"][0]["metadata"]["cost_usd"], 0.02)
        self.assertEqual(result["dataset"]["id"], "from-trace")
        self.assertEqual(calls[0]["messages"][0]["content"], "Redacted user goal")

    def test_manual_dataset_save_supports_editing_examples(self):
        service, _ = self.service()

        created = service.save_dataset({
            "id": "manual",
            "name": "Manual",
            "examples": [{"input": "Say ok", "expected": "ok", "metadata": {"source_type": "manual"}}],
        })
        edited = service.save_dataset({
            **created,
            "examples": [{"id": "one", "input": "Say ok now", "expected": "ok", "metadata": {"source_type": "manual"}}],
        })

        self.assertEqual(edited["examples"][0]["input"], "Say ok now")
        self.assertEqual(service.load_dataset("manual")["examples"][0]["metadata"]["source_type"], "manual")


if __name__ == "__main__":
    unittest.main()
