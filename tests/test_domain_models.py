import unittest

from src.console.domain.auth import ActorIdentity, PermissionDecision
from src.console.domain.dedicated import DedicatedConfig, LifecycleEvent
from src.console.domain.gateway import GatewayDecision
from src.console.domain.models import ModelRecord
from src.console.domain.results import ErrorInfo
from src.console.domain.traces import MessageSummary, TraceRecord


class DomainModelTests(unittest.TestCase):
    def test_actor_identity_serializes_and_checks_permissions(self):
        actor = ActorIdentity.from_dict({"id": "ops", "roles": ["operator"], "permissions": ["view_console"], "source": "test"})

        self.assertTrue(actor.has_permission("view_console"))
        self.assertEqual(actor.to_dict()["id"], "ops")
        self.assertEqual(ActorIdentity.from_dict({}).to_dict()["id"], "anonymous")

    def test_trace_record_validates_and_preserves_extra_fields(self):
        summary = MessageSummary.from_messages([{"role": "user", "content": "hello private world"}], limit=5)
        trace = TraceRecord.from_dict({
            "trace_id": "trace-a",
            "timestamp": 1000,
            "status": "success",
            "latency_ms": -5,
            "message_summary": summary.to_dict(),
            "gateway_policy": {"decision": "fallback"},
        })

        payload = trace.to_dict()

        self.assertEqual(payload["latency_ms"], 0)
        self.assertEqual(payload["message_summary"]["last_user_preview"], "hello")
        self.assertEqual(payload["gateway_policy"], {"decision": "fallback"})
        with self.assertRaisesRegex(ValueError, "trace_id"):
            TraceRecord.from_dict({"timestamp": 1})

    def test_gateway_model_dedicated_result_records_validate_required_fields(self):
        self.assertEqual(GatewayDecision.from_dict({"decision": "selected", "model": "model-a"}).to_dict()["selected_model"], "model-a")
        self.assertEqual(ModelRecord.from_dict({"id": "model-a", "pricing": {"input": 1, "output": 2}}).to_dict()["pricing"]["output_usd_per_1m"], 2.0)
        self.assertEqual(DedicatedConfig.from_dict({"state": "ready", "daily_budget_usd": 3}).to_dict()["daily_budget_usd"], 3.0)
        self.assertEqual(LifecycleEvent.from_dict({"type": "ready"}).to_dict()["severity"], "info")
        self.assertEqual(ErrorInfo.from_dict({"error": "failed", "code": "bad"}).to_dict()["message"], "failed")
        with self.assertRaisesRegex(ValueError, "permission"):
            PermissionDecision.from_dict({"allowed": True})


if __name__ == "__main__":
    unittest.main()
