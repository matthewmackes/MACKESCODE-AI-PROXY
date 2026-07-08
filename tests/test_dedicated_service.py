import json
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services.dedicated import DedicatedInferenceService


DEFAULT_CONFIG = {
    "state": "not_configured",
    "name": "test-dedicated",
    "version": "1",
    "region": "nyc2",
    "vpc_uuid": "",
    "model_slug": "",
    "model_provider": "",
    "deployment_name": "primary",
    "accelerator_slug": "",
    "accelerator_type": "prefill_decode",
    "scale": 1,
    "enable_public_endpoint": True,
    "inference_id": "",
    "model_id": "dedicated-inference",
    "display_name": "Dedicated Inference",
    "fallback_model": "serverless-a",
    "price_per_hour": 0.0,
    "daily_budget_usd": 0.0,
    "warning_threshold": 0.8,
    "cooldown_threshold": 0.95,
    "idle_warning_seconds": 300,
    "idle_teardown_seconds": 600,
    "auto_rebuild": True,
    "public_endpoint_fqdn": "",
    "private_endpoint_fqdn": "",
    "access_token": "",
    "ca_certificate": "",
    "created_at": 0,
    "run_started_at": 0,
    "last_work_at": 0,
    "last_status_at": 0,
    "last_error": "",
    "raw": {},
}


