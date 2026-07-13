import gzip
import json
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services.dedicated import DedicatedInferenceService


DEFAULT_CONFIG = {
    "schema_version": 1,
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
    "unhealthy_teardown_seconds": 300,
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
    def service(self, tmp, token="do-token", now=1000, do_request=None, health=None, legacy_config_file=None, local_usage_report=None):
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
            local_usage_report=local_usage_report,
            clock=lambda: now,
        )
        return service, registry

    def critical_build_data(self):
        return {
            "name": "test-dedicated",
            "region": "tor1",
            "vpc_uuid": "vpc-1",
            "model_slug": "Qwen/Qwen3-32B",
            "model_provider": "hugging_face",
            "accelerator_slug": "gpu-mi325x1-256gb",
            "model_id": "qwen-dedicated",
            "fallback_model": "serverless-a",
            "price_per_hour": 10,
            "daily_budget_usd": 10,
            "warning_threshold": 0.7,
            "cooldown_threshold": 0.9,
        }

    def seed_one_hour_dedicated_runtime(self, tmp, start=6400, end=10000):
        path = Path(tmp) / "dedicated-events.jsonl"
        rows = [
            {"ts": start, "state": "provisioning", "message": "Dedicated Inference creation accepted by DigitalOcean"},
            {"ts": end, "state": "deleted", "message": "Dedicated model removed and teardown requested"},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

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
        self.assertEqual(saved["schema_version"], 1)
        self.assertTrue(payload["config_status"]["valid"])

    def test_load_config_migrates_legacy_config_when_runtime_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_path = Path(tmp) / "legacy-dedicated.json"
            legacy_path.write_text(json.dumps({"state": "active", "model_id": "legacy-model"}), encoding="utf-8")
            service, _ = self.service(tmp, legacy_config_file=lambda: legacy_path)

            cfg = service.load_config()

            self.assertEqual(cfg["state"], "active")
            self.assertEqual(cfg["model_id"], "legacy-model")
            self.assertTrue((Path(tmp) / "dedicated.json").exists())
            migrated = json.loads((Path(tmp) / "dedicated.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], 1)

    def test_config_status_reports_malformed_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dedicated.json"
            path.write_text(json.dumps({"schema_version": 99, "state": "active"}), encoding="utf-8")
            service, _ = self.service(tmp)

            status = service.config_status()
            cfg = service.load_config()

            self.assertFalse(status["valid"])
            self.assertIn("schema_version 99 is not supported", status["issues"][0])
            self.assertEqual(cfg["state"], "not_configured")

    def test_build_blocks_when_daily_budget_is_critical(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            self.seed_one_hour_dedicated_runtime(tmp)
            service, _ = self.service(
                tmp,
                now=10000,
                do_request=lambda *args, **kwargs: calls.append((args, kwargs)) or (500, {}),
            )

            status, payload = service.build(self.critical_build_data())
            events = service.events()

        self.assertEqual(status, HTTPStatus.PAYMENT_REQUIRED)
        self.assertIn("daily budget", payload["message"])
        self.assertEqual(payload["budget_state"]["percent"], 100.0)
        self.assertFalse(calls)
        blocked = next(event for event in events if event["state"] == "budget_blocked")
        self.assertEqual(blocked["details"]["accelerator_slug"], "gpu-mi325x1-256gb")

    def test_build_budget_override_is_logged_with_context(self):
        calls = []

        def do_request(path, token, payload=None, timeout=60, method="GET"):
            calls.append((path, method))
            if path.endswith("/tokens"):
                return 201, {"token": {"value": "runtime-token"}}
            if method == "POST":
                return 202, {"id": "server-1"}
            return 200, {"dedicated_inference": {"id": "server-1", "status": "provisioning"}}

        with tempfile.TemporaryDirectory() as tmp:
            self.seed_one_hour_dedicated_runtime(tmp)
            service, _ = self.service(tmp, now=10000, do_request=do_request)
            data = dict(self.critical_build_data(), budget_override=True, operator="console-token:abc")

            status, _ = service.build(data)
            events = service.events()

        override = next(event for event in events if event["state"] == "budget_override")
        self.assertEqual(status, HTTPStatus.ACCEPTED)
        self.assertIn(("/v2/dedicated-inferences", "POST"), calls)
        self.assertEqual(override["details"]["operator"], "console-token:abc")
        self.assertEqual(override["details"]["model_slug"], "Qwen/Qwen3-32B")
        self.assertEqual(override["details"]["fallback_model"], "serverless-a")

    def test_capacity_plan_estimates_cost_break_even_and_fit(self):
        calls = []

        def do_request(path, token, payload=None, timeout=60, method="GET"):
            calls.append((path, method))
            if path.endswith("/sizes"):
                return 200, {
                    "sizes": [{
                        "slug": "gpu-mi325x1-256gb",
                        "regions": ["nyc2", "tor1"],
                    }]
                }
            if path.endswith("/gpu-model-config"):
                return 200, {
                    "config": [{
                        "accelerator_slug": "gpu-mi325x1-256gb",
                        "models": ["Qwen/Qwen3-32B"],
                    }]
                }
            return 200, {}

        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(
                tmp,
                now=200000,
                do_request=do_request,
                health=lambda: {
                    "configured": True,
                    "account": {"status": "active"},
                    "prepay": {"status": "ok"},
                    "platform": {"indicator": "none"},
                },
            )
            plan = service.capacity_plan(dict(
                self.critical_build_data(),
                region="nyc2",
                vpc_uuid="vpc-1",
                price_per_hour=2,
                daily_budget_usd=100,
                projected_serverless_daily_usd=80,
                idle_teardown_seconds=1800,
            ))

        self.assertEqual(plan["recommendation"], "build")
        self.assertEqual(plan["cost"]["hourly_usd"], 2.0)
        self.assertEqual(plan["cost"]["daily_usd"], 48.0)
        self.assertEqual(plan["cost"]["monthly_30d_usd"], 1440.0)
        self.assertEqual(plan["cost"]["idle_teardown_hours"], 0.5)
        self.assertEqual(plan["cost"]["idle_window_cost_usd"], 1.0)
        self.assertEqual(plan["serverless_comparison"]["break_even_daily_serverless_usd"], 48.0)
        self.assertEqual(plan["serverless_comparison"]["delta_daily_usd"], -32.0)
        self.assertTrue(plan["serverless_comparison"]["dedicated_cheaper"])
        self.assertFalse(plan["capacity"]["uncertain"])
        self.assertTrue(plan["capacity"]["accelerator_seen"])
        self.assertTrue(plan["capacity"]["model_seen"])
        self.assertEqual(calls, [
            ("/v2/dedicated-inferences/sizes", "GET"),
            ("/v2/dedicated-inferences/gpu-model-config", "GET"),
        ])

    def test_capacity_plan_surfaces_missing_price_and_capacity_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(
                tmp,
                token="",
                local_usage_report=lambda start, end: {"total_usd": 12.5},
            )
            plan = service.capacity_plan(dict(
                self.critical_build_data(),
                region="sfo3",
                price_per_hour=0,
                projected_serverless_daily_usd="",
            ))

        self.assertEqual(plan["recommendation"], "blocked")
        self.assertEqual(plan["cost"]["daily_usd"], 0.0)
        self.assertEqual(plan["serverless_comparison"]["projected_daily_usd"], 12.5)
        self.assertTrue(plan["capacity"]["uncertain"])
        self.assertFalse(plan["capacity"]["region_known"])
        notes = " ".join(plan["uncertainty_notes"])
        self.assertIn("hourly price is missing", notes)
        self.assertIn("Live capacity", notes)
        self.assertIn("Region is outside", notes)
        self.assertFalse(plan["readiness"]["preflight"]["ok"])

    def test_budget_blocked_chat_routes_to_serverless_with_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.seed_one_hour_dedicated_runtime(tmp)
            service, _ = self.service(tmp, now=10000)
            cfg = dict(
                DEFAULT_CONFIG,
                state="active",
                public_endpoint_fqdn="ready.example.com",
                access_token="runtime-token",
                price_per_hour=10,
                daily_budget_usd=10,
                warning_threshold=0.7,
                cooldown_threshold=0.9,
            )

            status, payload = service.chat_completion({"model": "qwen-dedicated", "messages": []}, cfg)
            event = next(item for item in service.events() if item["state"] == "budget_blocked_fallback")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload["text"], "fallback")
        self.assertIn("over the configured daily budget", payload["notice"])
        self.assertEqual(payload["routing"]["reason"], "budget_blocked_fallback")
        self.assertEqual(payload["routing"]["used"], "serverless-a")
        self.assertEqual(event["details"]["fallback_model"], "serverless-a")

    def test_idle_policy_warns_once_after_idle_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=1401)
            service.save_config(dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-1",
                run_started_at=1000,
                last_work_at=1000,
                idle_warning_seconds=300,
                idle_teardown_seconds=600,
            ))

            result = service.enforce_policy()
            second = service.enforce_policy()
            cfg = service.load_config()
            events = [event for event in service.events() if event["state"] == "idle_warning"]

        self.assertEqual(result["action"], "warning")
        self.assertEqual(second["action"], "none")
        self.assertEqual(cfg["idle_warning_started_at"], 1401)
        self.assertEqual(len(events), 1)
        self.assertEqual(result["idle_policy"]["teardown_countdown_seconds"], 199)

    def test_idle_policy_auto_tears_down_after_teardown_threshold(self):
        calls = []

        def do_request(path, token, payload=None, timeout=60, method="GET"):
            calls.append((path, method))
            return 202, {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            service, registry = self.service(tmp, now=1701, do_request=do_request)
            registry.append({"id": "dedicated-inference", "enabled": True, "type": "text"})
            service.save_config(dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-1",
                run_started_at=1000,
                last_work_at=1000,
                idle_warning_seconds=300,
                idle_teardown_seconds=600,
            ))

            result = service.enforce_policy()
            cfg = service.load_config()
            events = service.events()

        self.assertEqual(result["action"], "teardown")
        self.assertEqual(result["reason"], "idle_timeout")
        self.assertEqual(cfg["state"], "deleted")
        self.assertFalse(registry)
        self.assertIn(("/v2/dedicated-inferences/server-1", "DELETE"), calls)
        self.assertTrue(any(event["state"] == "idle_teardown" for event in events))

    def test_keep_alive_extends_idle_countdown_for_allowed_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=1401)
            service.save_config(dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-1",
                run_started_at=1000,
                last_work_at=1000,
                idle_warning_seconds=300,
                idle_teardown_seconds=600,
            ))

            status, payload = service.keep_alive({"seconds": 600, "operator": "console-token:abc"})
            cfg = service.load_config()
            policy = payload["dedicated"]["idle_policy"]
            event = next(item for item in service.events() if item["state"] == "keep_alive")

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(cfg["keep_alive_started_at"], 1401)
        self.assertEqual(cfg["keep_alive_until"], 2001)
        self.assertTrue(policy["extension_active_unused"])
        self.assertEqual(policy["teardown_countdown_seconds"], 600)
        self.assertEqual(event["details"]["operator"], "console-token:abc")

    def test_keep_alive_rejects_invalid_duration_and_inactive_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=1401)

            bad_status, bad_payload = service.keep_alive({"seconds": 120})
            inactive_status, inactive_payload = service.keep_alive({"seconds": 300})

        self.assertEqual(bad_status, HTTPStatus.BAD_REQUEST)
        self.assertIn("300, 600, 1800, or 3600", bad_payload["error"])
        self.assertEqual(inactive_status, HTTPStatus.CONFLICT)
        self.assertIn("only available", inactive_payload["error"])

    def test_unused_keep_alive_extension_tears_down_when_it_expires(self):
        calls = []

        def do_request(path, token, payload=None, timeout=60, method="GET"):
            calls.append((path, method))
            return 202, {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=2002, do_request=do_request)
            service.save_config(dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-1",
                run_started_at=1000,
                last_work_at=1000,
                idle_warning_seconds=300,
                idle_teardown_seconds=600,
                keep_alive_started_at=1401,
                keep_alive_until=2001,
            ))

            result = service.enforce_policy()

        self.assertEqual(result["action"], "teardown")
        self.assertEqual(result["reason"], "keep_alive_extension_expired")
        self.assertIn(("/v2/dedicated-inferences/server-1", "DELETE"), calls)

    def test_archive_old_events_compresses_lifecycle_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dedicated-events.jsonl"
            old = {"ts": 1000, "state": "deleted", "message": "old"}
            recent = {"ts": 199999, "state": "active", "message": "recent"}
            path.write_text(json.dumps(old) + "\n" + json.dumps(recent) + "\n", encoding="utf-8")
            service, _ = self.service(tmp, now=200000)

            result = service.archive_old_events(retention_days=1)
            remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            with gzip.open(result["archive_file"], "rt", encoding="utf-8") as f:
                archived = [json.loads(line) for line in f.read().splitlines()]

        self.assertEqual(result["archived"], 1)
        self.assertTrue(result["archive_file"].endswith(".jsonl.gz"))
        self.assertEqual(remaining[0]["message"], "recent")
        self.assertEqual(remaining[1]["state"], "archive")
        self.assertEqual(archived, [old])

    def test_repeated_status_failures_start_unhealthy_countdown(self):
        def do_request(path, token, payload=None, timeout=60, method="GET"):
            return 503, {"message": "endpoint unhealthy"}

        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=1000, do_request=do_request)
            service.save_config(dict(DEFAULT_CONFIG, state="active", inference_id="server-1"))

            service.status_payload(poll=True)
            service.status_payload(poll=True)
            payload = service.status_payload(poll=True)
            cfg = service.load_config()
            event = next(item for item in service.events() if item["state"] == "unhealthy")

        self.assertEqual(cfg["unhealthy_failed_checks"], 3)
        self.assertEqual(cfg["unhealthy_started_at"], 1000)
        self.assertTrue(payload["dedicated"]["unhealthy_policy"]["unhealthy"])
        self.assertEqual(event["details"]["failed_checks"], 3)

    def test_unhealthy_dedicated_chat_fails_fast_with_fallback_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=1100)
            cfg = dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-1",
                public_endpoint_fqdn="ready.example.com",
                access_token="runtime-token",
                unhealthy_failed_checks=3,
                unhealthy_started_at=1000,
            )

            status, payload = service.chat_completion({"model": "dedicated-inference", "messages": []}, cfg)

        self.assertEqual(status, HTTPStatus.SERVICE_UNAVAILABLE)
        self.assertIn("marked unhealthy", payload["message"])
        self.assertEqual(payload["routing"]["reason"], "dedicated_unhealthy")
        self.assertEqual(payload["routing"]["fallback_model"], "serverless-a")

    def test_unhealthy_policy_auto_tears_down_after_countdown(self):
        calls = []

        def do_request(path, token, payload=None, timeout=60, method="GET"):
            calls.append((path, method))
            return 202, {"ok": True}

        with tempfile.TemporaryDirectory() as tmp:
            service, _ = self.service(tmp, now=1301, do_request=do_request)
            service.save_config(dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-1",
                unhealthy_failed_checks=3,
                unhealthy_started_at=1000,
                unhealthy_teardown_seconds=300,
            ))

            result = service.enforce_policy()

        self.assertEqual(result["action"], "teardown")
        self.assertEqual(result["reason"], "unhealthy_timeout")
        self.assertIn(("/v2/dedicated-inferences/server-1", "DELETE"), calls)

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
        self.assertEqual(entry["pricing"]["hourly"], 2.59)
        self.assertTrue(entry["dedicated"]["managed"])
        self.assertEqual(entry["dedicated"]["state"], "active")
        # ADR-0005: live identifiers never reach the git-tracked registry entry.
        self.assertNotIn("endpoint", entry)
        self.assertNotIn("inference_id", entry)
        self.assertNotIn("server_id", entry["dedicated"])
        self.assertNotIn("endpoint", entry["dedicated"])
        self.assertNotIn("server-1", json.dumps(registry))
        self.assertNotIn("ready.example.com", json.dumps(registry))

    def test_registry_entry_omits_identifiers_that_stay_in_runtime_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, registry = self.service(tmp)
            cfg = service.save_config(dict(
                DEFAULT_CONFIG,
                state="active",
                inference_id="server-9",
                public_endpoint_fqdn="live.example.com",
                private_endpoint_fqdn="private.example.internal",
                access_token="secret-token",
                price_per_hour=2.0,
            ))
            service.register_model(cfg)
            registry_text = json.dumps(registry)
            runtime_text = (Path(tmp) / "dedicated.json").read_text(encoding="utf-8")
            runtime_cfg = service.load_config()

        for sensitive in ("server-9", "live.example.com", "private.example.internal", "secret-token"):
            self.assertNotIn(sensitive, registry_text)
        # Readers resolve the identifiers from runtime state, not the registry.
        self.assertIn("server-9", runtime_text)
        self.assertEqual(runtime_cfg["inference_id"], "server-9")
        self.assertEqual(service.endpoint(runtime_cfg), "https://live.example.com")

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
        # The registry entry keeps only non-sensitive routing facts; the live
        # server id stays in the runtime config (ADR-0005).
        self.assertTrue(registry[0]["dedicated"]["managed"])
        self.assertEqual(registry[0]["dedicated"]["state"], "active")
        self.assertNotIn("server_id", registry[0]["dedicated"])
        self.assertNotIn("server-1", json.dumps(registry))
        self.assertEqual(cfg["inference_id"], "server-1")
        self.assertTrue(any(call[0].endswith("/tokens") for call in calls))


if __name__ == "__main__":
    unittest.main()
