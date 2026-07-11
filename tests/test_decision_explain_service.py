import json
import unittest
from pathlib import Path

from src.console.services.decision_explain import DecisionExplanationService


class DecisionExplanationServiceTests(unittest.TestCase):
    def service(self, traces=None):
        return DecisionExplanationService(
            read_traces=lambda **kwargs: traces or [],
            policy_files=lambda: {"gateway_policy": Path("config/gateway-policy.json")},
            clock=lambda: 1000.0,
        )

    def test_explains_gateway_routing_from_trace_id_and_redacts(self):
        traces = [{
            "trace_id": "trace-a",
            "requested_model": "model-a",
            "routed_model": "model-b",
            "routing_reason": "failover",
            "gateway_policy": {
                "decision": "failover",
                "slo_routing": {
                    "candidates": [{"model": "model-a"}, {"model": "model-b"}],
                    "rejected": [{"model": "model-a", "reason": "circuit_open"}],
                },
            },
            "prompt": "Bearer secret-token-value",
        }]
        payload = self.service(traces).payload({"trace_id": "trace-a"})

        self.assertEqual(payload["type"], "gateway_routing")
        self.assertEqual(payload["selected_action"], "failover")
        self.assertTrue(payload["deterministic"])
        self.assertEqual(payload["rejected_alternatives"][0]["reason"], "circuit_open")
        text = json.dumps(payload)
        self.assertIn("[redacted]", text)
        self.assertNotIn("secret-token-value", text)

    def test_explains_quota_budget_dedicated_and_eval_gate_payloads(self):
        service = self.service()
        quota = service.payload({"record": {"action": "chat", "status": "blocked", "blocks": [{"source": "default", "metric": "usd"}]}})
        budget = service.payload({"record": {"budget_state": {"critical": True, "percent": 101}}})
        dedicated = service.payload({"record": {"dedicated": {"state": "idle_warning", "idle_policy": {"teardown_due": False}}}})
        eval_gate = service.payload({"record": {"surface": "model_registry", "decision": "blocked", "required": True, "recommended_datasets": [{"id": "smoke"}]}})

        self.assertEqual(quota["type"], "quota")
        self.assertEqual(quota["selected_action"], "blocked")
        self.assertEqual(budget["type"], "budget")
        self.assertEqual(budget["selected_action"], "blocked")
        self.assertEqual(dedicated["type"], "dedicated_lifecycle")
        self.assertEqual(eval_gate["type"], "eval_gate")
        self.assertEqual(eval_gate["rejected_alternatives"][0]["id"], "smoke")

    def test_explains_structured_policy_decision(self):
        payload = self.service().payload({"record": {
            "policy_decision": {
                "domain": "rbac",
                "action": "audit.view",
                "allowed": False,
                "reason": "missing_permission",
                "actor": {"id": "viewer"},
                "subject": {"permission": "audit_view"},
                "matched_policy": {"permission": "audit_view"},
                "inputs": {"roles": ["viewer"]},
            }
        }})

        self.assertEqual(payload["type"], "authorization")
        self.assertEqual(payload["selected_action"], "audit.view")
        self.assertFalse(payload["raw"]["policy_decision"]["allowed"])
        self.assertEqual(payload["matched_policy"]["permission"], "audit_view")

    def test_missing_trace_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "trace not found"):
            self.service([]).payload({"trace_id": "missing"})


if __name__ == "__main__":
    unittest.main()