class DedicatedInferenceServiceTests(unittest.TestCase):
    def service(self, tmp, token="do-token", now=1000, do_request=None, health=None, legacy_config_file=None):
        root = Path(tmp)
        config_path = root / "dedicated.json"
        events_path = root / "dedicated-events.jsonl"
        registry = []

        def tail_jsonl(path, limit=80):
            if not path.exists():
                return []
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[-limit:]]

        def load_model_registry(include_disabled=True):
            return list(registry)

        def save_model_registry(models):
            registry[:] = list(models)
            return list(registry)

        service = DedicatedInferenceService(
            default_config=DEFAULT_CONFIG,
            steps=["plan", "build", "route"],
            config_file=lambda: config_path,
            legacy_config_file=legacy_config_file,
            events_file=lambda: events_path,
            tail_jsonl=tail_jsonl,
            digitalocean_token=lambda: token,
            do_request=do_request or (lambda path, token, payload=None, timeout=60, method="GET": (200, {})),
            load_model_registry=load_model_registry,
            save_model_registry=save_model_registry,
            refresh_model_globals=lambda: None,
            models_payload=lambda: {"models": registry},
            digitalocean_health_snapshot=health or (lambda: {"configured": bool(token), "platform": {"indicator": "none"}}),
            serverless_chat_completion=lambda data, model, allow_unregistered=False: (HTTPStatus.OK, {"text": "fallback"}),
            active_text_models=lambda: ["serverless-a"],
            default_text_model=lambda: "serverless-a",
            clock=lambda: now,
        )
        return service, registry

    def test_config_round_trip_and_public_payload_redacts_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=4600)
            saved = service.save_config({
                "state": "active",
                "access_token": "secret",
                "run_started_at": 1000,
                "last_work_at": 4300,
                "price_per_hour": 2.0,
                "daily_budget_usd": 10,
            })
            loaded = service.load_config()
            payload = service.public_payload(loaded)

        self.assertEqual(saved["state"], "active")
        self.assertEqual(loaded["access_token"], "secret")
        self.assertEqual(payload["access_token"], "")
        self.assertTrue(payload["access_token_configured"])
        self.assertEqual(payload["elapsed_seconds"], 3600)
        self.assertEqual(payload["idle_seconds"], 300)
        self.assertEqual(payload["estimated_cost_usd"], 2.0)
        self.assertEqual(payload["budget_percent"], 20.0)

    def test_load_config_migrates_legacy_config_when_runtime_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = Path(tmp) / "legacy-dedicated.json"
            legacy_path.write_text(json.dumps({"state": "active", "model_id": "legacy-model"}), encoding="utf-8")
            service, _ = self.service(tmp, legacy_config_file=lambda: legacy_path)

            cfg = service.load_config()

            self.assertEqual(cfg["state"], "active")
            self.assertEqual(cfg["model_id"], "legacy-model")
            self.assertTrue((Path(tmp) / "dedicated.json").exists())

    def test_resource_update_activates_and_clears_stale_endpoint_until_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=2000)
            cfg = dict(DEFAULT_CONFIG, public_endpoint_fqdn="stale.example.com")
            provisioning = service.update_from_resource(cfg, {"status": "provisioning"})
            self.assertEqual(provisioning["public_endpoint_fqdn"], "")
            active = service.update_from_resource(dict(provisioning), {
                "status": "active",
                "endpoints": {"public_endpoint_fqdn": "ready.example.com"},
            })

        self.assertEqual(active["state"], "active")
        self.assertEqual(active["run_started_at"], 2000)
        self.assertEqual(service.endpoint(active), "https://ready.example.com")

    def test_resource_issue_ignores_pending_unassigned_invalid_accelerator(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp)
            pending = {
                "pending_deployment_spec": {
                    "status": "pending",
                    "model_deployments": [{
                        "model_slug": "Qwen/Qwen3-32B",
                        "accelerators": [{"accelerator_slug": "gpu-mi325x1-256gb", "status": "invalid"}],
                    }],
                }
            }
            assigned = {
                "deployment_spec": {
                    "status": "active",
                    "model_deployments": [{
                        "model_slug": "Qwen/Qwen3-32B",
                        "accelerators": [{"accelerator_id": "acc-1", "accelerator_slug": "gpu-mi300x1-192gb", "status": "invalid"}],
                    }],
                }
            }

        self.assertEqual(service.resource_issue(pending), "")
        self.assertIn("gpu-mi300x1-192gb", service.resource_issue(assigned))

    def test_register_model_replaces_existing_managed_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, registry = self.service(tmp)
            registry.append({"id": "dedicated-inference", "enabled": False, "type": "text"})
            entry = service.register_model(dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-1",
                public_endpoint_fqdn="ready.example.com",
                price_per_hour=2.59,
            ))

        self.assertEqual(len(registry), 1)
        self.assertTrue(entry["enabled"])
        self.assertEqual(entry["dedicated"]["server_id"], "server-1")
        self.assertEqual(entry["pricing"]["hourly"], 2.59)

    def test_not_ready_payload_is_human_friendly_and_includes_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp)
            cfg = dict(DEFAULT_CONFIG, state="provisioning", inference_id="server-1", region="tor1", accelerator_slug="gpu-mi325x1-256gb")
            payload = service.not_ready_payload(cfg, "dedicated-inference")

        self.assertIn("not ready yet", payload["message"])
        self.assertEqual(payload["lifecycle"]["server_id"], "server-1")
        self.assertFalse(payload["lifecycle"]["endpoint_ready"])
        self.assertIn("Wait for DigitalOcean", payload["lifecycle"]["next_step"])

    def test_status_payload_polls_active_resource_and_issues_token(self):
        calls = []

        def do_request(path, token, payload=None, timeout=60, method="GET"):
            calls.append((path, payload, method))
            if path.endswith("/tokens"):
                return 201, {"token": {"value": "runtime-token"}}
            return 200, {
                "dedicated_inference": {
                    "id": "server-1",
                    "status": "active",
                    "endpoints": {"public_endpoint_fqdn": "ready.example.com"},
                }
            }

        with tempfile.TemporaryDirectory() as tmp:
            service, registry = self.service(tmp, do_request=do_request, now=2000)
            service.save_config(dict(DEFAULT_CONFIG, state="provisioning", inference_id="server-1"))
            payload = service.status_payload(poll=True)
            cfg = service.load_config()

        self.assertEqual(payload["dedicated"]["state"], "active")
        self.assertEqual(cfg["access_token"], "runtime-token")
        self.assertEqual(registry[0]["dedicated"]["server_id"], "server-1")
        self.assertTrue(any(call[0].endswith("/tokens") for call in calls))


if __name__ == "__main__":
    unittest.main()
