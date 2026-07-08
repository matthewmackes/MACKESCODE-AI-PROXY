import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def load_proxy_module():
    spec = importlib.util.spec_from_file_location("do_anthropic_proxy_registry", ROOT / "do-anthropic-proxy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proxy = load_proxy_module()


def write_registry(path, model_id):
    path.write_text(json.dumps({
        "models": [{
            "id": model_id,
            "type": "text",
            "enabled": True,
            "serverless": True,
            "access_status": "ok",
            "aliases": ["primary"],
            "pricing": {"input": 0.11, "output": 0.22},
        }]
    }), encoding="utf-8")
    now = time.time() + 0.01
    path.touch()
    return now


def server_for(path):
    return SimpleNamespace(
        model_config_file=str(path),
        fallback_models=["fallback-model"],
        fallback_model_aliases={"fallback": "fallback-model"},
        fallback_costs={"fallback-model": {"input": 1.0, "output": 2.0}},
        models=["fallback-model"],
        model_aliases={"fallback": "fallback-model"},
        costs={"fallback-model": {"input": 1.0, "output": 2.0}},
        default_model="fallback-model",
        model_config_loaded=False,
        model_config_fingerprint=None,
        model_config_last_check_at=0,
        model_config_last_loaded_at=0,
        model_config_last_error="",
    )


class ProxyRegistryReloadTests(unittest.TestCase):
    def test_refresh_tracks_fingerprint_and_skips_unchanged_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            write_registry(path, "model-a")
            server = server_for(path)

            proxy._refresh_model_registry(server, force=True)
            first_loaded_at = server.model_config_last_loaded_at
            proxy._refresh_model_registry(server)

        self.assertEqual(server.models, ["model-a"])
        self.assertEqual(server.model_aliases["primary"], "model-a")
        self.assertEqual(server.costs["model-a"]["input"], 0.11)
        self.assertEqual(server.model_config_last_loaded_at, first_loaded_at)
        self.assertTrue(server.model_config_loaded)

    def test_refresh_reloads_when_registry_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            write_registry(path, "model-a")
            server = server_for(path)
            proxy._refresh_model_registry(server, force=True)

            time.sleep(0.01)
            write_registry(path, "model-b")
            stale_state = proxy._model_config_state(server)
            proxy._refresh_model_registry(server)
            fresh_state = proxy._model_config_state(server)

        self.assertTrue(stale_state["stale"])
        self.assertEqual(server.models, ["model-b"])
        self.assertEqual(server.model_aliases["primary"], "model-b")
        self.assertFalse(fresh_state["stale"])
        self.assertTrue(fresh_state["loaded"])

    def test_missing_registry_reports_load_error_and_uses_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-models.json"
            server = server_for(path)
            proxy._refresh_model_registry(server, force=True)
            state = proxy._model_config_state(server)

        self.assertFalse(state["loaded"])
        self.assertIn("No such file", state["last_error"])
        self.assertEqual(server.models, ["fallback-model"])
        self.assertEqual(server.model_aliases["fallback"], "fallback-model")


if __name__ == "__main__":
    unittest.main()
