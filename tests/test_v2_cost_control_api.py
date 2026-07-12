import json
import os
import unittest
from contextlib import contextmanager

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.api import chat as chat_api
from backend.v2.api import cost_control as cost_control_api
from backend.v2.app import create_app


@contextmanager
def console_auth_env():
    keys = ("MATTS_CONSOLE_AUTH_ENABLED", "MATTS_CONSOLE_AUTH_TOKEN", "MATTS_CONSOLE_ROLE_TOKENS")
    old_env = {key: os.environ.get(key) for key in keys}
    os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "1"
    os.environ["MATTS_CONSOLE_AUTH_TOKEN"] = "owner-token-secret"
    os.environ["MATTS_CONSOLE_ROLE_TOKENS"] = json.dumps({
        "viewer-token": {"id": "viewer-user", "roles": ["viewer"]},
        "operator-token": {"id": "operator-user", "roles": ["operator"]},
        "model-admin-token": {"id": "model-admin-user", "roles": ["model_admin"]},
    })
    try:
        yield
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeCostAdapter:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.updates = []
        self.overrides = []
        self.guards = []

    def cost_control_status(self):
        return {
            "schema_version": 1,
            "checked_at": 123.0,
            "status": "ready",
            "costs": {"monthly_total_usd": 12.0},
            "threshold": {"monthly_threshold_usd": 100.0},
            "pause": {"active": False},
            "thresholds": {},
            "payment_review": {"items": []},
        }

    def update_cost_control(self, payload):
        self.updates.append(payload)
        return {**self.cost_control_status(), "updated": payload}

    def override_cost_control(self, payload):
        self.overrides.append(payload)
        return {**self.cost_control_status(), "override": payload}

    def cost_control_guard(self, action, category="llm_service", actor=None):
        self.guards.append({"action": action, "category": category, "actor": actor or {}})
        if self.allowed:
            return True, {"action": action}
        return False, {
            "type": "cost_control_paused",
            "message": "paused",
            "action": action,
            "category": category,
        }


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2CostControlApiTests(unittest.TestCase):
    def test_status_is_visible_and_operator_can_update_threshold(self):
        old_adapter = cost_control_api.cost_adapter
        fake = FakeCostAdapter()
        cost_control_api.cost_adapter = fake
        try:
            with console_auth_env():
                client = TestClient(create_app())
                headers = {"x-matts-console-token": "operator-token"}
                status = client.get("/v2/cost-control", headers=headers)
                update = client.post("/v2/cost-control/thresholds", headers=headers, json={"monthly_threshold_usd": 250})
        finally:
            cost_control_api.cost_adapter = old_adapter

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "ready")
        self.assertEqual(update.status_code, 200)
        self.assertEqual(fake.updates[0]["monthly_threshold_usd"], 250)
        self.assertEqual(fake.updates[0]["actor"]["id"], "operator-user")

    def test_viewer_cannot_update_and_model_admin_can_override(self):
        old_adapter = cost_control_api.cost_adapter
        fake = FakeCostAdapter()
        cost_control_api.cost_adapter = fake
        try:
            with console_auth_env():
                client = TestClient(create_app())
                viewer = client.post("/v2/cost-control/thresholds", headers={"x-matts-console-token": "viewer-token"}, json={"monthly_threshold_usd": 250})
                operator_override = client.post("/v2/cost-control/override", headers={"x-matts-console-token": "operator-token"}, json={"duration_minutes": 30})
                admin_override = client.post("/v2/cost-control/override", headers={"x-matts-console-token": "model-admin-token"}, json={"duration_minutes": 30})
        finally:
            cost_control_api.cost_adapter = old_adapter

        self.assertEqual(viewer.status_code, 403)
        self.assertEqual(viewer.json()["detail"]["required_permission"], "cost_control_edit")
        self.assertEqual(operator_override.status_code, 403)
        self.assertEqual(operator_override.json()["detail"]["required_permission"], "cost_control_override")
        self.assertEqual(admin_override.status_code, 200)
        self.assertEqual(fake.overrides[0]["actor"]["id"], "model-admin-user")

    def test_chat_spend_returns_402_before_legacy_dispatch_when_paused(self):
        old_cost_adapter = cost_control_api.cost_adapter
        old_chat_adapter = chat_api.legacy_adapter
        fake_cost = FakeCostAdapter(allowed=False)

        class FailingChatAdapter:
            def chat_completion(self, payload):  # pragma: no cover - guard must stop first
                raise AssertionError("chat dispatch should be guarded")

        cost_control_api.cost_adapter = fake_cost
        chat_api.legacy_adapter = FailingChatAdapter()
        try:
            with console_auth_env():
                client = TestClient(create_app())
                response = client.post(
                    "/v2/chat",
                    headers={"x-matts-console-token": "operator-token"},
                    json={"model": "model-a", "messages": [{"role": "user", "content": "hello"}]},
                )
        finally:
            cost_control_api.cost_adapter = old_cost_adapter
            chat_api.legacy_adapter = old_chat_adapter

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.json()["detail"]["type"], "cost_control_paused")
        self.assertEqual(fake_cost.guards[0]["action"], "chat.completion")


if __name__ == "__main__":
    unittest.main()
