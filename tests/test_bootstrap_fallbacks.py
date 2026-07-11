"""Bootstrap fallback reconciliation tests.

GOVERNANCE: `config/models.json` is the active model source of truth and
`config/default-models.json` is the single sanctioned bootstrap fallback.
These tests pin the proxy, `claude-DO.sh`, and `matts-image` to that contract
so no divergent hardcoded model/alias/pricing tables can reappear.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_FILE = ROOT / "config" / "default-models.json"
ACTIVE_MODELS_FILE = ROOT / "config" / "models.json"


def load_module(filename, module_name):
    loader = importlib.machinery.SourceFileLoader(module_name, str(ROOT / filename))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


proxy = load_module("do-anthropic-proxy.py", "do_anthropic_proxy_bootstrap")


def registry_expectations(path):
    """Derive expected models/aliases/costs exactly as declared by a registry file."""
    rows = json.loads(path.read_text(encoding="utf-8"))["models"]
    active = [model for model in rows if proxy._model_route_enabled(model)]
    text = [str(model["id"]) for model in active if model.get("type", "text") == "text"]
    image = [str(model["id"]) for model in active if model.get("type") == "image"]
    aliases = {str(alias): str(model["id"]) for model in active for alias in model.get("aliases") or [] if alias}
    costs = {
        str(model["id"]): {
            key: float(value or 0)
            for key, value in model["pricing"].items()
            if key in ("input", "output", "image")
        }
        for model in active
        if isinstance(model.get("pricing"), dict) and model["pricing"]
    }
    return text + image, aliases, costs


class ProxyBootstrapFallbackTests(unittest.TestCase):
    def test_proxy_bootstrap_fallbacks_match_default_models_file(self):
        expected_models, expected_aliases, expected_costs = registry_expectations(DEFAULT_MODELS_FILE)

        models, aliases, costs, warning = proxy._load_bootstrap_fallbacks()

        self.assertEqual(warning, "")
        self.assertEqual(models, expected_models)
        self.assertEqual(aliases, expected_aliases)
        self.assertEqual(costs, expected_costs)
        self.assertTrue(expected_costs, "default-models.json must declare pricing for the fallback path")

    def test_proxy_has_no_hardcoded_fallback_tables(self):
        for legacy_table in ("DEFAULT_COSTS_PER_MTOK", "MATTS_VALUE_SET_MODELS", "DEFAULT_ALIASES"):
            self.assertFalse(
                hasattr(proxy, legacy_table),
                "%s must not exist; config/default-models.json is the only sanctioned fallback source" % legacy_table,
            )

    def test_proxy_registry_failure_falls_back_to_default_models_data(self):
        expected_models, expected_aliases, expected_costs = registry_expectations(DEFAULT_MODELS_FILE)
        fallback_models, fallback_aliases, fallback_costs, _warning = proxy._load_bootstrap_fallbacks()
        with tempfile.TemporaryDirectory() as tmp:
            server = SimpleNamespace(
                model_config_file=str(Path(tmp) / "missing-models.json"),
                fallback_models=fallback_models,
                fallback_model_aliases=fallback_aliases,
                fallback_costs=fallback_costs,
                models=[],
                model_aliases={},
                costs={},
                model_registry_records=[],
                default_model="deepseek-3.2",
                model_config_loaded=False,
                model_config_fingerprint=None,
                model_config_last_check_at=0,
                model_config_last_loaded_at=0,
                model_config_last_error="",
            )

            proxy._refresh_model_registry(server, force=True)

        self.assertFalse(server.model_config_loaded)
        self.assertEqual(server.models, expected_models)
        self.assertEqual(server.model_aliases, expected_aliases)
        self.assertEqual(server.costs, expected_costs)
        self.assertEqual(
            server.costs["deepseek-3.2"],
            expected_costs["deepseek-3.2"],
            "fallback pricing must equal what config/default-models.json declares",
        )

    def test_proxy_bootstrap_loader_degrades_to_minimal_structure_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "missing-default-models.json")
            models, aliases, costs, warning = proxy._load_bootstrap_fallbacks(missing)

            corrupt = Path(tmp) / "corrupt-default-models.json"
            corrupt.write_text("{not json", encoding="utf-8")
            corrupt_models, corrupt_aliases, corrupt_costs, corrupt_warning = proxy._load_bootstrap_fallbacks(str(corrupt))

        self.assertEqual(models, [proxy.DEFAULT_MODEL])
        self.assertEqual(aliases, {})
        self.assertEqual(costs, {}, "degraded fallback must not invent a third divergent price list")
        self.assertIn(missing, warning)
        self.assertIn("minimal fallback model list", warning)
        self.assertEqual(corrupt_models, [proxy.DEFAULT_MODEL])
        self.assertEqual(corrupt_aliases, {})
        self.assertEqual(corrupt_costs, {})
        self.assertIn("minimal fallback model list", corrupt_warning)

    def test_proxy_port_default_is_18081(self):
        args = proxy._build_arg_parser().parse_args([])
        self.assertEqual(args.port, 18081)
        self.assertEqual(args.host, "127.0.0.1")


class MattsImageProxySpawnTests(unittest.TestCase):
    def test_matts_image_spawns_proxy_without_hardcoded_model_list(self):
        matts_image = load_module("matts-image", "matts_image_bootstrap")
        with patch.object(matts_image, "proxy_is_listening", side_effect=[False, True]), \
             patch.object(matts_image.subprocess, "Popen") as popen:
            matts_image.start_proxy_if_needed()

        cmd = popen.call_args[0][0]
        self.assertNotIn("--models", cmd)
        self.assertNotIn("--default-model", cmd)
        self.assertIn("--provider", cmd)
        self.assertIn("matts-value-set", cmd)
        self.assertEqual(matts_image.MODEL, "stable-diffusion-3.5-large")


class ClaudeDoFallbackTests(unittest.TestCase):
    def run_list_models(self, env_overrides):
        env = dict(os.environ)
        if "MATTS_MODEL_ACCESS_STATE_FILE" not in env_overrides:
            env.pop("MATTS_MODEL_ACCESS_STATE_FILE", None)
        env.update(env_overrides)
        result = subprocess.run(
            ["bash", str(ROOT / "claude-DO.sh"), "--list-models"],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        return [item["id"] for item in payload["data"]], result.stderr

    def test_claude_do_list_models_uses_registry_in_happy_path(self):
        expected_models, _aliases, _costs = registry_expectations(ACTIVE_MODELS_FILE)

        ids, stderr = self.run_list_models({"MATTS_MODEL_CONFIG_FILE": str(ACTIVE_MODELS_FILE)})

        self.assertEqual(ids, expected_models)
        self.assertNotIn("fallback", stderr)

    def test_claude_do_list_models_falls_back_to_default_models_file(self):
        expected_models, _aliases, _costs = registry_expectations(DEFAULT_MODELS_FILE)
        with tempfile.TemporaryDirectory() as tmp:
            ids, stderr = self.run_list_models({
                "MATTS_MODEL_CONFIG_FILE": str(Path(tmp) / "missing-models.json"),
            })

        self.assertEqual(ids, expected_models)
        self.assertIn("bootstrap fallback", stderr)

    def test_claude_do_list_models_minimal_fallback_when_bootstrap_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ids, stderr = self.run_list_models({
                "MATTS_MODEL_CONFIG_FILE": str(Path(tmp) / "missing-models.json"),
                "MATTS_DEFAULT_MODEL_CONFIG_FILE": str(Path(tmp) / "missing-default-models.json"),
            })

        self.assertEqual(ids, ["deepseek-3.2"])
        self.assertIn("minimal fallback model list", stderr)


if __name__ == "__main__":
    unittest.main()
