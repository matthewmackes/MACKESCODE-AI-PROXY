import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.plugins import PluginRegistryService


class PluginRegistryServiceTests(unittest.TestCase):
    def test_loads_enabled_disabled_and_invalid_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin_dir = root / "plugins"
            plugin_dir.mkdir()
            (plugin_dir / "enabled.json").write_text(json.dumps({
                "id": "enabled-plugin",
                "name": "Enabled",
                "version": "1.0.0",
                "extensions": [{"point": "console.panel", "label": "Panel"}],
            }), encoding="utf-8")
            (plugin_dir / "disabled.json").write_text(json.dumps({
                "id": "disabled-plugin",
                "enabled": False,
                "extensions": [{"point": "console.panel"}],
            }), encoding="utf-8")
            (plugin_dir / "invalid.json").write_text(json.dumps({
                "id": "invalid-plugin",
                "extensions": [{"point": "unknown.point"}],
            }), encoding="utf-8")

            payload = PluginRegistryService({"enabled": True, "directories": ["plugins"]}, root).payload()

        by_id = {item["id"]: item for item in payload["plugins"]}
        self.assertEqual(payload["counts"], {"total": 3, "enabled": 1, "invalid": 1})
        self.assertTrue(by_id["enabled-plugin"]["enabled"])
        self.assertEqual(by_id["disabled-plugin"]["status"], "disabled")
        self.assertEqual(by_id["invalid-plugin"]["status"], "invalid")
        self.assertEqual(by_id["invalid-plugin"]["invalid_extensions"][0]["point"], "unknown.point")

    def test_disabled_registry_does_not_load_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plugins").mkdir()
            payload = PluginRegistryService({"enabled": False, "directories": ["plugins"]}, root).payload()

        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["plugins"], [])
        self.assertEqual(payload["counts"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
