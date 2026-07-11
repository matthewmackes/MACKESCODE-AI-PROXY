import importlib.util
import errno
import io
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_studio_module():
    spec = importlib.util.spec_from_file_location("image_studio", ROOT / "image-studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


studio = load_studio_module()


class QuietStudioHandler(studio.StudioHandler):
    def log_message(self, fmt, *args):
        return None


def quiet_server():
    return ThreadingHTTPServer(("127.0.0.1", 0), QuietStudioHandler)


class SequencedWriter:
    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return len(data)


def response_handler_with_writer(writer):
    handler = object.__new__(studio.StudioHandler)
    handler.wfile = writer
    handler.path = "/api/test"
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.log_request = lambda *args, **kwargs: None
    return handler


class ServiceAdapterSmokeTests(unittest.TestCase):
    def test_default_model_registry_loads_from_configured_file(self):
        self.assertTrue(studio.DEFAULT_MODEL_REGISTRY)
        self.assertTrue(any(model["id"] == "deepseek-3.2" for model in studio.DEFAULT_MODEL_REGISTRY))


class HealthSmokeTests(unittest.TestCase):
    def test_console_status_ok_when_proxy_and_launcher_are_ready(self):
        with patch.object(studio, "port_open", return_value=True), \
             patch.object(studio, "launcher_health", return_value={"ok": True, "healed": False, "path": "/tmp/claude-DO.sh"}), \
             patch.object(studio, "auth_enabled", return_value=True), \
             patch.object(studio, "SERVER_STARTED_AT", time.time() - 5):
            status = studio.console_status()

        self.assertEqual(status["service"], "mde-llm-proxy-console")
        self.assertEqual(status["version"], studio.APP_VERSION)
        self.assertEqual(status["status"], "ok")
        self.assertTrue(status["proxy"]["listening"])
        self.assertTrue(status["launcher"]["ok"])
        self.assertTrue(status["auth_enabled"])

    def test_console_status_degraded_when_proxy_is_down(self):
        with patch.object(studio, "port_open", return_value=False), \
             patch.object(studio, "launcher_health", return_value={"ok": True}), \
             patch.object(studio, "auth_enabled", return_value=False):
            status = studio.console_status()

        self.assertEqual(status["status"], "degraded")
        self.assertFalse(status["proxy"]["listening"])

    def test_console_metrics_emit_prometheus_gauges_and_counters(self):
        fake_status = {
            "status": "ok",
            "uptime_seconds": 42,
            "proxy": {"listening": True},
        }
        with patch.object(studio, "console_status", return_value=fake_status), \
             patch.object(studio, "tmux_sessions", return_value=[{"name": "one"}]), \
             patch.dict(studio.REQUEST_COUNTS, {"GET": 3, "POST": 1}, clear=True):
            metrics = studio.console_metrics_text()

        self.assertIn("matts_console_up 1", metrics)
        self.assertIn("matts_console_ready 1", metrics)
        self.assertIn("matts_console_uptime_seconds 42", metrics)
        self.assertIn("matts_console_proxy_listening 1", metrics)
        self.assertIn("matts_console_tmux_sessions 1", metrics)
        self.assertIn('matts_console_requests_total{method="GET"} 3', metrics)
        self.assertIn('matts_console_requests_total{method="POST"} 1', metrics)

    def test_handler_prefers_server_app_for_health_dependencies(self):
        from src.console.app import ConsoleApp

        app = ConsoleApp(
            "fake-console",
            "9",
            dependencies={
                "console_status": lambda: {"status": "degraded", "service": "fake-console", "uptime_seconds": 1, "proxy": {"listening": False}},
            },
        )
        server = quiet_server()
        server.app = app
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        error_logger = patch.object(studio, "log_error_response", return_value={})
        thread.start()
        try:
            with error_logger, self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/ready", timeout=3)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertEqual(ctx.exception.code, 503)
            self.assertEqual(body["service"], "fake-console")
            self.assertEqual(app.request_counts["GET"], 1)
        finally:
            server.shutdown()
            server.server_close()


class RequestParsingTests(unittest.TestCase):
    def test_read_json_reports_malformed_body(self):
        handler = object.__new__(studio.StudioHandler)
        handler.headers = {"content-length": "1"}
        handler.rfile = io.BytesIO(b"{")

        with self.assertRaisesRegex(ValueError, "invalid JSON request body"):
            handler.read_json()


class ResponseDisconnectTests(unittest.TestCase):
    def test_send_json_swallows_broken_pipe_during_body_write(self):
        writer = SequencedWriter([None, BrokenPipeError()])
        handler = response_handler_with_writer(writer)

        handler.send_json(200, {"ok": True})

        self.assertEqual(len(writer.writes), 2)
        self.assertIn(b"content-type: application/json", writer.writes[0].lower())
        self.assertEqual(writer.writes[1], b'{"ok": true}')

    def test_send_text_swallows_connection_reset_during_header_write(self):
        writer = SequencedWriter([ConnectionResetError()])
        handler = response_handler_with_writer(writer)

        handler.send_text(200, "hello")

        self.assertEqual(len(writer.writes), 1)
        self.assertIn(b"content-type: text/plain", writer.writes[0].lower())

    def test_unexpected_write_error_still_propagates(self):
        writer = SequencedWriter([OSError(errno.EINVAL, "bad write")])
        handler = response_handler_with_writer(writer)

        with self.assertRaises(OSError) as ctx:
            handler.send_html("<p>hello</p>")

        self.assertEqual(ctx.exception.errno, errno.EINVAL)


class QuietHttpSmokeHandlerTests(unittest.TestCase):
    def test_quiet_handler_suppresses_access_logs_without_changing_production_handler(self):
        quiet = object.__new__(QuietStudioHandler)
        production = object.__new__(studio.StudioHandler)
        stdout = StringIO()

        with redirect_stdout(stdout):
            quiet.log_message("GET %s", "/quiet")
            production.log_message("GET %s", "/production")

        output = stdout.getvalue()
        self.assertNotIn("/quiet", output)
        self.assertIn("/production", output)


class ApiVersionHttpSmokeTests(unittest.TestCase):
    def with_server(self, callback):
        server = quiet_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        with patch.object(studio, "auth_enabled", return_value=False), \
             patch.object(studio, "models_payload", return_value={"models": [{"id": "model-a"}]}), \
             patch.object(studio, "log_error_response", return_value={}):
            thread.start()
            try:
                callback("http://127.0.0.1:%d" % server.server_address[1])
            finally:
                server.shutdown()
                server.server_close()

    def read_json(self, url, headers=None):
        request = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response, json.loads(response.read().decode("utf-8"))

    def test_v1_api_path_and_legacy_deprecation_headers(self):
        def run(base_url):
            versioned, versioned_body = self.read_json(base_url + "/api/v1/models")
            legacy, legacy_body = self.read_json(base_url + "/api/models")

            self.assertEqual(versioned.status, 200)
            self.assertEqual(versioned.headers["x-matts-api-version"], "v1")
            self.assertNotIn("deprecation", versioned.headers)
            self.assertEqual(versioned_body["models"][0]["id"], "model-a")
            self.assertEqual(legacy.status, 200)
            self.assertEqual(legacy.headers["x-matts-api-version"], "v1")
            self.assertEqual(legacy.headers["deprecation"], "true")
            self.assertEqual(legacy_body["models"][0]["id"], "model-a")

        self.with_server(run)

    def test_unsupported_api_version_returns_structured_error(self):
        def run(base_url):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.read_json(base_url + "/api/v2/models")
            body = json.loads(ctx.exception.read().decode("utf-8"))

            self.assertEqual(ctx.exception.code, 400)
            self.assertEqual(ctx.exception.headers["x-matts-api-version"], "v2")
            self.assertEqual(body["code"], "unsupported_api_version")
            self.assertEqual(body["details"]["requested_version"], "v2")

        self.with_server(run)


class TmuxWebSocketPermissionHttpTests(unittest.TestCase):
    def test_ws_tmux_enforces_tmux_control_scope_and_audits_denials(self):
        audits = []
        role_tokens = {
            "viewer-token": {"id": "viewer-a", "roles": ["viewer"]},
            "operator-token": {"id": "operator-a", "roles": ["operator"]},
        }
        server = ThreadingHTTPServer(("127.0.0.1", 0), studio.StudioHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        with patch.object(studio, "auth_enabled", return_value=True), \
             patch.object(studio, "auth_token", return_value="owner-secret"), \
             patch.object(studio, "auth_role_tokens", return_value=role_tokens), \
             patch.object(studio, "tmux_cmd", side_effect=lambda args, check=True: (1, "", "no session")), \
             patch.object(studio, "append_audit", side_effect=lambda action, **kwargs: audits.append({"action": action, **kwargs})):
            thread.start()
            base = "http://127.0.0.1:%d" % server.server_address[1]
            statuses = {}
            try:
                for label, token in (("viewer", "viewer-token"), ("operator", "operator-token"), ("owner", "owner-secret"), ("anonymous", "")):
                    url = base + "/ws/tmux?name=smoke" + ("&token=%s" % token if token else "")
                    try:
                        with urllib.request.urlopen(url, timeout=5) as response:
                            statuses[label] = response.status
                    except urllib.error.HTTPError as exc:
                        statuses[label] = exc.code
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(statuses["viewer"], 403)
        self.assertEqual(statuses["operator"], 404)
        self.assertEqual(statuses["owner"], 404)
        self.assertEqual(statuses["anonymous"], 401)
        denied = [record for record in audits if record["action"] == "tmux.ws_attach" and record.get("outcome") == "denied"]
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[0]["actor"]["id"], "viewer-a")
        self.assertEqual(denied[0]["permission"], "tmux_control")
        self.assertEqual(denied[0]["status"], 403)
        self.assertNotIn("viewer-token", json.dumps(denied[0].get("request", {})))


class AlwaysDeniedLimiter:
    def check(self, key, method, path):
        return {
            "allowed": False,
            "headers": {
                "x-ratelimit-limit": "1",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "200",
                "retry-after": "60",
            },
            "limit": 1,
            "remaining": 0,
            "reset": 200,
            "retry_after": 60,
        }


class ApiRateLimitHttpSmokeTests(unittest.TestCase):
    def test_api_rate_limit_returns_429_with_quota_headers(self):
        server = quiet_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        with patch.object(studio, "auth_enabled", return_value=False), \
             patch.object(studio, "rate_limiter", return_value=AlwaysDeniedLimiter()), \
             patch.object(studio, "log_error_response", return_value={}):
            thread.start()
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen("http://127.0.0.1:%d/api/v1/models" % server.server_address[1], timeout=5)
                body = json.loads(ctx.exception.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(ctx.exception.code, 429)
        self.assertEqual(ctx.exception.headers["x-ratelimit-limit"], "1")
        self.assertEqual(ctx.exception.headers["retry-after"], "60")
        self.assertEqual(body["code"], "rate_limit_exceeded")


class ApiRouteSuggestionHttpSmokeTests(unittest.TestCase):
    def test_unknown_legacy_api_route_returns_method_aware_suggestions(self):
        server = quiet_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        with patch.object(studio, "auth_enabled", return_value=False), \
             patch.object(studio, "log_error_response", return_value={}):
            thread.start()
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen("http://127.0.0.1:%d/api/proxy/stats?token=secret" % server.server_address[1], timeout=5)
                body = json.loads(ctx.exception.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()

        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(body["code"], "api_endpoint_not_found")
        self.assertEqual(body["details"]["method"], "GET")
        self.assertEqual(body["details"]["path"], "/api/proxy/stats")
        self.assertEqual(body["details"]["suggested_endpoints"][0], "/api/proxy/status")
        self.assertNotIn("secret", json.dumps(body))


class RolePermissionHttpSmokeTests(unittest.TestCase):
    def with_auth_server(self, callback):
        server = quiet_server()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        role_tokens = {
            "viewer-token": {"id": "viewer-a", "roles": ["viewer"]},
            "operator-token": {"id": "operator-a", "roles": ["operator"]},
        }
        with patch.object(studio, "auth_enabled", return_value=True), \
             patch.object(studio, "auth_token", return_value="owner-token"), \
             patch.object(studio, "auth_role_tokens", return_value=role_tokens), \
             patch.object(studio, "append_audit", return_value={}), \
             patch.object(studio, "active_auth_sessions", return_value={"sessions": [{"session_id": "session-a"}]}), \
             patch.object(studio, "tmux_session_items", return_value=[{"name": "live", "live": True}]), \
             patch.object(studio, "tmux_capture", return_value=(200, {"name": "live", "screen": "secret terminal text"})), \
             patch.object(studio, "log_error_response", return_value={}):
            thread.start()
            try:
                callback("http://127.0.0.1:%d" % server.server_address[1])
            finally:
                server.shutdown()
                server.server_close()

    def read_json(self, url, token, data=None):
        headers = {"authorization": "Bearer " + token}
        body = None
        method = "GET"
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["content-type"] = "application/json"
            method = "POST"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response, json.loads(response.read().decode("utf-8"))

    def assert_forbidden(self, url, token, data=None):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.read_json(url, token, data=data)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(ctx.exception.code, 403)
        self.assertEqual(body["code"], "permission_denied")
        return body

    def test_viewer_cannot_list_auth_sessions_or_read_terminal_output(self):
        def run(base_url):
            auth_body = self.assert_forbidden(base_url + "/api/v1/auth/sessions", "viewer-token")
            tmux_body = self.assert_forbidden(base_url + "/api/v1/tmux/sessions", "viewer-token")
            capture_body = self.assert_forbidden(base_url + "/api/v1/tmux/capture", "viewer-token", data={"name": "live"})

            self.assertEqual(auth_body["details"]["permission"], "auth_session_admin")
            self.assertEqual(tmux_body["details"]["permission"], "tmux_control")
            self.assertEqual(capture_body["details"]["permission"], "tmux_control")

        self.with_auth_server(run)

    def test_owner_and_operator_keep_expected_sensitive_access(self):
        def run(base_url):
            owner_response, owner_body = self.read_json(base_url + "/api/v1/auth/sessions", "owner-token")
            operator_response, operator_body = self.read_json(base_url + "/api/v1/tmux/capture", "operator-token", data={"name": "live"})

            self.assertEqual(owner_response.status, 200)
            self.assertEqual(owner_body["sessions"][0]["session_id"], "session-a")
            self.assertEqual(operator_response.status, 200)
            self.assertEqual(operator_body["screen"], "secret terminal text")

        self.with_auth_server(run)

    def test_tmux_websocket_requires_tmux_control_permission(self):
        role_tokens = {
            "viewer-token": {"id": "viewer-a", "roles": ["viewer"]},
            "operator-token": {"id": "operator-a", "roles": ["operator"]},
        }
        handler = object.__new__(studio.StudioHandler)

        with patch.object(studio, "auth_enabled", return_value=True), \
             patch.object(studio, "auth_token", return_value="owner-token"), \
             patch.object(studio, "auth_role_tokens", return_value=role_tokens):
            handler.path = "/ws/tmux?name=live"
            handler.headers = {"authorization": "Bearer viewer-token"}
            self.assertFalse(handler.tmux_websocket_authorized())

            handler.headers = {"authorization": "Bearer operator-token"}
            self.assertTrue(handler.tmux_websocket_authorized())


if __name__ == "__main__":
    unittest.main()
