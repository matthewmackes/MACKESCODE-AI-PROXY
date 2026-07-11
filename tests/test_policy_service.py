import unittest

from src.console.policy import PolicyDecision, PolicyService


class PolicyServiceTests(unittest.TestCase):
    def service(self):
        return PolicyService(
            get_permissions={"/api/audit": ("audit_view", "audit.view")},
            post_permissions={"/api/dedicated/build": ("dedicated_admin", "dedicated.build")},
        )

    def test_policy_decision_serializes_required_fields(self):
        decision = PolicyDecision.deny(
            "rbac",
            "audit.view",
            "missing_permission",
            actor={"id": "viewer"},
            subject={"permission": "audit_view"},
            matched_policy={"permission": "audit_view"},
        )

        payload = decision.to_dict()
        restored = PolicyDecision.from_dict(payload)

        self.assertFalse(payload["allowed"])
        self.assertEqual(restored.domain, "rbac")
        self.assertEqual(restored.action, "audit.view")
        self.assertEqual(restored.subject["permission"], "audit_view")

    def test_rbac_policy_precedence_and_unrestricted_routes(self):
        service = self.service()
        viewer = {"id": "viewer", "roles": ["viewer"], "permissions": ["view_console"], "source": "test"}
        owner = {"id": "owner", "roles": ["owner"], "permissions": ["*"], "source": "test"}

        unrestricted = service.request_decision("GET", "/api/status", viewer)
        denied = service.request_decision("GET", "/api/audit", viewer)
        allowed = service.request_decision("GET", "/api/audit", owner)

        self.assertTrue(unrestricted.allowed)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.effects["permission"], "audit_view")
        self.assertTrue(allowed.allowed)

    def test_quota_decision_wraps_blocks_and_warnings(self):
        service = self.service()
        wrapped = service.quota_decision({
            "managed": True,
            "allowed": False,
            "status": "blocked",
            "action": "chat",
            "route": "/api/chat",
            "blocks": [{"source": "default", "metric": "usd"}],
            "checks": [{"metric": "usd"}],
        })

        payload = wrapped.to_dict()

        self.assertEqual(payload["domain"], "quota")
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["matched_policy"]["blocks"][0]["metric"], "usd")

    def test_dedicated_lifecycle_and_override_decisions(self):
        service = self.service()
        cfg = {"state": "active", "model_id": "dedicated-inference"}
        lifecycle = service.dedicated_lifecycle_decision(
            cfg,
            {"warning": False, "teardown_due": True, "extension_expired_unused": False},
            {"unhealthy": False, "teardown_due": False},
        )
        budget = service.dedicated_build_budget_decision({"critical": True, "percent": 99}, cfg=cfg)
        keep_alive = service.dedicated_keep_alive_decision(cfg, 600, {300, 600})

        self.assertFalse(lifecycle.allowed)
        self.assertEqual(lifecycle.action, "teardown")
        self.assertFalse(budget.allowed)
        self.assertTrue(keep_alive.allowed)

    def test_gateway_decision_identifies_blocking_metadata(self):
        service = self.service()
        decision = service.gateway_decision({"decision": "rate_limited", "model": "model-a"})

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.domain, "gateway")


if __name__ == "__main__":
    unittest.main()
