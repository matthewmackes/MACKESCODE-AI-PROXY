"""HTTP-level authorization-enforcement tests for the console server (PR-3.2).

The existing HTTP smoke tests in ``tests/test_console_smoke.py`` all run with
console auth DISABLED, so the permission gate that ``image-studio.py``'s
``do_GET``/``do_POST`` apply (``auth_handler().permission_for`` +
``has_permission`` -> 403 with an audit entry) is never exercised against the
live server. This suite closes that gap: it starts the *real*
``StudioHandler`` on an ephemeral port WITH auth ENABLED and a role-token map
configured, then issues real ``urllib`` requests and asserts the enforcement
outcomes (401 for no/bad token, 403 for an authenticated-but-underprivileged
viewer, and non-401/403 for the owner "*" token).

Hermeticity:
* A scratch ``HOME`` is set before the studio module is imported, so audit
  writes and cache lookups never touch operator state.
* Auth is enabled and the owner token / role-token map are injected by
  monkeypatching the studio module's ``auth_enabled`` / ``auth_token`` /
  ``auth_role_tokens`` seams (mirrors how ``auth_handler()`` wires them).
* The rate limiter is stubbed to always-allow (it is enabled by default) so a
  burst of test requests cannot flake into a 429.
* ``api_handler`` is stubbed with a benign in-memory handler. The permission
  gate runs *before* dispatch, so this does not weaken the 403/401 assertions
  (the stub records calls, letting us prove a denied request never reached
  dispatch); it only keeps the owner "allowed" path off any real
  proxy/tmux/DigitalOcean backend.
"""
import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

# Redirect HOME to a throwaway directory BEFORE importing the studio module so
# nothing (audit log, token/cache files) can land in the operator's real home.
_SCRATCH_HOME = tempfile.mkdtemp(prefix="matts-auth-http-test-home-")
os.environ["HOME"] = _SCRATCH_HOME


def load_studio_module():
    spec = importlib.util.spec_from_file_location("image_studio", ROOT / "image-studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


studio = load_studio_module()

from src.console.handlers.auth_handler import (  # noqa: E402
    ROLE_PERMISSIONS,
    SENSITIVE_GET_PERMISSIONS,
    SENSITIVE_POST_PERMISSIONS,
    AuthHandler,
)


# --- Tokens and the role-token map injected for the duration of each test. ----
OWNER_TOKEN = "owner-token-secret-000"
VIEWER_TOKEN = "viewer-token-secret-111"
OPERATOR_TOKEN = "operator-token-secret-222"
MODEL_ADMIN_TOKEN = "model-admin-token-secret-333"
BILLING_ADMIN_TOKEN = "billing-admin-token-secret-444"

ROLE_TOKEN_MAP = {
    VIEWER_TOKEN: {"id": "viewer-user", "roles": ["viewer"]},
    OPERATOR_TOKEN: {"id": "operator-user", "roles": ["operator"]},
    MODEL_ADMIN_TOKEN: {"id": "model-admin-user", "roles": ["model_admin"]},
    BILLING_ADMIN_TOKEN: {"id": "billing-admin-user", "roles": ["billing_admin"]},
}

# Gated routes a *viewer* (view_console/view_traces/view_billing only) must be
# denied on, and that an owner ("*") must be allowed past.
GATED_POST_ROUTES = [
    "/api/chat",             # ("model_use", "chat.completion")
    "/api/generate",         # ("model_use", "image.generate")
    "/api/tmux/capture",     # ("tmux_control", "tmux.capture")
    "/api/terminal/read",    # ("tmux_control", "terminal.read")
]
GATED_GET_ROUTES = [
    "/api/agentboard",                 # ("tmux_control", "agentboard.view")
    "/api/models/serverless-catalog",  # ("model_admin", "model_catalog.refresh")
]


class AllowAllLimiter:
    """Rate limiter stub: never throttles, so request bursts can't flake."""

    def check(self, key, method, path):
        return {"allowed": True, "headers": {}}


class StubApiHandler:
    """In-memory stand-in for the real dispatch layer.

    The permission gate in ``do_GET``/``do_POST`` runs *before* the handler is
    invoked, so a denied request never lands here. Recording calls lets tests
    assert that (a denied viewer must NOT appear in these lists) while keeping
    the owner "allowed" path off any real backend.
    """

    def __init__(self):
        self.get_calls = []
        self.post_calls = []

    def get(self, path, query):
        self.get_calls.append(path)
        return True, 200, {"ok": True, "path": path, "method": "GET"}

    def post(self, path, data):
        self.post_calls.append(path)
        return True, 200, {"ok": True, "path": path, "method": "POST"}


class AuthEnforcementServerCase(unittest.TestCase):
    """Base case: real StudioHandler on an ephemeral port with auth ENABLED."""

    def setUp(self):
        self.stub = StubApiHandler()
        self._patchers = [
            patch.object(studio, "auth_enabled", return_value=True),
            patch.object(studio, "auth_token", return_value=OWNER_TOKEN),
            patch.object(studio, "auth_role_tokens", return_value=dict(ROLE_TOKEN_MAP)),
            patch.object(studio, "rate_limiter", return_value=AllowAllLimiter()),
            patch.object(studio, "api_handler", return_value=self.stub),
        ]
        for patcher in self._patchers:
            patcher.start()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), studio.StudioHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        for patcher in reversed(self._patchers):
            patcher.stop()

    def request(self, method, path, token=None, body=b"{}"):
        """Issue a real HTTP request; return (status_code, parsed_body)."""
        headers = {}
        data = None
        if method == "POST":
            data = body if body is not None else b"{}"
            headers["content-type"] = "application/json"
        if token is not None:
            headers["x-matts-console-token"] = token
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return resp.status, self._parse(raw)
        except urllib.error.HTTPError as exc:
            return exc.code, self._parse(exc.read())

    @staticmethod
    def _parse(raw):
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}


