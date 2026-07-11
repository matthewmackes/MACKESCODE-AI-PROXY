import tempfile
import unittest
from pathlib import Path

from src.console.services.comparison_reports import ComparisonReportService


class FixedUuid:
    hex = "abcdef1234567890"


class ComparisonReportServiceTests(unittest.TestCase):
    def service(self, tmp):
        root = Path(tmp)
        return ComparisonReportService(
            reports_dir=lambda: root,
            clock=lambda: 2000,
            uuid_factory=lambda: FixedUuid(),
        )

    def test_save_list_load_and_export_formats_redact_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            report = service.save_report({
                "prompt": "Use token=dop_v1_supersecretvalue in request",
                "models": ["model-a", "model-b"],
                "winner_model": "model-a",
                "notes": "winner is concise",
                "results": [
                    {"model": "model-a", "ok": True, "text": "answer with sk-secretvalue", "routing": {"used": "model-a", "backend": "serverless"}, "cost": {"total_cost_usd": 0.01}, "latency_ms": 123, "trace_id": "trace-a"},
                    {"model": "model-b", "ok": False, "error": "timeout", "status": 504},
                ],
            })
            listed = service.list_reports()
            loaded = service.load_report(report["id"])
            markdown = service.export_report(report["id"], "markdown")
            csv_export = service.export_report(report["id"], "csv")
            json_export = service.export_report(report["id"], "json")

        self.assertEqual(report["id"], "comparison_2000_abcdef1234")
        self.assertEqual(listed[0]["winner_model"], "model-a")
        self.assertEqual(loaded["trace_ids"], ["trace-a"])
        self.assertEqual(loaded["scorecard_links"][0]["report_id"], report["id"])
        self.assertEqual(loaded["dataset_builder_examples"][0]["source_type"], "comparison")
        self.assertNotIn("dop_v1_supersecretvalue", markdown["content"])
        self.assertNotIn("sk-secretvalue", csv_export["content"])
        self.assertEqual(json_export["content_type"], "application/json")

    def test_missing_results_export_as_empty_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            report = service.save_report({"title": "Empty comparison", "prompt": "hello"})
            csv_export = service.export_report(report["id"], "csv")

        self.assertEqual(report["results"], [])
        self.assertIn("model,routed_model,ok,status", csv_export["content"])

    def test_unsupported_export_and_missing_report_raise_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            report = service.save_report({"prompt": "hello"})

            with self.assertRaises(ValueError):
                service.export_report(report["id"], "pdf")
            with self.assertRaises(ValueError):
                service.export_report("missing", "json")


if __name__ == "__main__":
    unittest.main()
