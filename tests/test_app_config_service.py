import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.app_config import ConfigError, ConsoleConfigService, deep_merge


class ConsoleConfigServiceTests(unittest.TestCase):
    def test_deep_merge_preserves_nested_defaults(self):
        merged = deep_merge({"server": {"host": "0.0.0.0", "port": 18181}, "auth": {"enabled": True}}, {"server": {"port": 19000}})

        self.assertEqual(merged["server"], {"host": "0.0.0.0", "port": 19000})
        self.assertEqual(merged["auth"], {"enabled": True})

    def test_loads_file_and_environment_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "console.json"
            path.write_text(json.dumps({"server": {"port": 19000}, "models": {"auto_enable_max_usd": 0.25}}), encoding="utf-8")
            service = ConsoleConfigService(
                config_path=path,
                env={
                    "MATTS_STUDIO_HOST": "127.0.0.1",
                    "MATTS_VALUE_SET_PROXY_PORT": "19999",
                    "MATTS_CONSOLE_DISABLE_AUTH": "1",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
                    "OTEL_SERVICE_NAME": "matts-test-console",
                    "OTEL_EXPORTER_OTLP_TIMEOUT": "500",
                    "OTEL_EXPORTER_OTLP_HEADERS": "x-api-key=abc,tenant=dev",
                },
            )

            config = service.load()

        self.assertEqual(config["server"]["host"], "127.0.0.1")
        self.assertEqual(config["server"]["port"], 19000)
        self.assertEqual(config["models"]["auto_enable_max_usd"], 0.25)
        self.assertEqual(config["proxy"]["port"], 19999)
        self.assertEqual(config["paths"]["template_dir"], "templates")
        self.assertFalse(config["auth"]["enabled"])
        self.assertTrue(config["observability"]["opentelemetry"]["enabled"])
        self.assertEqual(config["observability"]["opentelemetry"]["endpoint"], "http://collector:4318")
        self.assertEqual(config["observability"]["opentelemetry"]["service_name"], "matts-test-console")
        self.assertEqual(config["observability"]["opentelemetry"]["timeout_seconds"], 0.5)
        self.assertEqual(config["observability"]["opentelemetry"]["headers"]["x-api-key"], "abc")

    def test_validation_rejects_bad_ports_and_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_json = Path(tmp) / "bad.json"
            bad_json.write_text("{", encoding="utf-8")
            with self.assertRaises(ConfigError):
                ConsoleConfigService(config_path=bad_json, env={}).load()

            bad_port = Path(tmp) / "bad-port.json"
            bad_port.write_text(json.dumps({"server": {"port": 70000}}), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "server.port"):
                ConsoleConfigService(config_path=bad_port, env={}).load()

    def test_invalid_environment_override_reports_name(self):
        with self.assertRaisesRegex(ConfigError, "MATTS_STUDIO_PORT"):
            ConsoleConfigService(env={"MATTS_STUDIO_PORT": "nope"}, config_path=Path("/missing")).load()
        with self.assertRaisesRegex(ConfigError, "OTEL_EXPORTER_OTLP_TIMEOUT"):
            ConsoleConfigService(env={"OTEL_EXPORTER_OTLP_TIMEOUT": "slow"}, config_path=Path("/missing")).load()


if __name__ == "__main__":
    unittest.main()
