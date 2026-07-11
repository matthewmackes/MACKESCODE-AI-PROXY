import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from backend.v2 import app as app_module

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def console_auth_env():
    keys = ("MATTS_CONSOLE_AUTH_ENABLED", "MATTS_CONSOLE_AUTH_TOKEN", "MATTS_CONSOLE_ROLE_TOKENS")
    old = {key: os.environ.get(key) for key in keys}
    os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "1"
    os.environ["MATTS_CONSOLE_AUTH_TOKEN"] = "owner-token-secret"
    os.environ["MATTS_CONSOLE_ROLE_TOKENS"] = json.dumps({
        "viewer-token": {"id": "viewer-user", "roles": ["viewer"]},
        "operator-token": {"id": "operator-user", "roles": ["operator"]},
    })
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def load_launcher():
    path = ROOT / "matts-v2-console.py"
    spec = importlib.util.spec_from_file_location("matts_v2_console", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V2AppLauncherTests(unittest.TestCase):
    def fake_runtime(self):
        return types.SimpleNamespace(auth_token=lambda: "test-token", local_addresses=lambda: ["192.0.2.10"])

    def run_launcher_main(self, launcher):
        output = StringIO()
        with redirect_stdout(output):
            status = launcher.main()
        return status, output.getvalue()

    def test_create_app_mounts_react_dist_when_present(self):
        if app_module.FastAPI is None or app_module.StaticFiles is None:
            self.skipTest("fastapi is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("<div>v2</div>", encoding="utf-8")
            with patch.object(app_module, "FRONTEND_DIST", dist):
                app = app_module.create_app()

        self.assertTrue(any(getattr(route, "name", "") == "react" for route in app.routes))

    def test_v2_api_404_returns_route_suggestions_without_breaking_root(self):
        if app_module.FastAPI is None or app_module.StaticFiles is None or TestClient is None:
            self.skipTest("fastapi test client is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("<!doctype html><div id=\"root\">v2</div>", encoding="utf-8")
            with patch.object(app_module, "FRONTEND_DIST", dist):
                client = TestClient(app_module.create_app())

            missing = client.get("/v2/research/engin")
            root = client.get("/")

        self.assertEqual(missing.status_code, 404)
        payload = missing.json()
        self.assertEqual(payload["code"], "api_endpoint_not_found")
        self.assertEqual(payload["details"]["method"], "GET")
        self.assertEqual(payload["details"]["path"], "/v2/research/engin")
        self.assertIn("/v2/research/engines", payload["details"]["suggested_endpoints"])
        self.assertIn({"path": "/v2/research/engines", "methods": ["GET"]}, payload["details"]["nearby_endpoints"])
        self.assertEqual(root.status_code, 200)
        self.assertIn('id="root"', root.text)

    def test_v2_api_404_reports_exact_path_wrong_method(self):
        if app_module.FastAPI is None or app_module.StaticFiles is None or TestClient is None:
            self.skipTest("fastapi test client is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("<!doctype html><div id=\"root\">v2</div>", encoding="utf-8")
            with patch.object(app_module, "FRONTEND_DIST", dist):
                client = TestClient(app_module.create_app())

            missing = client.get("/v2/research/search?token=secret")

        self.assertEqual(missing.status_code, 404)
        payload = missing.json()
        self.assertEqual(payload["code"], "api_endpoint_not_found")
        self.assertEqual(payload["details"]["path"], "/v2/research/search")
        self.assertEqual(payload["details"]["method"], "GET")
        self.assertTrue(payload["details"]["method_mismatch"])
        self.assertEqual(payload["details"]["allowed_methods"], ["POST"])
        self.assertEqual(payload["details"]["suggested_endpoints"], ["/v2/research/search"])
        self.assertIn("Use POST /v2/research/search", payload["details"]["suggested_fix"])
        self.assertNotIn("secret", missing.text)

    def test_v2_api_405_returns_structured_allowed_method_details(self):
        if app_module.FastAPI is None or app_module.StaticFiles is None or TestClient is None:
            self.skipTest("fastapi test client is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("<!doctype html><div id=\"root\">v2</div>", encoding="utf-8")
            with patch.object(app_module, "FRONTEND_DIST", dist):
                client = TestClient(app_module.create_app())

            wrong_method = client.post("/v2/research/engines")

        self.assertEqual(wrong_method.status_code, 405)
        payload = wrong_method.json()
        self.assertEqual(payload["code"], "api_method_not_allowed")
        self.assertEqual(payload["message"], "api method not allowed")
        self.assertEqual(payload["details"]["path"], "/v2/research/engines")
        self.assertEqual(payload["details"]["method"], "POST")
        self.assertTrue(payload["details"]["method_mismatch"])
        self.assertEqual(payload["details"]["allowed_methods"], ["GET"])
        self.assertIn("Use GET /v2/research/engines", payload["details"]["suggested_fix"])

    def test_ws_tmux_route_is_registered_before_react_static_mount(self):
        if app_module.FastAPI is None or app_module.StaticFiles is None:
            self.skipTest("fastapi is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("<!doctype html><div id=\"root\">v2</div>", encoding="utf-8")
            with patch.object(app_module, "FRONTEND_DIST", dist):
                app = app_module.create_app()

        tmux_index = next(index for index, route in enumerate(app.routes) if getattr(route, "path", "") == "/ws/tmux")
        react_index = next(index for index, route in enumerate(app.routes) if getattr(route, "name", "") == "react")
        self.assertLess(tmux_index, react_index)

    def test_ws_tmux_viewer_denial_uses_v2_route_not_static_mount(self):
        if app_module.FastAPI is None or app_module.StaticFiles is None or TestClient is None:
            self.skipTest("fastapi test client is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("<!doctype html><div id=\"root\">v2</div>", encoding="utf-8")
            with patch.object(app_module, "FRONTEND_DIST", dist), console_auth_env():
                client = TestClient(app_module.create_app())
                with client.websocket_connect("/ws/tmux?session=work&token=viewer-token") as websocket:
                    payload = websocket.receive_json()

        self.assertEqual(payload["type"], "denied")
        self.assertEqual(payload["decision"]["required_permission"], "tmux_control")

    def test_cors_origins_default_to_remote_browser_friendly_wildcard(self):
        old_env = os.environ.get("MATTS_V2_CORS_ORIGINS")
        os.environ.pop("MATTS_V2_CORS_ORIGINS", None)
        try:
            self.assertEqual(app_module.cors_origins(), ["*"])
        finally:
            if old_env is None:
                os.environ.pop("MATTS_V2_CORS_ORIGINS", None)
            else:
                os.environ["MATTS_V2_CORS_ORIGINS"] = old_env

    def test_cors_origins_parse_explicit_remote_hosts(self):
        old_env = os.environ.get("MATTS_V2_CORS_ORIGINS")
        os.environ["MATTS_V2_CORS_ORIGINS"] = "http://console.example:5173, https://console.example "
        try:
            self.assertEqual(app_module.cors_origins(), ["http://console.example:5173", "https://console.example"])
        finally:
            if old_env is None:
                os.environ.pop("MATTS_V2_CORS_ORIGINS", None)
            else:
                os.environ["MATTS_V2_CORS_ORIGINS"] = old_env

    def test_launcher_builds_missing_assets_and_starts_uvicorn(self):
        launcher = load_launcher()
        uvicorn = types.SimpleNamespace(run=Mock())
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "frontend" / "dist"
            with (
                patch.object(launcher, "FRONTEND_DIST", dist),
                patch.object(launcher, "build_frontend") as build_frontend,
                patch.object(launcher, "runtime_config", self.fake_runtime),
                patch.dict(sys.modules, {"uvicorn": uvicorn}),
                patch.object(sys, "argv", ["matts-v2-console.py", "--host", "0.0.0.0", "--port", "19000"]),
            ):
                status, output = self.run_launcher_main(launcher)

        self.assertEqual(status, 0)
        self.assertIn("React v2 console: http://0.0.0.0:19000/?token=test-token", output)
        self.assertIn("Reachable React v2 URL: http://192.0.2.10:19000/?token=test-token", output)
        build_frontend.assert_called_once_with()
        uvicorn.run.assert_called_once_with("backend.v2.app:app", host="0.0.0.0", port=19000, reload=False)

    def test_build_frontend_uses_npm_ci_when_lockfile_exists(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as tmp:
            frontend = Path(tmp) / "frontend"
            frontend.mkdir()
            lockfile = frontend / "package-lock.json"
            lockfile.write_text("{}", encoding="utf-8")
            run = Mock()
            with (
                patch.object(launcher, "FRONTEND_DIR", frontend),
                patch.object(launcher, "FRONTEND_LOCK", lockfile),
                patch.object(launcher.subprocess, "run", run),
            ):
                launcher.build_frontend()

        self.assertEqual([call.args[0] for call in run.call_args_list], [["npm", "ci", "--no-audit"], ["npm", "run", "build"]])
        self.assertEqual([call.kwargs["cwd"] for call in run.call_args_list], [str(frontend), str(frontend)])

    def test_build_frontend_falls_back_to_npm_install_without_lockfile(self):
        launcher = load_launcher()
        with tempfile.TemporaryDirectory() as tmp:
            frontend = Path(tmp) / "frontend"
            frontend.mkdir()
            run = Mock()
            with (
                patch.object(launcher, "FRONTEND_DIR", frontend),
                patch.object(launcher, "FRONTEND_LOCK", frontend / "package-lock.json"),
                patch.object(launcher.subprocess, "run", run),
            ):
                launcher.build_frontend()

        self.assertEqual([call.args[0] for call in run.call_args_list], [["npm", "install", "--no-audit"], ["npm", "run", "build"]])

    def test_launcher_defaults_to_remote_host_for_headless_console(self):
        launcher = load_launcher()
        uvicorn = types.SimpleNamespace(run=Mock())
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "frontend" / "dist"
            dist.mkdir(parents=True)
            with (
                patch.object(launcher, "FRONTEND_DIST", dist),
                patch.object(launcher, "build_frontend") as build_frontend,
                patch.object(launcher, "runtime_config", self.fake_runtime),
                patch.dict(sys.modules, {"uvicorn": uvicorn}),
                patch.object(sys, "argv", ["matts-v2-console.py"]),
            ):
                status, output = self.run_launcher_main(launcher)

        self.assertEqual(status, 0)
        self.assertIn("React v2 console: http://0.0.0.0:18182/?token=test-token", output)
        self.assertIn("Reachable React v2 URL: http://192.0.2.10:18182/?token=test-token", output)
        build_frontend.assert_not_called()
        uvicorn.run.assert_called_once_with("backend.v2.app:app", host="0.0.0.0", port=18182, reload=False)

    def test_launcher_sets_cors_origins_from_flags(self):
        launcher = load_launcher()
        uvicorn = types.SimpleNamespace(run=Mock())
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "frontend" / "dist"
            dist.mkdir(parents=True)
            with (
                patch.object(launcher, "FRONTEND_DIST", dist),
                patch.object(launcher, "runtime_config", self.fake_runtime),
                patch.dict(sys.modules, {"uvicorn": uvicorn}),
                patch.dict("os.environ", {}, clear=True),
                patch.object(sys, "argv", ["matts-v2-console.py", "--cors-origin", "http://console.example:5173", "--cors-origin", "https://console.example"]),
            ):
                status, output = self.run_launcher_main(launcher)
                self.assertEqual(launcher.os.environ["MATTS_V2_CORS_ORIGINS"], "http://console.example:5173,https://console.example")

        self.assertEqual(status, 0)
        self.assertIn("React v2 console: http://0.0.0.0:18182/?token=test-token", output)


if __name__ == "__main__":
    unittest.main()
