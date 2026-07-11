import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.audit_explorer import AuditExplorerService


class AuditExplorerServiceTests(unittest.TestCase):
    def write_rows(self, path, rows):
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                if isinstance(row, str):
                    handle.write(row + "\n")
                else:
                    handle.write(json.dumps(row) + "\n")

    def service(self, path):
        return AuditExplorerService(audit_file=lambda: path)

    def row(self, ts, action="model.save", actor="ops", roles=None, **extra):
        return {
            "ts": ts,
            "action": action,
            "outcome": extra.get("outcome", "completed"),
            "permission": extra.get("permission", "model_admin"),
            "status": extra.get("status", 200),
            "actor": {"id": actor, "roles": roles or ["infra_admin"], "source": "token"},
            "request": extra.get("request", {"path": "/api/models", "session_id": "session-a", "model": "model-a", "token": "secret"}),
        }

    def test_filters_redacts_and_links_related_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            self.write_rows(path, [
                self.row(1, action="review.update", actor="alice", request={"path": "/api/reviews/update", "review_id": "review-a", "trace_id": "trace-a", "authorization": "secret"}),
                self.row(2, action="config_drift.acknowledge", actor="bob", outcome="denied", status=403, request={"path": "/api/config-drift/acknowledge", "session_id": "session-b"}),
            ])
            payload = self.service(path).payload({"actor": "alice", "action": "review", "q": "trace-a"})

        self.assertEqual(payload["summary"]["returned"], 1)
        record = payload["records"][0]
        self.assertEqual(record["actor_id"], "alice")
        self.assertEqual(record["request"]["authorization"], "[redacted]")
        targets = {link["target"] for link in record["related_links"]}
        self.assertIn("console:traces", targets)
        self.assertIn("console:reviews", targets)

    def test_windowing_skips_invalid_records_and_exports_csv_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            self.write_rows(path, [
                self.row(1, actor="old"),
                "not-json",
                self.row(2, actor="mid", status=403, outcome="denied"),
                self.row(3, actor="new", request={"path": "/api/cost-anomalies/update", "id": "cost-a"}),
            ])
            service = self.service(path)
            payload = service.payload({"limit": "2", "scan_limit": "2"})
            csv_export = service.export({"limit": "3"}, fmt="csv")
            json_export = service.export({"actor": "new"}, fmt="json")

        self.assertEqual(payload["summary"]["invalid_records"], 1)
        self.assertEqual([row["actor_id"] for row in payload["records"]], ["new", "mid"])
        self.assertIn("actor_id,action,permission", csv_export["content"])
        self.assertEqual(json.loads(json_export["content"])["records"][0]["actor_id"], "new")

    def test_missing_file_returns_empty_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(Path(tmp) / "missing.jsonl").payload()

        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["summary"]["invalid_records"], 0)


if __name__ == "__main__":
    unittest.main()
