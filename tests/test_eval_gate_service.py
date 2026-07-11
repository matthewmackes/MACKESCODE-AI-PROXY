import unittest

from src.console.services.eval_gates import EvalGateBlocked, EvalGateService


class EvalGateServiceTests(unittest.TestCase):
    def service(self, datasets=None, runs=None, audits=None, now=1_000.0):
        audits = audits if audits is not None else []
        return EvalGateService(
            list_datasets=lambda: datasets or [],
            list_runs=lambda limit=100: runs or [],
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=lambda: now,
        )

    def test_recommends_datasets_from_changed_surface_and_fields(self):
        service = self.service(datasets=[
            {"id": "smoke", "name": "Smoke", "valid": True, "example_count": 2},
            {"id": "gateway-routing", "name": "Gateway routing", "description": "failover slo policy", "valid": True, "example_count": 4},
            {"id": "image-only", "name": "Image only", "valid": True, "example_count": 1},
        ])

        preview = service.preview("gateway_policy", before={"slo": False}, after={"slo": True})

        self.assertTrue(preview["change"]["changed"])
        self.assertEqual(preview["recommended_datasets"][0]["id"], "gateway-routing")
        self.assertEqual(preview["decision"], "not_required")

    def test_required_gate_blocks_without_passing_evidence_and_audits(self):
        audits = []
        service = self.service(datasets=[{"id": "smoke", "name": "Smoke", "valid": True, "example_count": 1}], audits=audits)

        with self.assertRaises(EvalGateBlocked) as ctx:
            service.enforce("model_registry", before={"models": ["a"]}, after={"models": ["b"]}, eval_gate={"policy": {"require_pass": True}}, actor={"id": "owner"})

        self.assertEqual(ctx.exception.gate["decision"], "blocked")
        self.assertEqual(audits[0][1]["outcome"], "denied")

    def test_required_gate_accepts_fresh_passing_evidence(self):
        service = self.service(
            datasets=[{"id": "smoke", "name": "Smoke", "valid": True, "example_count": 1}],
            runs=[{"id": "eval-a", "created_at": 990.0, "dataset": "smoke", "models": ["model-a"], "summary": [{"requests": 2, "failures": 0, "pass_rate": 1.0}]}],
        )

        gate = service.enforce("model_registry", before={"models": ["a"]}, after={"models": ["b"]}, eval_gate={"policy": {"require_pass": True}})

        self.assertTrue(gate["allowed"])
        self.assertEqual(gate["decision"], "passed")
        self.assertEqual(gate["evidence"][0]["id"], "eval-a")

    def test_override_requires_actor_and_reason(self):
        service = self.service(datasets=[{"id": "smoke", "name": "Smoke", "valid": True, "example_count": 1}])

        gate = service.enforce(
            "gateway_policy",
            before={"cache": False},
            after={"cache": True},
            eval_gate={"policy": {"require_pass": True}, "override": {"actor": {"id": "ops"}, "reason": "emergency routing repair"}},
        )

        self.assertEqual(gate["decision"], "override")
        self.assertTrue(gate["override"]["accepted"])


if __name__ == "__main__":
    unittest.main()
