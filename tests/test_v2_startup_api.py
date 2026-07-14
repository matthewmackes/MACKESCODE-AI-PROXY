import json
import os
import unittest
from contextlib import contextmanager

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.api import startup as startup_api
from backend.v2.app import create_app


@contextmanager
def startup_auth_env():
    keys = ("MATTS_CONSOLE_AUTH_ENABLED", "MATTS_CONSOLE_AUTH_TOKEN", "MATTS_CONSOLE_ROLE_TOKENS", "MATTS_ANALYST_WORKER_ENABLED", "MATTS_STARTUP_CONSOLE_RUNTIME_ENABLED")
    old_env = {key: os.environ.get(key) for key in keys}
    os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "1"
    os.environ["MATTS_CONSOLE_AUTH_TOKEN"] = "owner-token-secret"
    os.environ["MATTS_ANALYST_WORKER_ENABLED"] = "0"
    os.environ["MATTS_STARTUP_CONSOLE_RUNTIME_ENABLED"] = "0"
    os.environ["MATTS_CONSOLE_ROLE_TOKENS"] = json.dumps({
        "viewer-token": {"id": "viewer-user", "roles": ["viewer"]},
        "infra-token": {"id": "infra-user", "roles": ["infra_admin"]},
    })
    try:
        yield
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeStartupManager:
    def status_payload(self):
        return {
            "generated_at": 1,
            "config": {"schema_version": 1, "services": {"irc-bridge": {"enabled": True}}},
            "services": [{"id": "irc-bridge", "label": "IRC", "running": False, "boot_enabled": True, "errors": []}],
            "summary": {"services": 1, "boot_enabled": 1, "running": 0, "errors": 0},
            "tmux_tmpdir": "/tmp/tmux",
        }

    def update_config(self, payload):
        return {"config": payload, "results": {}, "payload": self.status_payload()}

    def action(self, service_id, action, payload):
        if service_id == "proxy" and action == "restart" and payload.get("confirm") != "restart:proxy":
            raise ValueError("restart for proxy requires confirmation")
        return {"service_id": service_id, "action": action, "result": {"ok": True}, "payload": self.status_payload()}


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2StartupApiTests(unittest.TestCase):
    def test_viewer_can_read_startup_but_cannot_change_it(self):
        old_manager = startup_api.manager
        startup_api.manager = FakeStartupManager()
        try:
            with startup_auth_env():
                client = TestClient(create_app())
                read_response = client.get("/v2/startup", headers={"x-matts-console-token": "viewer-token"})
                write_response = client.post("/v2/startup/config", json={"services": {"irc-bridge": {"enabled": False}}}, headers={"x-matts-console-token": "viewer-token"})
        finally:
            startup_api.manager = old_manager

        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(write_response.status_code, 403)
        self.assertEqual(write_response.json()["detail"]["required_permission"], "startup_admin")

    def test_infra_admin_can_manage_startup_services(self):
        old_manager = startup_api.manager
        startup_api.manager = FakeStartupManager()
        try:
            with startup_auth_env():
                client = TestClient(create_app())
                response = client.post(
                    "/v2/startup/services/irc-bridge/start",
                    json={},
                    headers={"x-matts-console-token": "infra-token"},
                )
        finally:
            startup_api.manager = old_manager

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service_id"], "irc-bridge")

    def test_core_restart_requires_confirmation(self):
        old_manager = startup_api.manager
        startup_api.manager = FakeStartupManager()
        try:
            with startup_auth_env():
                client = TestClient(create_app())
                denied = client.post("/v2/startup/services/proxy/restart", json={}, headers={"x-matts-console-token": "infra-token"})
                allowed = client.post(
                    "/v2/startup/services/proxy/restart",
                    json={"confirm": "restart:proxy"},
                    headers={"x-matts-console-token": "infra-token"},
                )
        finally:
            startup_api.manager = old_manager

        self.assertEqual(denied.status_code, 400)
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
