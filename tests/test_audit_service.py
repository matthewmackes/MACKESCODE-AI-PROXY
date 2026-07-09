import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.audit import AuditService


class AuditServiceTests(unittest.TestCase):
    def test_append_redacts_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            service = AuditService(audit_file=lambda: path, clock=lambda: 123)
            service.append(
                "dedicated.build",
                actor={"id": "operator-a", "roles": ["infra_admin"], "source": "role-token"},
                permission="dedicated_admin",
                request={"token": "secret", "nested": {"access_token": "secret2", "model": "qwen"}},
                status=200,
            )

            record = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(record["action"], "dedicated.build")
        self.assertEqual(record["actor"]["id"], "operator-a")
        self.assertEqual(record["request"]["token"], "[redacted]")
        self.assertEqual(record["request"]["nested"]["access_token"], "[redacted]")
        self.assertEqual(record["request"]["nested"]["model"], "qwen")
