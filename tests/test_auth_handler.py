import unittest

from src.console.handlers.auth_handler import AuthHandler


class AuthHandlerTests(unittest.TestCase):
    def handler(self, enabled=True, token="secret", role_tokens=None, session_verifier=None):
        return AuthHandler(
            auth_enabled=lambda: enabled,
            auth_token=lambda: token,
            role_tokens=lambda: role_tokens or {},
            session_verifier=session_verifier,
        )

    def test_request_token_prefers_query_then_header_then_bearer(self):
        handler = self.handler()

        self.assertEqual(
            handler.request_token("/?token=query-token", {"x-matts-console-token": "header-token", "authorization": "Bearer bearer-token"}),
            "query-token",
        )
        self.assertEqual(
            handler.request_token("/", {"x-matts-console-token": " header-token ", "authorization": "Bearer bearer-token"}),
            "header-token",
        )
        self.assertEqual(handler.request_token("/", {"authorization": "Bearer bearer-token"}), "bearer-token")
        self.assertEqual(handler.request_token("/", {}), "")

    def test_authorized_allows_disabled_auth_and_rejects_bad_tokens(self):
        self.assertTrue(self.handler(enabled=False).authorized("/", {}))
        self.assertTrue(self.handler().authorized("/?token=secret", {}))
        self.assertFalse(self.handler().authorized("/?token=wrong", {}))
        self.assertFalse(self.handler(token="").authorized("/", {}))

    def test_role_tokens_build_identity_and_permissions(self):
        handler = self.handler(role_tokens={
            "viewer-token": {"id": "viewer-a", "roles": ["viewer"]},
            "infra-token": {"id": "infra-a", "roles": ["infra_admin"]},
        })

        viewer = handler.identity("/", {"authorization": "Bearer viewer-token"})
        infra = handler.identity("/", {"authorization": "Bearer infra-token"})

        self.assertTrue(handler.authorized("/", {"authorization": "Bearer viewer-token"}))
        self.assertFalse(handler.authorized("/", {"authorization": "Bearer unknown-token"}))
        self.assertEqual(viewer["id"], "viewer-a")
        self.assertIn("view_console", viewer["permissions"])
        self.assertFalse(handler.has_permission(viewer, "dedicated_admin"))
        self.assertTrue(handler.has_permission(infra, "dedicated_admin"))
        self.assertEqual(handler.permission_for("POST", "/api/dedicated/build"), ("dedicated_admin", "dedicated.build"))
        self.assertEqual(handler.permission_for("POST", "/api/dedicated/capacity-plan"), ("dedicated_admin", "dedicated.capacity_plan"))
        self.assertEqual(handler.permission_for("POST", "/api/tmux/capture"), ("tmux_control", "tmux.capture"))
        self.assertEqual(handler.permission_for("POST", "/api/terminal/read"), ("tmux_control", "terminal.read"))
        self.assertEqual(handler.permission_for("GET", "/api/auth/sessions"), ("auth_session_admin", "auth.sessions.list"))
        self.assertEqual(handler.permission_for("GET", "/api/audit"), ("audit_view", "audit.view"))
        self.assertEqual(handler.permission_for("GET", "/api/audit/export"), ("audit_view", "audit.export"))
        self.assertEqual(handler.permission_for("GET", "/api/agentboard"), ("tmux_control", "agentboard.view"))
        self.assertEqual(handler.permission_for("GET", "/api/tmux/sessions"), ("tmux_control", "tmux.sessions"))
        self.assertEqual(handler.permission_for("POST", "/api/comparison-reports"), ("model_use", "comparison_report.save"))
        self.assertEqual(handler.permission_for("GET", "/api/comparison-reports/export"), ("view_traces", "comparison_report.export"))
        self.assertEqual(handler.permission_for("GET", "/api/rag"), ("view_console", "rag.view"))
        self.assertEqual(handler.permission_for("POST", "/api/rag/index"), ("model_use", "rag.index"))
        self.assertEqual(handler.permission_for("POST", "/api/tmux/permissions"), ("tmux_control", "tmux.permissions"))
        self.assertEqual(handler.permission_for("POST", "/api/session-snapshots"), ("tmux_control", "session.snapshot"))
        self.assertEqual(handler.permission_for("GET", "/api/config-drift"), ("view_console", "config_drift.view"))
        self.assertEqual(handler.permission_for("POST", "/api/config-drift/baseline"), ("config_drift_admin", "config_drift.baseline"))
        self.assertEqual(handler.permission_for("POST", "/api/config-drift/acknowledge"), ("config_drift_admin", "config_drift.acknowledge"))
        self.assertEqual(handler.permission_for("GET", "/api/rollback"), ("rollback_admin", "rollback.targets"))
        self.assertEqual(handler.permission_for("POST", "/api/rollback/preview"), ("rollback_admin", "rollback.preview"))
        self.assertEqual(handler.permission_for("POST", "/api/rollback/apply"), ("rollback_admin", "rollback.apply"))
        self.assertEqual(handler.permission_for("GET", "/api/release-candidate"), ("view_console", "release_candidate.view"))
        self.assertEqual(handler.permission_for("POST", "/api/release-candidate/report"), ("rollback_admin", "release_candidate.report"))
        self.assertEqual(handler.permission_for("GET", "/api/automation"), ("automation_admin", "automation.view"))
        self.assertEqual(handler.permission_for("POST", "/api/automation/rules"), ("automation_admin", "automation.rules"))
        self.assertEqual(handler.permission_for("POST", "/api/automation/test"), ("automation_admin", "automation.test"))
        self.assertEqual(handler.permission_for("POST", "/api/automation/run"), ("automation_admin", "automation.run"))
        self.assertEqual(handler.permission_for("GET", "/api/policies"), ("policy_admin", "policy.view"))
        self.assertEqual(handler.permission_for("POST", "/api/policies/preview"), ("policy_admin", "policy.preview"))
        self.assertEqual(handler.permission_for("POST", "/api/policies/apply"), ("policy_admin", "policy.apply"))
        self.assertEqual(handler.permission_for("POST", "/api/policies/rollback"), ("policy_admin", "policy.rollback"))
        self.assertEqual(handler.permission_for("GET", "/api/synthetic-load"), ("synthetic_load_run", "synthetic_load.view"))
        self.assertEqual(handler.permission_for("POST", "/api/synthetic-load/preview"), ("synthetic_load_run", "synthetic_load.preview"))
        self.assertEqual(handler.permission_for("POST", "/api/synthetic-load/run"), ("synthetic_load_run", "synthetic_load.run"))
        self.assertEqual(handler.permission_for("GET", "/api/cost-anomalies"), ("view_billing", "cost_anomaly.view"))
        self.assertEqual(handler.permission_for("POST", "/api/cost-anomalies/update"), ("budget_admin", "cost_anomaly.update"))
        self.assertEqual(handler.permission_for("GET", "/api/notifications"), ("view_console", "notification.view"))
        self.assertEqual(handler.permission_for("POST", "/api/notifications/update"), ("notification_update", "notification.update"))
        self.assertEqual(handler.permission_for("GET", "/api/repository-context"), ("repository_context_import", "repository_context.view"))
        self.assertEqual(handler.permission_for("POST", "/api/repository-context/preview"), ("repository_context_import", "repository_context.preview"))
        self.assertEqual(handler.permission_for("POST", "/api/repository-context/import"), ("repository_context_import", "repository_context.import"))
        self.assertEqual(handler.permission_for("GET", "/api/ci-triage"), ("repository_context_import", "ci_triage.view"))
        self.assertEqual(handler.permission_for("POST", "/api/ci-triage/preview"), ("repository_context_import", "ci_triage.preview"))
        self.assertEqual(handler.permission_for("POST", "/api/ci-triage/launch"), ("repository_context_import", "ci_triage.launch"))
        self.assertEqual(handler.permission_for("POST", "/api/patch-review"), ("tmux_control", "patch_review.generate"))
        self.assertEqual(handler.permission_for("GET", "/api/onboarding"), ("view_console", "onboarding.view"))
        self.assertEqual(handler.permission_for("POST", "/api/onboarding/complete"), ("config_drift_admin", "onboarding.complete"))
        self.assertEqual(handler.permission_for("POST", "/api/explain-decision"), ("view_console", "decision.explain"))
        self.assertEqual(handler.permission_for("GET", "/api/commands"), ("view_console", "command.list"))
        self.assertEqual(handler.permission_for("POST", "/api/commands/dispatch"), ("view_console", "command.dispatch"))
        self.assertEqual(handler.permission_for("POST", "/api/model-access-drift/acknowledge"), ("model_admin", "model_access_drift.acknowledge"))
        self.assertEqual(handler.permission_for("GET", "/api/model-deprecations"), ("model_admin", "model_deprecation.view"))
        self.assertEqual(handler.permission_for("POST", "/api/model-deprecations/apply"), ("model_admin", "model_deprecation.apply"))
        self.assertEqual(handler.permission_for("GET", "/api/offline-mode"), ("view_console", "offline_mode.view"))
        self.assertEqual(handler.permission_for("GET", "/api/workspace-bundles"), ("workspace_bundle_admin", "workspace_bundle.list"))
        self.assertEqual(handler.permission_for("POST", "/api/workspace-bundles/export"), ("workspace_bundle_admin", "workspace_bundle.export"))
        self.assertEqual(handler.permission_for("POST", "/api/workspace-bundles/preview"), ("workspace_bundle_admin", "workspace_bundle.preview"))
        self.assertEqual(handler.permission_for("POST", "/api/workspace-bundles/import"), ("workspace_bundle_admin", "workspace_bundle.import"))
        self.assertEqual(handler.permission_for("GET", "/api/reporting-integrations"), ("view_console", "reporting.integrations"))
        self.assertEqual(handler.permission_for("GET", "/api/reporting-export"), ("audit_view", "reporting.export.status"))
        self.assertEqual(handler.permission_for("POST", "/api/reporting-export"), ("audit_view", "reporting.export"))
        decision = handler.policy_decision("GET", "/api/audit", viewer)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.effects["permission"], "audit_view")
        self.assertTrue(handler.has_permission(infra, "notification_update"))
        self.assertTrue(handler.has_permission(infra, "workspace_bundle_admin"))
        self.assertTrue(handler.has_permission(infra, "audit_view"))
        self.assertTrue(handler.has_permission(infra, "policy_admin"))
        self.assertTrue(handler.has_permission(infra, "repository_context_import"))
        self.assertTrue(handler.has_permission(infra, "synthetic_load_run"))
        self.assertFalse(handler.has_permission(viewer, "notification_update"))
        self.assertFalse(handler.has_permission(viewer, "workspace_bundle_admin"))
        self.assertFalse(handler.has_permission(viewer, "audit_view"))
        self.assertFalse(handler.has_permission(viewer, "policy_admin"))
        self.assertFalse(handler.has_permission(viewer, "repository_context_import"))
        self.assertFalse(handler.has_permission(viewer, "synthetic_load_run"))

    def test_websocket_tmux_route_requires_tmux_control(self):
        handler = self.handler(role_tokens={
            "viewer-token": {"id": "viewer-a", "roles": ["viewer"]},
            "billing-token": {"id": "billing-a", "roles": ["billing_admin"]},
            "operator-token": {"id": "operator-a", "roles": ["operator"]},
        })

        self.assertEqual(handler.permission_for("GET", "/ws/tmux"), ("tmux_control", "tmux.ws_attach"))
        self.assertEqual(handler.permission_for("WEBSOCKET", "/ws/tmux"), ("tmux_control", "tmux.ws_attach"))
        self.assertIsNone(handler.permission_for("POST", "/ws/tmux"))
        self.assertIsNone(handler.permission_for("GET", "/api/models"))
        viewer = handler.identity("/ws/tmux", {"authorization": "Bearer viewer-token"})
        billing = handler.identity("/ws/tmux", {"authorization": "Bearer billing-token"})
        operator = handler.identity("/ws/tmux", {"authorization": "Bearer operator-token"})
        owner = handler.identity("/ws/tmux?token=secret", {})
        self.assertFalse(handler.has_permission(viewer, "tmux_control"))
        self.assertFalse(handler.has_permission(billing, "tmux_control"))
        self.assertTrue(handler.has_permission(operator, "tmux_control"))
        self.assertTrue(handler.has_permission(owner, "tmux_control"))

    def test_jwt_session_identity_is_authorized(self):
        handler = self.handler(session_verifier=lambda token: {
            "id": "session-user",
            "roles": ["operator"],
            "permissions": ["view_console", "tmux_control"],
            "source": "jwt-session",
            "session_id": "session-a",
        } if token == "jwt-token" else None)

        identity = handler.identity("/", {"authorization": "Bearer jwt-token"})

        self.assertTrue(handler.authorized("/", {"authorization": "Bearer jwt-token"}))
        self.assertEqual(identity["id"], "session-user")
        self.assertEqual(identity["source"], "jwt-session")
        self.assertTrue(handler.has_permission(identity, "tmux_control"))

    def test_cost_bearing_and_terminal_read_routes_require_permissions(self):
        handler = self.handler()
        # Cost-bearing model calls must be gated on model_use, not merely "any token".
        self.assertEqual(handler.permission_for("POST", "/api/chat"), ("model_use", "chat.completion"))
        self.assertEqual(handler.permission_for("POST", "/api/chat/compare"), ("model_use", "chat.compare"))
        self.assertEqual(handler.permission_for("POST", "/api/generate"), ("model_use", "image.generate"))
        # Reading live terminal contents is a security surface, like writing.
        self.assertEqual(handler.permission_for("POST", "/api/tmux/capture"), ("tmux_control", "tmux.capture"))
        self.assertEqual(handler.permission_for("POST", "/api/terminal/read"), ("tmux_control", "terminal.read"))

    def test_state_mutating_get_route_is_permission_checked(self):
        handler = self.handler()
        self.assertEqual(
            handler.permission_for("GET", "/api/models/serverless-catalog"),
            ("model_admin", "model_catalog.refresh"),
        )
        # Agentboard exposes live tmux pane contents; gate like a terminal read.
        self.assertEqual(
            handler.permission_for("GET", "/api/agentboard"),
            ("tmux_control", "agentboard.view"),
        )
        # Read-only GETs remain ungated by fine-grained permission.
        self.assertIsNone(handler.permission_for("GET", "/api/cost-summary"))

    def test_viewer_cannot_spend_or_read_terminals(self):
        handler = self.handler(role_tokens={"viewer-token": {"id": "v", "roles": ["viewer"]}})
        viewer = handler.identity("/", {"authorization": "Bearer viewer-token"})
        self.assertFalse(handler.has_permission(viewer, "model_use"))
        self.assertFalse(handler.has_permission(viewer, "tmux_control"))


if __name__ == "__main__":
    unittest.main()
