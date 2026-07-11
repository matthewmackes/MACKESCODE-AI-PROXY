import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.audit import AuditService
from src.console.services.traces import TraceService
from src.console.store import RuntimeStateRepository


class RuntimeStateRepositoryTests(unittest.TestCase):
    def test_atomic_json_write_read_migration_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            repo = RuntimeStateRepository(lambda: path, "state", schema_version=1, redacted_keys={"token"})

            written = repo.write_json({"schema_version": 0, "token": "secret", "value": 1})
            loaded = repo.read_json(migrations=[lambda data: {**data, "schema_version": 1}])
            fingerprint = repo.fingerprint()

            self.assertEqual(written["token"], "[redacted]")
            self.assertEqual(loaded["schema_version"], 1)
            self.assertTrue(fingerprint["exists"])
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_jsonl_read_skips_or_preserves_malformed_rows_and_discovers_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rows.jsonl"
            backup = Path(tmp) / "rows.jsonl.bak"
            path.write_text('{"id":1}\nnot-json\n{"id":2}\n', encoding="utf-8")
            backup.write_text("backup\n", encoding="utf-8")
            repo = RuntimeStateRepository(lambda: path, "rows")

            skipped = repo.read_jsonl(limit=10)
            raw = repo.read_jsonl(limit=10, malformed="raw")
            metadata = repo.metadata()

            self.assertEqual([row["id"] for row in skipped], [1, 2])
            self.assertEqual(raw[1]["raw"], "not-json")
            self.assertEqual(metadata["schema_version"], 1)
            self.assertEqual(metadata["backups"][0]["path"], str(backup))

    def test_trace_and_audit_services_use_repositories(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "traces.jsonl"
            audit_path = Path(tmp) / "audit.jsonl"
            trace = TraceService(trace_file=lambda: trace_path, clock=lambda: 1000)
            audit = AuditService(audit_file=lambda: audit_path, clock=lambda: 1000)

            trace.append({"action": "chat", "status": "success", "messages": [{"content": "private"}]})
            audit.append("policy.apply", request={"token": "secret"})

            stored_trace = json.loads(trace_path.read_text(encoding="utf-8"))
            stored_audit = json.loads(audit_path.read_text(encoding="utf-8"))

            self.assertEqual(stored_trace["messages"], "[redacted]")
            self.assertEqual(stored_audit["request"]["token"], "[redacted]")
            self.assertEqual(trace.metadata()["name"], "traces")
            self.assertEqual(audit.metadata()["name"], "audit")


if __name__ == "__main__":
    unittest.main()
