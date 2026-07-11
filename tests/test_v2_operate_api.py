import os
import unittest

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app
from backend.v2.api import operate as operate_api


class FakeOperateAdapter:
    def __init__(self):
        self.calls = []

    def mark_config_drift_baseline(self, payload):
        self.calls.append(("baseline", payload))
        return {"summary": {"state": "clean"}, "baseline_file": "/tmp/baseline.json", "actor": payload.get("actor")}

    def acknowledge_config_drift(self, payload):
        self.calls.append(("acknowledge", payload))
        if payload.get("items") == ["missing"]:
            raise ValueError("no current drift items matched the acknowledgement request")
        return {"summary": {"state": "acknowledged"}, "acknowledged": payload.get("items"), "actor": payload.get("actor")}

    def operate_payload(self):
        return {
            "config_drift": {
                "drift": [
                    {"name": "console_config", "risk": "high", "changed": True, "acknowledged": False},
                    {"name": "tmux_registry", "risk": "low", "changed": True, "acknowledged": False},
                ]
            }
        }


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2OperateApiTests(unittest.TestCase):
    def test_config_drift_actions_delegate_with_actor_and_report_validation_errors(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        old_adapter = operate_api.operate_adapter
        fake = FakeOperateAdapter()
        try:
            os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
            operate_api.operate_adapter = fake
            client = TestClient(create_app())

            baseline_missing_confirm = client.post("/v2/operate/config-drift/baseline", json={"reason": "verified release"})
            ack_missing_confirm = client.post("/v2/operate/config-drift/acknowledge", json={"items": ["console_config"], "reason": "expected"})
            baseline_missing_items = client.post("/v2/operate/config-drift/baseline", json={"reason": "verified release", "confirm_high_risk": True})
            ack_stale_items = client.post(
                "/v2/operate/config-drift/acknowledge",
                json={"items": ["console_config"], "reason": "expected", "confirm_high_risk": True, "confirmed_high_risk_items": ["old_console_config"]},
            )
            baseline = client.post(
                "/v2/operate/config-drift/baseline",
                json={"reason": "verified release", "confirm_high_risk": True, "confirmed_high_risk_items": ["console_config"]},
            )
            acknowledged = client.post(
                "/v2/operate/config-drift/acknowledge",
                json={"items": ["console_config"], "reason": "expected", "confirm_high_risk": True, "confirmed_high_risk_items": ["console_config"]},
            )
            low_risk_ack = client.post("/v2/operate/config-drift/acknowledge", json={"items": ["tmux_registry"], "reason": "expected"})
            invalid = client.post("/v2/operate/config-drift/acknowledge", json={"items": ["missing"]})

            self.assertEqual(baseline_missing_confirm.status_code, 400)
            self.assertEqual(baseline_missing_confirm.json()["detail"]["code"], "config_drift_high_risk_confirmation_required")
            self.assertEqual(ack_missing_confirm.status_code, 400)
            self.assertEqual(ack_missing_confirm.json()["detail"]["items"], ["console_config"])
            self.assertEqual(baseline_missing_items.status_code, 400)
            self.assertEqual(baseline_missing_items.json()["detail"]["code"], "config_drift_high_risk_confirmation_items_mismatch")
            self.assertEqual(baseline_missing_items.json()["detail"]["items"], ["console_config"])
            self.assertEqual(baseline_missing_items.json()["detail"]["confirmed_items"], [])
            self.assertEqual(ack_stale_items.status_code, 400)
            self.assertEqual(ack_stale_items.json()["detail"]["code"], "config_drift_high_risk_confirmation_items_mismatch")
            self.assertEqual(ack_stale_items.json()["detail"]["items"], ["console_config"])
            self.assertEqual(ack_stale_items.json()["detail"]["confirmed_items"], ["old_console_config"])
            self.assertEqual(baseline.status_code, 200)
            self.assertEqual(acknowledged.status_code, 200)
            self.assertEqual(low_risk_ack.status_code, 200)
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(invalid.json()["detail"]["code"], "config_drift_ack_invalid")
            self.assertEqual(fake.calls[0][0], "baseline")
            self.assertEqual(fake.calls[0][1]["actor"]["id"], "auth-disabled")
            self.assertTrue(fake.calls[0][1]["confirm_high_risk"])
            self.assertEqual(fake.calls[0][1]["confirmed_high_risk_items"], ["console_config"])
            self.assertEqual(fake.calls[1][1]["items"], ["console_config"])
            self.assertTrue(fake.calls[1][1]["confirm_high_risk"])
            self.assertEqual(fake.calls[1][1]["confirmed_high_risk_items"], ["console_config"])
            self.assertEqual(fake.calls[2][1]["items"], ["tmux_registry"])
            self.assertEqual(acknowledged.json()["actor"]["id"], "auth-disabled")
        finally:
            operate_api.operate_adapter = old_adapter
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth


if __name__ == "__main__":
    unittest.main()
