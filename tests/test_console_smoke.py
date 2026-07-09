import importlib.util
import io
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_studio_module():
    spec = importlib.util.spec_from_file_location("image_studio", ROOT / "image-studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


studio = load_studio_module()


class TemplateSmokeTests(unittest.TestCase):
    def test_default_model_registry_loads_from_configured_file(self):
        self.assertTrue(studio.DEFAULT_MODEL_REGISTRY)
        self.assertTrue(any(model["id"] == "deepseek-3.2" for model in studio.DEFAULT_MODEL_REGISTRY))

    def test_main_template_loads_from_template_directory(self):
        html = studio.load_template("main.html")
        self.assertIn("<header>", html)
        self.assertIn('id="create"', html)
        self.assertIn('id="console"', html)
        self.assertIn("function routeBadge", html)
        self.assertIn("registry_sync:routing.registry_sync", html)
        self.assertIn("route-badge", html)
        self.assertIn("LLM Management", html)
        self.assertIn('id="models-editor"', html)
        self.assertIn('id="models-save"', html)
        self.assertIn('id="models-add"', html)
        self.assertIn('id="models-import-serverless"', html)
        self.assertIn('id="global-dedicated-meter"', html)
        self.assertIn("function dedicatedPolicyAlerts", html)
        self.assertIn("function updateDedicatedTopMeter", html)
        self.assertIn("function renderGlobalAlert", html)
        self.assertIn("budget_state", html)
        self.assertIn("idle_policy", html)
        self.assertIn("unhealthy_policy", html)
        self.assertIn("dedicatedBuildAgainHtml", html)
        self.assertIn("buildDedicatedFromModel", html)
        self.assertIn("dedicated-build-again", html)
        self.assertIn('data-console-view="traces"', html)
        self.assertIn('id="traces-results"', html)
        self.assertIn("function loadTraces", html)
        self.assertIn("trace_id", html)
        self.assertIn("fallback_reason", html)
        self.assertIn("upstream_url", html)
        self.assertIn("error_category", html)
        self.assertIn("human_message", html)
        self.assertIn("claude_do", html)
        self.assertIn('id="gateway-policy-grid"', html)
        self.assertIn('id="gateway-decisions"', html)
        self.assertIn("function renderGatewayPolicy", html)
        self.assertIn("function loadGatewayDecisions", html)
        self.assertIn("gateway_policy", html)
        self.assertIn('id="chat-compare-models"', html)
        self.assertIn("function compareChatModels", html)
        self.assertIn("function continueWithModel", html)
        self.assertIn("data-continue-model", html)
        self.assertIn("Continue with this model", html)
        self.assertIn("/api/chat/compare", html)
        self.assertIn("function runEval", html)
        self.assertIn("/api/evals/run", html)
        self.assertIn('id="create-mood"', html)
        self.assertIn("function loadCreateMood", html)
        self.assertIn("function updateCursorLight", html)
        self.assertIn("createMotes", html)
        self.assertIn('id="create-greeting"', html)
        self.assertIn("function typeCreateGreeting", html)
        self.assertIn("function createGreetingText", html)
        self.assertIn('id="wallpaper-info"', html)
        self.assertIn("function modelStyleVars", html)
        self.assertIn("function applyModelStyle", html)
        self.assertIn("new_until", html)
        self.assertIn("model-generated", html)
        self.assertIn('id="model-hero-modal"', html)
        self.assertIn("function openModelHero", html)
        self.assertIn("/api/model-info", html)
        self.assertIn("data-model-info", html)
        self.assertIn("Model Info", html)

    def test_render_template_replaces_string_and_json_values(self):
        html = studio.render_template(
            "main.html",
            {
                "SCRIPT_DIR": "/tmp/example-project",
                "TEXT_MODELS": ["model-a"],
            },
        )
        self.assertIn("/tmp/example-project", html)
        self.assertIn('["model-a"]', html)
        self.assertNotIn("__SCRIPT_DIR__", html)


class HealthSmokeTests(unittest.TestCase):
    def test_console_status_ok_when_proxy_and_launcher_are_ready(self):
        with patch.object(studio, "port_open", return_value=True), \
             patch.object(studio, "launcher_health", return_value={"ok": True, "healed": False, "path": "/tmp/claude-DO.sh"}), \
             patch.object(studio, "auth_enabled", return_value=True), \
             patch.object(studio, "SERVER_STARTED_AT", time.time() - 5):
            status = studio.console_status()

        self.assertEqual(status["service"], "matts-unified-console")
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


class RequestParsingTests(unittest.TestCase):
    def test_read_json_reports_malformed_body(self):
        handler = object.__new__(studio.StudioHandler)
        handler.headers = {"content-length": "1"}
        handler.rfile = io.BytesIO(b"{")

        with self.assertRaisesRegex(ValueError, "invalid JSON request body"):
            handler.read_json()


if __name__ == "__main__":
    unittest.main()