class ViewerDeniedTests(AuthEnforcementServerCase):
    """A viewer token holds only view_* permissions -> 403 on gated routes."""

    def test_viewer_denied_403_on_gated_post_routes(self):
        for path in GATED_POST_ROUTES:
            with self.subTest(route=path):
                status, body = self.request("POST", path, token=VIEWER_TOKEN)
                self.assertEqual(status, 403, "expected 403 for viewer on POST %s, got %s" % (path, status))
                self.assertEqual(body.get("code"), "permission_denied")
                # The gate must short-circuit before dispatch reaches the handler.
                self.assertNotIn(path, self.stub.post_calls)

    def test_viewer_denied_403_on_gated_get_routes(self):
        for path in GATED_GET_ROUTES:
            with self.subTest(route=path):
                status, body = self.request("GET", path, token=VIEWER_TOKEN)
                self.assertEqual(status, 403, "expected 403 for viewer on GET %s, got %s" % (path, status))
                self.assertEqual(body.get("code"), "permission_denied")
                self.assertNotIn(path, self.stub.get_calls)


class OwnerAllowedTests(AuthEnforcementServerCase):
    """The owner token has permissions ["*"] -> never blocked by the gate."""

    def test_owner_not_denied_on_gated_post_routes(self):
        for path in GATED_POST_ROUTES:
            with self.subTest(route=path):
                status, _ = self.request("POST", path, token=OWNER_TOKEN)
                self.assertNotIn(status, (401, 403), "owner unexpectedly blocked on POST %s (%s)" % (path, status))
                # Passing the gate means the request was actually dispatched.
                self.assertIn(path, self.stub.post_calls)

    def test_owner_not_denied_on_gated_get_routes(self):
        for path in GATED_GET_ROUTES:
            with self.subTest(route=path):
                status, _ = self.request("GET", path, token=OWNER_TOKEN)
                self.assertNotIn(status, (401, 403), "owner unexpectedly blocked on GET %s (%s)" % (path, status))
                self.assertIn(path, self.stub.get_calls)


