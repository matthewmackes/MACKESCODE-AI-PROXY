"""Authentication helpers for the console HTTP handler."""
import json
import secrets
from urllib.parse import parse_qs, urlparse


ROLE_PERMISSIONS = {
    "owner": {"*"},
    "admin": {"*"},
    "viewer": {"view_console", "view_traces", "view_billing"},
    "operator": {"view_console", "view_traces", "model_use", "tmux_control", "eval_run"},
    "model_admin": {"view_console", "view_traces", "model_use", "model_admin", "tmux_control", "eval_run"},
    "billing_admin": {"view_console", "view_billing", "budget_admin"},
    "infra_admin": {"view_console", "view_traces", "model_use", "tmux_control", "dedicated_admin", "budget_admin"},
}

SENSITIVE_POST_PERMISSIONS = {
    "/api/models": ("model_admin", "model_registry.update"),
    "/api/proxy/sync": ("model_admin", "proxy.sync"),
    "/api/model-access-audit": ("model_admin", "model_access.audit"),
    "/api/dedicated/preflight": ("dedicated_admin", "dedicated.preflight"),
    "/api/dedicated/build": ("dedicated_admin", "dedicated.build"),
    "/api/dedicated/teardown": ("dedicated_admin", "dedicated.teardown"),
    "/api/dedicated/resume": ("dedicated_admin", "dedicated.resume"),
    "/api/dedicated/policy": ("dedicated_admin", "dedicated.policy"),
    "/api/dedicated/keep-alive": ("dedicated_admin", "dedicated.keep_alive"),
    "/api/budget": ("budget_admin", "budget.update"),
    "/api/reporting": ("view_billing", "billing.report"),
    "/api/evals/run": ("eval_run", "eval.run"),
    "/api/test-models": ("model_admin", "model.smoke_test"),
    "/api/tmux/start": ("tmux_control", "tmux.start"),
    "/api/tmux/send": ("tmux_control", "tmux.send"),
    "/api/tmux/key": ("tmux_control", "tmux.key"),
    "/api/tmux/stop": ("tmux_control", "tmux.stop"),
    "/api/tmux/rename": ("tmux_control", "tmux.rename"),
    "/api/terminal/start": ("tmux_control", "terminal.start"),
    "/api/terminal/write": ("tmux_control", "terminal.write"),
    "/api/terminal/stop": ("tmux_control", "terminal.stop"),
}


class AuthHandler:
    """Parse console auth tokens and evaluate request authorization."""

    def __init__(self, auth_enabled, auth_token, role_tokens=None, session_verifier=None):
        self.auth_enabled = auth_enabled
        self.auth_token = auth_token
        self.role_tokens = role_tokens or (lambda: {})
        self.session_verifier = session_verifier or (lambda token: None)

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
            return {"id": "auth-disabled", "roles": ["owner"], "permissions": ["*"], "source": "auth-disabled"}
        token = self.request_token(path, headers)
        owner_token = self.auth_token()
        if token and owner_token and secrets.compare_digest(token, owner_token):
            return {"id": "console-owner", "roles": ["owner"], "permissions": ["*"], "source": "console-token"}
        session_identity = self.session_verifier(token) if token else None
        if isinstance(session_identity, dict):
            return session_identity
        token_map = self.role_token_map()
        profile = token_map.get(token) if token else None
        if not isinstance(profile, dict):
            return {"id": "anonymous", "roles": [], "permissions": [], "source": "none"}
        roles = [str(role) for role in (profile.get("roles") or []) if role]
        permissions = set()
        for role in roles:
            permissions.update(ROLE_PERMISSIONS.get(role, set()))
        permissions.update(str(item) for item in (profile.get("permissions") or []) if item)
        return {
            "id": str(profile.get("id") or profile.get("name") or "role-token-user"),
            "roles": roles,
            "permissions": sorted(permissions),
            "source": "role-token",
        }

    def authorized(self, path, headers):
        return not self.auth_enabled() or bool(self.identity(path, headers).get("permissions"))

    def permission_for(self, method, path):
        if str(method or "").upper() == "POST":
            return SENSITIVE_POST_PERMISSIONS.get(path)
        return None

    def has_permission(self, identity, permission):
        perms = set((identity or {}).get("permissions") or [])
        return "*" in perms or permission in perms
