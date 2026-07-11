import tempfile
import unittest
from pathlib import Path

from src.console.services.synthetic_load import SyntheticLoadTesterService


class SyntheticLoadTesterServiceTests(unittest.TestCase):
    def service(self, root, *, status=200, payload=None, audits=None, traces=None, clock_values=None):
        audits = audits if audits is not None else []
        traces = traces if traces is not None else []
        payload = payload if payload is not None else {
            "text": "ok",
            "routing": {"backend": "serverless", "used": "model-a"},
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            "cost": {"total_cost_usd": 0.01},
            "trace_id": "trace-a",
        }
        times = list(clock_values or [1000, 1000, 1000.05, 1000.05, 1000.10, 1000.10])

        def clock():
            return times.pop(0) if times else 1000.10

        return SyntheticLoadTesterService(
            runs_file=lambda: Path(root) / "synthetic-load-runs.jsonl",
            chat_completion=lambda data: (status, payload),
            text_models=lambda: ["model-a", "model-b"],
            default_text_model=lambda: "model-a",
            cost_forecast_payload=lambda data: {"forecast_id": "f1", "estimated_total_usd": 0.02},
            quota_planner_preview=lambda path, data: {"allowed": True, "path": path},
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            append_trace=lambda record: traces.append(record) or record,
            clock=clock,
        )

    def test_preview_enforces_safety_and_budget_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            preview = service.preview({"models": ["model-a"], "request_count": 2, "budget_cap_usd": 1})
            blocked = service.preview({"models": ["missing"], "request_count": 200, "budget_cap_usd": 10})

        self.assertFalse(preview["blocking"])
        self.assertTrue(blocked["blocking"])
        self.assertIn("Unavailable models", " ".join(blocked["safety"]["errors"]))
        self.assertIn("request_count exceeds", " ".join(blocked["safety"]["errors"]))

    def test_run_records_latency_cost_routes_audit_and_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            audits = []
            traces = []
            service = self.service(tmp, audits=audits, traces=traces)
            run = service.run({"models": ["model-a"], "request_count": 2, "budget_cap_usd": 1, "actor": {"id": "ops"}})
            runs = service.payload()["runs"]

        self.assertEqual(run["summary"]["requests"], 2)
        self.assertEqual(run["summary"]["ok"], 2)
        self.assertEqual(run["summary"]["total_cost_usd"], 0.02)
        self.assertEqual(run["summary"]["routes"], {"serverless": 2})
        self.assertEqual(runs[0]["id"], run["id"])
        self.assertEqual(audits[0][0][0], "synthetic_load.run")
        self.assertEqual(traces[0]["action"], "synthetic_load.run")

    def test_blocked_run_raises_before_provider_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)

            with self.assertRaisesRegex(ValueError, "blocked"):
                service.run({"models": ["model-a"], "request_count": 1, "budget_cap_usd": 0.001})


if __name__ == "__main__":
    unittest.main()
