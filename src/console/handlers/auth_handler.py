"""Authentication helpers for the console HTTP handler."""
import json
import secrets
from urllib.parse import parse_qs, urlparse

from src.console.domain.auth import ActorIdentity
from src.console.policy import PolicyService


ROLE_PERMISSIONS = {
    "owner": {"*"},
    "admin": {"*"},
    "viewer": {"view_console", "view_traces", "view_billing"},
    "operator": {"view_console", "view_traces", "model_use", "tmux_control", "eval_run", "review_queue", "notification_update", "replay_run", "repository_context_import", "synthetic_load_run"},
    "model_admin": {"view_console", "view_traces", "model_use", "model_admin", "tmux_control", "eval_run", "review_queue", "notification_update", "replay_run", "repository_context_import", "workspace_bundle_admin", "synthetic_load_run"},
    "billing_admin": {"view_console", "view_billing", "budget_admin"},
    "infra_admin": {"view_console", "view_traces", "model_use", "tmux_control", "dedicated_admin", "budget_admin", "config_drift_admin", "rollback_admin", "automation_admin", "review_queue", "notification_update", "replay_run", "repository_context_import", "workspace_bundle_admin", "audit_view", "policy_admin", "synthetic_load_run"},
}

SENSITIVE_POST_PERMISSIONS = {
    "/api/models": ("model_admin", "model_registry.update"),
    "/api/proxy/sync": ("model_admin", "proxy.sync"),
    "/api/model-access-audit": ("model_admin", "model_access.audit"),
    "/api/model-access-drift/acknowledge": ("model_admin", "model_access_drift.acknowledge"),
    "/api/model-deprecations/preview": ("model_admin", "model_deprecation.preview"),
    "/api/model-deprecations/apply": ("model_admin", "model_deprecation.apply"),
    "/api/model-deprecations/rollback": ("model_admin", "model_deprecation.rollback"),
    "/api/dedicated/preflight": ("dedicated_admin", "dedicated.preflight"),
    "/api/dedicated/capacity-plan": ("dedicated_admin", "dedicated.capacity_plan"),
    "/api/dedicated/build": ("dedicated_admin", "dedicated.build"),
    "/api/dedicated/teardown": ("dedicated_admin", "dedicated.teardown"),
    "/api/dedicated/resume": ("dedicated_admin", "dedicated.resume"),
    "/api/dedicated/policy": ("dedicated_admin", "dedicated.policy"),
    "/api/dedicated/keep-alive": ("dedicated_admin", "dedicated.keep_alive"),
    "/api/budget": ("budget_admin", "budget.update"),
    "/api/reporting": ("view_billing", "billing.report"),
    "/api/evals/run": ("eval_run", "eval.run"),
    "/api/evals/datasets": ("eval_run", "eval.dataset.save"),
    "/api/evals/datasets/build": ("eval_run", "eval.dataset.build"),
    "/api/comparison-reports": ("model_use", "comparison_report.save"),
    "/api/rag/config": ("model_use", "rag.config"),
    "/api/rag/index": ("model_use", "rag.index"),
    "/api/rag/search": ("model_use", "rag.search"),
    "/api/reviews": ("review_queue", "review.create"),
    "/api/reviews/update": ("review_queue", "review.update"),
    "/api/reviews/promote": ("review_queue", "review.promote"),
    "/api/replay/snapshot": ("replay_run", "replay.snapshot"),
    "/api/replay": ("replay_run", "replay.run"),
    "/api/repository-context/preview": ("repository_context_import", "repository_context.preview"),
    "/api/repository-context/import": ("repository_context_import", "repository_context.import"),
    "/api/ci-triage/preview": ("repository_context_import", "ci_triage.preview"),
    "/api/ci-triage/launch": ("repository_context_import", "ci_triage.launch"),
    "/api/session-snapshots": ("tmux_control", "session.snapshot"),
    "/api/patch-review": ("tmux_control", "patch_review.generate"),
    "/api/onboarding/complete": ("config_drift_admin", "onboarding.complete"),
    "/api/explain-decision": ("view_console", "decision.explain"),
    "/api/commands/dispatch": ("view_console", "command.dispatch"),
    "/api/config-drift/baseline": ("config_drift_admin", "config_drift.baseline"),
    "/api/config-drift/acknowledge": ("config_drift_admin", "config_drift.acknowledge"),
    "/api/rollback/preview": ("rollback_admin", "rollback.preview"),
    "/api/rollback/apply": ("rollback_admin", "rollback.apply"),
    "/api/release-candidate/report": ("rollback_admin", "release_candidate.report"),
    "/api/automation/rules": ("automation_admin", "automation.rules"),
    "/api/automation/test": ("automation_admin", "automation.test"),
    "/api/automation/run": ("automation_admin", "automation.run"),
    "/api/policies/preview": ("policy_admin", "policy.preview"),
    "/api/policies/apply": ("policy_admin", "policy.apply"),
    "/api/policies/rollback": ("policy_admin", "policy.rollback"),
    "/api/synthetic-load/preview": ("synthetic_load_run", "synthetic_load.preview"),
    "/api/synthetic-load/run": ("synthetic_load_run", "synthetic_load.run"),
    "/api/cost-anomalies/update": ("budget_admin", "cost_anomaly.update"),
    "/api/notifications/update": ("notification_update", "notification.update"),
    "/api/reporting-export": ("audit_view", "reporting.export"),
    "/api/workspace-bundles/export": ("workspace_bundle_admin", "workspace_bundle.export"),
    "/api/workspace-bundles/preview": ("workspace_bundle_admin", "workspace_bundle.preview"),
    "/api/workspace-bundles/import": ("workspace_bundle_admin", "workspace_bundle.import"),
    "/api/test-models": ("model_admin", "model.smoke_test"),
    "/api/tmux/start": ("tmux_control", "tmux.start"),
    "/api/tmux/permissions": ("tmux_control", "tmux.permissions"),
    "/api/tmux/capture": ("tmux_control", "tmux.capture"),
    "/api/tmux/send": ("tmux_control", "tmux.send"),
    "/api/tmux/key": ("tmux_control", "tmux.key"),
    "/api/tmux/stop": ("tmux_control", "tmux.stop"),
    "/api/tmux/rename": ("tmux_control", "tmux.rename"),
    "/api/terminal/start": ("tmux_control", "terminal.start"),
    "/api/terminal/read": ("tmux_control", "terminal.read"),
    "/api/terminal/write": ("tmux_control", "terminal.write"),
    "/api/terminal/stop": ("tmux_control", "terminal.stop"),
}