class UnauthenticatedTests(AuthEnforcementServerCase):
    """No token / bad token -> 401 before any permission or dispatch step."""

    def test_missing_token_returns_401(self):
        for method, path in [("POST", "/api/chat"), ("GET", "/api/agentboard")]:
            with self.subTest(method=method, route=path):
                status, body = self.request(method, path, token=None)
                self.assertEqual(status, 401, "expected 401 for anonymous %s %s, got %s" % (method, path, status))
                self.assertEqual(body.get("code"), "console_auth_required")

    def test_bad_token_returns_401(self):
        for method, path in [("POST", "/api/generate"), ("GET", "/api/models/serverless-catalog")]:
            with self.subTest(method=method, route=path):
                status, body = self.request(method, path, token="not-a-real-token")
                self.assertEqual(status, 401, "expected 401 for bad token %s %s, got %s" % (method, path, status))
                self.assertEqual(body.get("code"), "console_auth_required")

    def test_denied_requests_never_reached_dispatch(self):
        # Sanity: none of the above 401 requests should have touched the handler.
        self.request("POST", "/api/chat", token=None)
        self.request("GET", "/api/agentboard", token="bad")
        self.assertEqual(self.stub.post_calls, [])
        self.assertEqual(self.stub.get_calls, [])


class PermissionMapParityTests(unittest.TestCase):
    """Static guards on the permission map itself (no server required).

    Catch a typo'd permission name in SENSITIVE_*_PERMISSIONS that no concrete
    role could ever satisfy (which would silently lock every non-owner out) and
    confirm permission_for() reports the same tuple the maps declare.
    """

    def setUp(self):
        # A handler with auth enabled so permission_for takes the real branch.
        self.handler = AuthHandler(auth_enabled=lambda: True, auth_token=lambda: OWNER_TOKEN)
        # Roles that carry explicit permission sets (exclude the "*" wildcards).
        self.explicit_roles = {
            role: perms for role, perms in ROLE_PERMISSIONS.items() if "*" not in perms
        }

    def test_every_sensitive_permission_is_grantable_by_some_explicit_role(self):
        combined = {}
        combined.update(SENSITIVE_POST_PERMISSIONS)
        combined.update(SENSITIVE_GET_PERMISSIONS)
        self.assertTrue(combined)
        for path, tuple_value in combined.items():
            permission, _action = tuple_value
            granting_roles = [role for role, perms in self.explicit_roles.items() if permission in perms]
            self.assertTrue(
                granting_roles,
                "sensitive route %s requires permission %r that NO non-owner role grants "
                "(likely a typo); explicit roles: %s" % (path, permission, sorted(self.explicit_roles)),
            )

    def test_permission_for_matches_the_declared_post_tuples(self):
        for path, expected in SENSITIVE_POST_PERMISSIONS.items():
            with self.subTest(route=path):
                self.assertEqual(self.handler.permission_for("POST", path), expected)
        # A non-sensitive POST route carries no gate.
        self.assertIsNone(self.handler.permission_for("POST", "/api/history"))

    def test_permission_for_matches_the_declared_get_tuples(self):
        for path, expected in SENSITIVE_GET_PERMISSIONS.items():
            with self.subTest(route=path):
                self.assertEqual(self.handler.permission_for("GET", path), expected)
        # GET must not inherit POST gates (method-specific lookup).
        self.assertIsNone(self.handler.permission_for("GET", "/api/chat"))

    def test_viewer_role_lacks_the_permissions_the_gated_routes_require(self):
        # Documents WHY the HTTP viewer cases 403: none of the gated permissions
        # are in the viewer role's set.
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        for path in GATED_POST_ROUTES:
            permission = SENSITIVE_POST_PERMISSIONS[path][0]
            self.assertNotIn(permission, viewer_perms)
        for path in GATED_GET_ROUTES:
            permission = SENSITIVE_GET_PERMISSIONS[path][0]
            self.assertNotIn(permission, viewer_perms)


if __name__ == "__main__":
    unittest.main()
