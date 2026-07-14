import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.api import analyst as analyst_api
from backend.v2.app import create_app


class FakeStore:
    def __init__(self):
        self.acked = []

    def acknowledge_finding(self, finding_id, actor=None):
        self.acked.append((finding_id, actor))
        if finding_id == "missing":
            return None
        return {"id": finding_id, "acknowledged": True, "acknowledged_by": (actor or {}).get("id")}


class FakeAnalystService:
    def __init__(self):
        self.calls = []
        self.store = FakeStore()

    def payload(self, force=False, actor=None):
        self.calls.append((force, actor))
        return {
            "status": "ok",
            "force": force,
            "actor_id": (actor or {}).get("id"),
            "summary": {"severity_counts": {"high": 0, "medium": 0, "low": 0}},
            "findings": [],
        }


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2AnalystApiTests(unittest.TestCase):
    def env(self, tmp, **extra):
        env = {
            "MATTS_CONSOLE_AUTH_ENABLED": "0",
            "MATTS_ANALYST_WORKER_ENABLED": "0",
            "MATTS_OPERATIONAL_DB": str(Path(tmp) / "ops.sqlite3"),
            "MATTS_ANALYST_PUBLIC_SWEEP": "0",
            "MATTS_ANALYST_LLM_ENABLED": "0",
        }
        env.update(extra)
        return env

    def test_local_owner_can_view_run_and_acknowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = FakeAnalystService()
            with patch.dict(os.environ, self.env(tmp)), \
                 patch.object(analyst_api, "analyst_service", return_value=service), \
                 patch.object(analyst_api, "enforce_cost_pause", return_value=None):
                client = TestClient(create_app())
                viewed = client.get("/v2/analyst")
                run = client.post("/v2/analyst/run", json={"force": True})
                acked = client.post("/v2/analyst/findings/f1/ack", json={})

        self.assertEqual(viewed.status_code, 200)
        self.assertEqual(run.status_code, 200)
        self.assertEqual(acked.status_code, 200)
        self.assertEqual(service.calls[0][0], False)
        self.assertEqual(service.calls[1][0], True)
        self.assertEqual(service.store.acked[0][0], "f1")

    def test_view_only_role_cannot_force_run(self):
        role_tokens = {"viewer-token": {"id": "viewer-user", "roles": ["viewer"]}}
        with tempfile.TemporaryDirectory() as tmp:
            service = FakeAnalystService()
            env = self.env(
                tmp,
                MATTS_CONSOLE_AUTH_ENABLED="1",
                MATTS_CONSOLE_AUTH_TOKEN="owner-secret",
                MATTS_CONSOLE_ROLE_TOKENS=json.dumps(role_tokens),
            )
            with patch.dict(os.environ, env), \
                 patch.object(analyst_api, "analyst_service", return_value=service), \
                 patch.object(analyst_api, "enforce_cost_pause", return_value=None):
                client = TestClient(create_app())
                viewed = client.get("/v2/analyst", headers={"x-matts-console-token": "viewer-token"})
                denied = client.post("/v2/analyst/run", headers={"x-matts-console-token": "viewer-token"}, json={"force": True})

        self.assertEqual(viewed.status_code, 200)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(len(service.calls), 1)


if __name__ == "__main__":
    unittest.main()