SENSITIVE_GET_PERMISSIONS = {
    "/api/auth/sessions": ("auth_session_admin", "auth.sessions.list"),
    "/api/audit": ("audit_view", "audit.view"),
    "/api/audit/export": ("audit_view", "audit.export"),
    "/api/policies": ("policy_admin", "policy.view"),
    "/api/agentboard": ("tmux_control", "agentboard.view"),
    "/api/tmux/sessions": ("tmux_control", "tmux.sessions"),
    "/api/reviews": ("review_queue", "review.list"),
    "/api/replays": ("replay_run", "replay.list"),
    "/api/repository-context": ("repository_context_import", "repository_context.view"),
    "/api/ci-triage": ("repository_context_import", "ci_triage.view"),
    "/api/onboarding": ("view_console", "onboarding.view"),
    "/api/commands": ("view_console", "command.list"),
    "/api/comparison-reports": ("view_traces", "comparison_report.list"),
    "/api/comparison-reports/load": ("view_traces", "comparison_report.load"),
    "/api/comparison-reports/export": ("view_traces", "comparison_report.export"),
    "/api/model-deprecations": ("model_admin", "model_deprecation.view"),
    "/api/rag": ("view_console", "rag.view"),
    "/api/reporting-integrations": ("view_console", "reporting.integrations"),
    "/api/reporting-export": ("audit_view", "reporting.export.status"),
    "/api/config-drift": ("view_console", "config_drift.view"),
    "/api/rollback": ("rollback_admin", "rollback.targets"),
    "/api/release-candidate": ("view_console", "release_candidate.view"),
    "/api/automation": ("automation_admin", "automation.view"),
    "/api/synthetic-load": ("synthetic_load_run", "synthetic_load.view"),
    "/api/cost-anomalies": ("view_billing", "cost_anomaly.view"),
    "/api/notifications": ("view_console", "notification.view"),
    "/api/offline-mode": ("view_console", "offline_mode.view"),
    "/api/workspace-bundles": ("workspace_bundle_admin", "workspace_bundle.list"),
}


class AuthHandler:
    """Parse console auth tokens and evaluate request authorization."""

    def __init__(self, auth_enabled, auth_token, role_tokens=None, session_verifier=None, policy_service=None):
        self.auth_enabled = auth_enabled
        self.auth_token = auth_token
        self.role_tokens = role_tokens or (lambda: {})
        self.session_verifier = session_verifier or (lambda token: None)
        self.policy_service = policy_service or PolicyService(
            get_permissions=SENSITIVE_GET_PERMISSIONS,
            post_permissions=SENSITIVE_POST_PERMISSIONS,
        )

    def request_token(self, path, headers):
        parsed = urlparse(path)
        query_token = (parse_qs(parsed.query).get("token") or [""])[0]
        if query_token:
            return query_token
        header_token = headers.get("x-matts-console-token", "").strip()
        if header_token:
            return header_token
        auth = headers.get("authorization", "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def role_token_map(self):
        raw = self.role_tokens() or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = {}
        return raw if isinstance(raw, dict) else {}

    def identity(self, path, headers):
        if not self.auth_enabled():
            return ActorIdentity("auth-disabled", ("owner",), ("*",), "auth-disabled").to_dict()
        token = self.request_token(path, headers)
        owner_token = self.auth_token()
        if token and owner_token and secrets.compare_digest(token, owner_token):
            return ActorIdentity("console-owner", ("owner",), ("*",), "console-token").to_dict()
        session_identity = self.session_verifier(token) if token else None
        if isinstance(session_identity, dict):
            return ActorIdentity.from_dict(session_identity).to_dict()
        token_map = self.role_token_map()
        profile = token_map.get(token) if token else None
        if not isinstance(profile, dict):
            return ActorIdentity("anonymous").to_dict()
        roles = [str(role) for role in (profile.get("roles") or []) if role]
        permissions = set()
        for role in roles:
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        permissions.update(str(item) for item in (profile.get("permissions") or []) if item)
        return ActorIdentity(str(profile.get("id") or profile.get("name") or "role-token-user"), tuple(roles), tuple(sorted(permissions)), "role-token").to_dict()

    def authorized(self, path, headers):
        return not self.auth_enabled() or bool(self.identity(path, headers).get("permissions"))

    def permission_for(self, method, path):
        return self.policy_service.permission_for(method, path)

    def has_permission(self, identity, permission):
        return self.policy_service.authorize(identity, permission).allowed

    def policy_decision(self, method, path, identity):
        return self.policy_service.request_decision(method, path, identity)
