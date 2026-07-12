import unittest

from backend.v2.contracts import (
    ActorIdentity,
    AuditEvent,
    ErrorEnvelope,
    EventEnvelope,
    NotificationEnvelope,
    ReportExportEnvelope,
    TraceSummary,
)
from backend.v2.services.capabilities import V2CapabilityService


class V2CapabilityServiceTests(unittest.TestCase):
    def test_owner_has_all_capabilities(self):
        service = V2CapabilityService()
        payload = service.capabilities_for({"id": "owner", "roles": ["owner"], "permissions": ["*"], "source": "test"})

        self.assertIn("tui.control", payload["allowed"])
        self.assertTrue(payload["capabilities"]["models.admin"]["allowed"])
        self.assertTrue(payload["capabilities"]["operate.review.manage"]["allowed"])
        self.assertTrue(payload["capabilities"]["operate.repository.import"]["allowed"])
        self.assertTrue(payload["capabilities"]["operate.rollback.admin"]["allowed"])
        self.assertTrue(payload["capabilities"]["operate.automation.admin"]["allowed"])
        self.assertTrue(payload["capabilities"]["operate.config_drift.admin"]["allowed"])
        self.assertTrue(payload["capabilities"]["cost_control.edit"]["allowed"])
        self.assertTrue(payload["capabilities"]["cost_control.override"]["allowed"])
        self.assertEqual(payload["actor"]["id"], "owner")

    def test_viewer_can_view_tui_but_cannot_control(self):
        service = V2CapabilityService()
        identity = ActorIdentity(id="viewer", roles=("viewer",), permissions=("view_console", "view_traces"))
        payload = service.capabilities_for(identity)

        self.assertTrue(payload["capabilities"]["tui.view"]["allowed"])
        self.assertTrue(payload["capabilities"]["run.view"]["allowed"])
        self.assertFalse(payload["capabilities"]["run.edit"]["allowed"])
        self.assertFalse(payload["capabilities"]["tui.control"]["allowed"])
        self.assertFalse(payload["capabilities"]["operate.review.manage"]["allowed"])
        self.assertFalse(payload["capabilities"]["operate.automation.admin"]["allowed"])
        self.assertFalse(payload["capabilities"]["operate.config_drift.admin"]["allowed"])
        self.assertFalse(payload["capabilities"]["cost_control.edit"]["allowed"])
        self.assertFalse(payload["capabilities"]["cost_control.override"]["allowed"])
        self.assertEqual(payload["capabilities"]["tui.control"]["reason"], "missing_permission:tmux_control")

    def test_cost_control_permissions_are_separate_for_edit_and_override(self):
        service = V2CapabilityService()
        edit = service.decide({"id": "billing", "permissions": ["cost_control_edit"]}, "cost_control.edit")
        override = service.decide({"id": "billing", "permissions": ["cost_control_edit"]}, "cost_control.override")

        self.assertTrue(edit.allowed)
        self.assertEqual(edit.required_permission, "cost_control_edit")
        self.assertFalse(override.allowed)
        self.assertEqual(override.required_permission, "cost_control_override")

    def test_config_drift_admin_uses_dedicated_permission(self):
        service = V2CapabilityService()
        allowed = service.decide({"id": "infra", "permissions": ["config_drift_admin"]}, "operate.config_drift.admin")
        denied = service.decide({"id": "rollback", "permissions": ["rollback_admin"]}, "operate.config_drift.admin")

        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.required_permission, "config_drift_admin")
        self.assertFalse(denied.allowed)

    def test_policy_decision_reports_required_permission(self):
        service = V2CapabilityService()
        decision = service.decide({"id": "viewer", "permissions": ["view_console"]}, "tui.control")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.required_permission, "tmux_control")
        self.assertEqual(decision.reason, "missing_permission")
        self.assertEqual(decision.to_dict()["actor_id"], "viewer")

    def test_unknown_policy_action_is_denied(self):
        service = V2CapabilityService()
        decision = service.decide({"id": "owner", "permissions": ["*"]}, "unknown.action")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "unknown_action")

    def test_standard_envelopes_are_json_ready(self):
        payloads = [
            ErrorEnvelope("bad input", code="bad_input", category="client", status=400).to_dict(),
            EventEnvelope(kind="trace.created", payload={"trace_id": "t1"}).to_dict(),
            AuditEvent(action="tui.control", actor_id="operator", outcome="allowed").to_dict(),
            TraceSummary(trace_id="t1", action="chat", status="success", cost_usd=0.1).to_dict(),
            NotificationEnvelope(notification_id="n1", title="Budget", body="Threshold reached").to_dict(),
            ReportExportEnvelope(export_id="r1", schema_version=1, format="duckdb", path="build/reporting.duckdb", tables=("traces",)).to_dict(),
        ]

        for payload in payloads:
            self.assertIsInstance(payload, dict)
        self.assertEqual(payloads[0]["error"], "bad input")
        self.assertEqual(payloads[-1]["tables"], ["traces"])


if __name__ == "__main__":
    unittest.main()
