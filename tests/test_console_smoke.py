import importlib.util
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
    def test_main_template_loads_from_template_directory(self):
        html = studio.load_template("main.html")
        self.assertIn("<header>", html)
        self.assertIn('id="create"', html)
        self.assertIn('id="console"', html)

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


if __name__ == "__main__":
    unittest.main()
