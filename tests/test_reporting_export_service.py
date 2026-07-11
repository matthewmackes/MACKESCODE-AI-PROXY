import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.console.services.reporting_export import ReportingExportService


class ReportingExportServiceTests(unittest.TestCase):
    def service(self, root):
        source = root / "traces.jsonl"
        source.write_text('{"trace_id":"trace-a"}\n', encoding="utf-8")
        return ReportingExportService(
            output_dir=root / "reporting",
            read_traces=lambda limit=5000: [{
                "trace_id": "trace-a",
                "timestamp": 1000,
                "status": "success",
                "action": "chat",
                "requested_model": "model-a",
                "routed_model": "model-b",
                "provider": "digitalocean",
                "endpoint_mode": "serverless",
                "routing_reason": "slo",
                "latency_ms": 1200,
                "cost_usd": 0.04,
                "messages": [{"role": "user", "content": "secret prompt"}],
            }],
            dedicated_events=lambda limit=5000: [{"timestamp": 1001, "type": "ready", "severity": "info", "data": {"model": "model-b"}}],
            list_eval_runs=lambda limit=5000: [{"id": "eval-a", "created_at": 1002, "dataset": "Smoke", "models": ["model-b"], "example_count": 1, "summary": [{"model": "model-b", "requests": 1, "failures": 0, "total_cost_usd": 0.01, "avg_latency_ms": 100, "pass_rate": 1.0}]}],
            list_comparison_reports=lambda: [{"id": "report-a", "title": "Compare", "winner_model": "model-b", "total_cost_usd": 0.02, "result_count": 2, "models": ["model-a", "model-b"]}],
            audit_rows=lambda limit=5000: [{"timestamp": 1003, "action": "model.save", "actor_id": "owner", "permission": "model_admin", "outcome": "completed", "status": 200, "token": "sk-secretvalue"}],
            review_queue_payload=lambda: {"reviews": [{"id": "review-a", "status": "open", "severity": "high", "reason": "eval", "title": "Review", "created_at": 1004, "updated_at": 1005}]},
            release_candidate_payload=lambda: {"checks": [{"name": "tests", "status": "passed", "severity": "info", "message": "ok"}]},
            cost_summary_payload=lambda: {"last_24h_total_usd": 0.5, "month_total_usd": 3.0, "token": "dop_v1_secretvalue"},
            source_files={"traces": source},
            clock=lambda: 2000,
        )

    def test_export_writes_sqlite_tables_redacts_and_records_fingerprints(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp))

            result = service.export({"format": "sqlite"})

            self.assertEqual(result["format"], "sqlite")
            self.assertTrue(Path(result["path"]).exists())
            self.assertEqual(Path(result["path"]).name, "mde-llm-proxy-reporting.sqlite")
            self.assertEqual(result["tables"]["trace_events"], 1)
            self.assertEqual(result["tables"]["eval_results"], 1)
            self.assertIn("traces", result["source_fingerprints"])

            conn = sqlite3.connect(result["path"])
            try:
                trace_json = conn.execute("SELECT payload_json FROM trace_events").fetchone()[0]
                audit_json = conn.execute("SELECT payload_json FROM audit_events_redacted").fetchone()[0]
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()

            self.assertIn("trace_events", tables)
            self.assertIn("usage_events", tables)
            self.assertEqual(json.loads(trace_json)["messages"], "[redacted]")
            self.assertEqual(json.loads(audit_json)["token"], "[redacted]")

    def test_status_reports_existing_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp))
            service.export({"format": "sqlite"})
            legacy = Path(tmp) / "reporting" / "matts-reporting.sqlite"
            legacy.write_text("legacy", encoding="utf-8")

            status = service.status()

            self.assertTrue(status["available"])
            names = {Path(row["path"]).name for row in status["exports"]}
            self.assertIn("mde-llm-proxy-reporting.sqlite", names)
            self.assertIn("matts-reporting.sqlite", names)
            self.assertTrue(all(row["format"] == "sqlite" for row in status["exports"]))


if __name__ == "__main__":
    unittest.main()
