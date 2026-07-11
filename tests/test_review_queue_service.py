import tempfile
import unittest
from pathlib import Path

from src.console.services.review_queue import ReviewQueueService


class ReviewQueueServiceTests(unittest.TestCase):
    def service(self, root, audits=None, saved=None):
        audits = audits if audits is not None else []
        saved = saved if saved is not None else []
        return ReviewQueueService(
            review_file=lambda: Path(root) / "reviews.jsonl",
            save_eval_dataset=lambda payload: saved.append(payload) or {"id": payload["id"], "examples": payload["examples"]},
            worklist_file=lambda: Path(root) / "WORKLIST.md",
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=lambda: 1000.0,
        )

    def test_create_update_filter_and_redact_review_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            audits = []
            service = self.service(tmp, audits=audits)
            item = service.create({
                "title": "High cost trace",
                "severity": "critical",
                "reason": "high_cost_run",
                "source": {"type": "trace", "trace_id": "trace-a", "token": "secret"},
                "evidence": {"prompt": "secret prompt", "cost_usd": 4.2},
            }, actor={"id": "owner"})
            updated = service.update(item["id"], {"status": "approved", "notes": "Known workload"}, actor={"id": "reviewer"})

            self.assertEqual(item["source"]["token"], "[redacted]")
            self.assertEqual(item["evidence"]["prompt"], "[redacted]")
            self.assertEqual(updated["status"], "approved")
            self.assertEqual(service.list_items(status="approved")[0]["id"], item["id"])
            self.assertEqual(audits[0][1]["permission"], "review.queue")

    def test_auto_from_eval_gate_and_trace_create_review_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            gate_item = service.auto_from_eval_gate({
                "allowed": False,
                "required": True,
                "surface": "model_registry",
                "decision": "blocked",
                "change": {"hash": "abc"},
                "recommended_datasets": [{"id": "smoke"}],
            })
            trace_item = service.auto_from_trace({"trace_id": "trace-a", "status": "error", "cost_usd": 2.0, "messages": [{"content": "secret"}]})

            self.assertEqual(gate_item["reason"], "eval_gate_blocked")
            self.assertEqual(gate_item["severity"], "high")
            self.assertIn("trace_failure", trace_item["reason"])
            self.assertEqual(trace_item["evidence"]["messages"], "[redacted]")

    def test_promote_review_to_eval_dataset_and_worklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = []
            service = self.service(tmp, saved=saved)
            item = service.create({"title": "Routing failure", "reason": "routing_uncertainty", "notes": "Expected fallback"})
            eval_result = service.promote_to_eval(item["id"], {"dataset_id": "review-regression", "input": "Reply ok", "expected": "ok"}, actor={"id": "owner"})
            worklist_result = service.promote_to_worklist(item["id"], {"title": "Investigate route", "notes": "Follow up"}, actor={"id": "owner"})

            self.assertEqual(saved[0]["id"], "review-regression")
            self.assertEqual(saved[0]["examples"][0]["metadata"]["review_item_id"], item["id"])
            self.assertEqual(eval_result["promotion"]["type"], "eval_example")
            self.assertEqual(worklist_result["promotion"]["type"], "worklist_followup")
            self.assertIn("Investigate route", (Path(tmp) / "WORKLIST.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
