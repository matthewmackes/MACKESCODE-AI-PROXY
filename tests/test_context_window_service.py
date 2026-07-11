import unittest

from src.console.services.context_window import ContextWindowService


class ContextWindowServiceTests(unittest.TestCase):
    def service(self, models=None, dataset=None, load_eval_dataset=None):
        return ContextWindowService(
            model_registry=lambda: models or [
                {"id": "model-a", "display_name": "Model A", "context_window": 100, "max_output_tokens": 20, "aliases": ["a"]},
                {"id": "model-b", "display_name": "Model B", "context_window": 1000, "max_output_tokens": 200},
            ],
            default_text_model=lambda: "model-a",
            load_eval_dataset=load_eval_dataset or (lambda dataset_id: dataset or {"examples": [{"input": "short question", "expected": "short answer"}]}),
            clock=lambda: 1700000000,
        )

    def test_chat_estimate_reports_per_message_rows_and_remaining_context(self):
        payload = self.service().inspect({
            "action": "chat",
            "payload": {
                "model": "model-a",
                "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello world"}],
                "max_tokens": 10,
            },
        })

        self.assertEqual(payload["action"], "chat")
        self.assertEqual(payload["message_count"], 2)
        self.assertEqual(payload["models"][0]["model"], "model-a")
        self.assertGreater(payload["models"][0]["remaining_context_tokens"], 0)
        self.assertEqual(payload["messages"][0]["role"], "system")

    def test_warning_when_requested_output_does_not_fit(self):
        text = " ".join(["token"] * 55)
        payload = self.service().inspect({
            "action": "chat",
            "payload": {"model": "model-a", "messages": [{"role": "user", "content": text}], "max_tokens": 20},
        })

        self.assertFalse(payload["models"][0]["fits"])
        codes = {warning["code"] for warning in payload["warnings"]}
        self.assertIn("output_exceeds_remaining_context", codes)

    def test_missing_context_metadata_warns_without_blocking_fit(self):
        payload = self.service(models=[{"id": "unknown-meta"}]).inspect({
            "action": "chat",
            "payload": {"model": "unknown-meta", "messages": [{"role": "user", "content": "hi"}]},
        })

        self.assertTrue(payload["models"][0]["fits"])
        self.assertIn("missing_context_window", {warning["code"] for warning in payload["warnings"]})

    def test_eval_uses_dataset_examples_and_selected_models(self):
        dataset = {"examples": [{"input": "A" * 120, "expected": "B"}, {"input": "short"}]}
        payload = self.service(dataset=dataset).inspect({
            "action": "eval",
            "payload": {"dataset_id": "smoke", "models": ["model-a", "model-b"], "max_examples": 1, "max_tokens": 5},
        })

        self.assertEqual(len(payload["models"]), 2)
        self.assertEqual(payload["message_count"], 1)
        self.assertEqual(payload["messages"][0]["role"], "eval_example")

    def test_missing_eval_dataset_warns_instead_of_raising(self):
        def missing(dataset_id):
            raise ValueError("Eval dataset '%s' was not found." % dataset_id)

        payload = self.service(load_eval_dataset=missing).inspect({
            "action": "eval",
            "payload": {"dataset_id": "smoke", "models": ["model-a"], "max_tokens": 5},
        })

        self.assertEqual(payload["message_count"], 1)
        self.assertEqual(payload["messages"][0]["role"], "eval_dataset_unavailable")
        self.assertIn("eval_dataset_unavailable", {warning["code"] for warning in payload["warnings"]})
        self.assertEqual(payload["warnings"][0]["dataset_id"], "smoke")

    def test_malformed_eval_dataset_errors_still_raise(self):
        def malformed(_dataset_id):
            raise ValueError("Eval dataset must include at least one example.")

        with self.assertRaisesRegex(ValueError, "at least one example"):
            self.service(load_eval_dataset=malformed).inspect({
                "action": "eval",
                "payload": {"dataset_id": "broken", "models": ["model-a"]},
            })

    def test_code_launch_prompt_includes_tool_and_project_context(self):
        payload = self.service().inspect({
            "action": "code",
            "payload": {
                "model": "model-b",
                "project_dir": "/repo",
                "print_prompt": "Fix failing tests",
                "allowed_tools": "Read Grep",
            },
        })

        self.assertEqual(payload["models"][0]["model"], "model-b")
        self.assertEqual(payload["messages"][0]["role"], "code_launch")
        self.assertIn("Fix failing tests", payload["messages"][0]["preview"])


if __name__ == "__main__":
    unittest.main()
