import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from src.console.services.model_registry import ModelRegistryService
from src.console.services.serverless_catalog import ServerlessCatalogService


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ServerlessCatalogServiceTests(unittest.TestCase):
    def service(self, tmp, **overrides):
        root = Path(tmp)
        registry_service = ModelRegistryService([], {"text", "image", "embedding", "rerank", "unknown"}, 0.45)
        state = {
            "models": [],
            "refreshes": 0,
            "proxy_syncs": [],
            "options": [],
        }

        def access_state():
            path = root / "model-access-state.json"
            if not path.exists():
                return {"schema_version": 1, "models": {}}
            return json.loads(path.read_text(encoding="utf-8"))

        def load_model_registry(include_disabled=True):
            rows = [dict(item) for item in state["models"]]
            rows = registry_service.apply_access_state(rows, access_state())
            if include_disabled:
                return rows
            return [item for item in rows if registry_service.route_enabled(item)]

        def save_model_registry(models):
            state["models"] = [dict(item) for item in models]
            return [dict(item) for item in state["models"]]

        kwargs = {
            "env": {},
            "token_file": lambda: root / "token",
            "home_dir": lambda: root,
            "script_dir": lambda: root / "app",
            "embedded_access_key": "embedded-token",
            "catalog_cache_file": lambda: root / "catalog.json",
            "catalog_ttl_seconds": 60,
            "model_enabled_by_default": registry_service.enabled_by_default,
            "catalog_pricing_from_item": registry_service.catalog_pricing_from_item,
            "serverless_model_type": registry_service.serverless_model_type,
            "display_name_from_model_id": registry_service.display_name_from_model_id,
            "model_types": {"text", "image", "embedding", "rerank", "unknown"},
            "documented_pricing": {"cheap": {"input": 0.10, "output": 0.40}, "expensive": {"input": 0.10, "output": 0.50}},
            "load_model_registry": load_model_registry,
            "save_model_registry": save_model_registry,
            "refresh_model_globals": lambda: state.__setitem__("refreshes", state["refreshes"] + 1),
            "proxy_sync_payload": lambda force=False: state["proxy_syncs"].append(force) or {"in_sync": True},
            "model_options": lambda model_type=None, include_disabled=True: state["options"],
            "model_metadata_map": lambda: {"metadata": True},
            "active_text_models": lambda: [item["id"] for item in load_model_registry(False) if item.get("type") == "text"],
            "auto_enable_max_usd": 0.45,
            "urlopen_func": lambda req, timeout=0: FakeResponse(200, {"data": []}),
            "clock": lambda: 1000,
            "model_access_state_file": lambda: root / "model-access-state.json",
        }
        kwargs.update(overrides)
        return ServerlessCatalogService(**kwargs), state, root

    def test_key_candidates_prefer_environment_then_files_then_embedded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "token").write_text("file-token", encoding="utf-8")
            service, _, _ = self.service(tmp, env={"MODEL_ACCESS_KEY": "env-token"})
            candidates = service.model_access_key_candidates()
            info = service.active_model_access_key_info()

        self.assertEqual(candidates[0]["source"], "env:MODEL_ACCESS_KEY")
        self.assertEqual(candidates[0]["token"], "env-token")
        self.assertTrue(info["configured"])
        self.assertEqual(info["masked"], "***")

    def test_fetch_catalog_and_probe_shape_runtime_requests(self):
        seen = []

        def urlopen_func(req, timeout=0):
            seen.append((req.full_url, req.get_method(), req.get_header("Authorization"), req.data, timeout))
            return FakeResponse(200, {"data": [{"id": "model-a"}]})

        with tempfile.TemporaryDirectory() as tmp:
            service, _, _ = self.service(tmp, env={"MODEL_ACCESS_KEY": "token-123"}, urlopen_func=urlopen_func)
            catalog = service.fetch_serverless_catalog()
            ok, status, detail = service.probe_serverless_text_model("model-a")

        self.assertEqual(catalog["data"][0]["id"], "model-a")
        self.assertTrue(ok)
        self.assertEqual(status, 200)
        self.assertEqual(detail, "")
        self.assertEqual(seen[0][0], "https://inference.do-ai.run/v1/models")
        self.assertEqual(seen[0][1], "GET")
        self.assertEqual(seen[1][0], "https://inference.do-ai.run/v1/chat/completions")
        self.assertEqual(seen[1][1], "POST")
        self.assertIn(b'"model": "model-a"', seen[1][3])

    def test_probe_reports_http_and_network_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            denied = self.service(
                tmp,
                urlopen_func=lambda req, timeout=0: (_ for _ in ()).throw(
                    HTTPError(req.full_url, 403, "forbidden", {}, io.BytesIO(b"no access"))
                ),
            )[0]
            denied_result = denied.probe_serverless_text_model("model-a")

            offline = self.service(
                tmp,
                urlopen_func=lambda req, timeout=0: (_ for _ in ()).throw(URLError("offline")),
            )[0]
            offline_result = offline.probe_serverless_text_model("model-a")

        self.assertEqual(denied_result, (False, 403, "no access"))
        self.assertEqual(offline_result, (False, 502, "offline"))

    def test_catalog_payload_uses_cache_and_falls_back_to_stale_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, root = self.service(tmp)
            cache = root / "catalog.json"
            cache.write_text(json.dumps({"ok": True, "fetched_at": 999, "source": "cache", "payload": {"data": [{"id": "cached"}]}, "error": ""}), encoding="utf-8")
            cached = service.serverless_catalog_payload(force=False)

            cache.write_text(json.dumps({"ok": True, "fetched_at": 1, "source": "old", "payload": {"data": [{"id": "stale"}]}, "error": ""}), encoding="utf-8")
            failing = self.service(tmp, fetch_serverless_catalog=lambda: (_ for _ in ()).throw(RuntimeError("network down")))[0]
            fallback = failing.serverless_catalog_payload(force=True)

        self.assertEqual(cached["payload"]["data"][0]["id"], "cached")
        self.assertFalse(fallback["ok"])
        self.assertEqual(fallback["source"], "cache_after_fetch_error")
        self.assertIn("network down", fallback["error"])

    def test_registry_entry_pricing_priority_and_access_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _ = self.service(
                tmp,
                probe_serverless_text_model=lambda model_id: (model_id == "cheap", 200 if model_id == "cheap" else 403, "denied"),
            )
            catalog_priced = service.serverless_registry_entry({"id": "cheap", "pricing": {"input": 0.01, "output": 0.02}})
            documented = service.serverless_registry_entry({"id": "expensive"})
            models = [catalog_priced, documented]
            result = service.validate_serverless_access(models)

        self.assertEqual(catalog_priced["pricing_source"], "digitalocean_catalog")
        self.assertEqual(documented["pricing_source"], "digitalocean_pricing_docs_2026_07_01")
        self.assertEqual(result, {"checked": 2, "disabled": 1})
        self.assertEqual(models[0]["access_status"], "ok")
        self.assertEqual(models[1]["access_status"], "forbidden")
        self.assertFalse(models[1]["enabled"])

    def test_probe_error_category_maps_status_and_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, _, _ = self.service(tmp)
            raw_body = '{"error": "Key sk-do-8f3e is not entitled to model", "request_id": "req-abc123"}'
            cases = [
                ((True, 200, ""), ""),
                ((False, 401, raw_body), "http_401_unauthorized"),
                ((False, 403, raw_body), "http_403_forbidden"),
                ((False, 429, raw_body), "http_429_rate_limited"),
                ((False, 502, "The read operation timed out"), "timeout"),
                ((False, 502, "<urlopen error [Errno 111] Connection refused>"), "connection_error"),
                ((False, 502, "offline"), "connection_error"),
                ((False, 500, "<html>Internal Server Error</html>"), "http_5xx"),
                ((False, 404, "no such model"), "http_4xx"),
                ((False, 0, "unparseable garbage"), "invalid_response"),
            ]
            for (ok, status, detail), expected in cases:
                category = service.probe_error_category(ok, status, detail)
                self.assertEqual(category, expected, msg=repr((ok, status, detail)))
                self.assertLessEqual(len(category), 64)
                self.assertNotIn("sk-do-8f3e", category)

    def test_audit_redacts_probe_bodies_into_categories_and_logs_forensics(self):
        catalog_holder = {"payload": {"ok": False, "payload": {"data": []}, "error": "skip"}}
        raw_bodies = {
            "forbidden": '{"error": "Key sk-do-8f3e cannot access this model", "request_id": "req-abc123"}',
            "rate": '{"error": "slow down please", "request_id": "req-999"}',
            "offline": "<urlopen error [Errno 111] Connection refused>",
            "slow": "The read operation timed out",
        }

        def probe(model_id):
            if model_id == "forbidden":
                return False, 403, raw_bodies["forbidden"]
            if model_id == "rate":
                return False, 429, raw_bodies["rate"]
            if model_id == "offline":
                return False, 502, raw_bodies["offline"]
            if model_id == "slow":
                return False, 502, raw_bodies["slow"]
            return True, 200, ""

        with tempfile.TemporaryDirectory() as tmp:
            service, state, root = self.service(
                tmp,
                env={"MODEL_ACCESS_KEY": "stable-token"},
                serverless_catalog_payload=lambda force=False: catalog_holder["payload"],
                probe_serverless_text_model=probe,
            )
            state["models"] = [
                {"id": model_id, "type": "text", "enabled": True, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}}
                for model_id in ("forbidden", "rate", "offline", "slow", "allowed")
            ]
            payload = service.audit_model_access_key()
            access_state_text = (root / "model-access-state.json").read_text(encoding="utf-8")
            drift_text = (root / "model-access-drift.json").read_text(encoding="utf-8")
            access_models = json.loads(access_state_text)["models"]
            probe_log = root / "model-access-probes.jsonl"
            probe_rows = [json.loads(line) for line in probe_log.read_text(encoding="utf-8").splitlines()]
            consumer_text = json.dumps(state["models"]) + json.dumps(payload["blocked"]) + json.dumps(payload["skipped"])

        # Everywhere a probe outcome is persisted, last_error is a short category.
        self.assertEqual(access_models["forbidden"]["last_error"], "http_403_forbidden")
        self.assertEqual(access_models["rate"]["last_error"], "http_429_rate_limited")
        self.assertEqual(access_models["offline"]["last_error"], "connection_error")
        self.assertEqual(access_models["slow"]["last_error"], "timeout")
        self.assertEqual(access_models["allowed"]["last_error"], "")
        for record in access_models.values():
            self.assertLessEqual(len(record["last_error"]), 64)
        # No raw body substring reaches access state, drift state, or the rows
        # registry consumers see; forensics live only in the runtime probe log.
        for raw in ("sk-do-8f3e", "req-abc123", "req-999", "slow down", "Connection refused", "timed out"):
            self.assertNotIn(raw, access_state_text)
            self.assertNotIn(raw, drift_text)
            self.assertNotIn(raw, consumer_text)
        self.assertEqual(payload["probe_log_file"], str(probe_log))
        self.assertEqual(len(probe_rows), 5)
        by_model = {row["model_id"]: row for row in probe_rows}
        self.assertEqual(by_model["forbidden"]["detail"], raw_bodies["forbidden"])
        self.assertEqual(by_model["forbidden"]["status"], 403)
        self.assertEqual(by_model["forbidden"]["category"], "http_403_forbidden")
        self.assertEqual(by_model["forbidden"]["source"], "audit")
        self.assertEqual(by_model["slow"]["detail"], raw_bodies["slow"])
        self.assertTrue(by_model["allowed"]["ok"])
        self.assertTrue(all(row["ts"] == 1000.0 for row in probe_rows))
        self.assertTrue(all(row["key_fingerprint"] for row in probe_rows))

    def test_validate_access_writes_categories_and_catalog_sync_probe_log(self):
        raw_body = '{"error": "denied", "request_id": "req-777"}'
        with tempfile.TemporaryDirectory() as tmp:
            service, _, root = self.service(
                tmp,
                probe_serverless_text_model=lambda model_id: (model_id == "cheap", 200 if model_id == "cheap" else 403, "" if model_id == "cheap" else raw_body),
            )
            models = [
                service.serverless_registry_entry({"id": "cheap", "pricing": {"input": 0.01, "output": 0.02}}),
                service.serverless_registry_entry({"id": "expensive"}),
            ]
            service.validate_serverless_access(models)
            probe_rows = [json.loads(line) for line in (root / "model-access-probes.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(models[1]["last_error"], "http_403_forbidden")
        self.assertNotIn("req-777", json.dumps(models))
        self.assertEqual([row["source"] for row in probe_rows], ["catalog_sync", "catalog_sync"])
        self.assertEqual(probe_rows[1]["detail"], raw_body)
        self.assertEqual(probe_rows[1]["category"], "http_403_forbidden")

    def test_sync_catalog_adds_removes_preserves_dedicated_and_refreshes(self):
        catalog = {
            "ok": True,
            "source": "test",
            "fetched_at": 1000,
            "payload": {"data": [{"id": "cheap"}, {"id": "new-model", "pricing": {"input": 0.1, "output": 0.2}}]},
            "error": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            service, state, _ = self.service(tmp, serverless_catalog_payload=lambda force=False: catalog)
            state["models"] = [
                {"id": "cheap", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "removed", "type": "text", "enabled": True, "serverless": True, "access_status": "ok", "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "dedicated", "type": "text", "enabled": False, "dedicated": {"managed": True}, "pricing": {"hourly": 2.59}},
            ]
            result = service.sync_serverless_model_catalog(force=True, validate_access=False)
            by_id = {model["id"]: model for model in state["models"]}

        self.assertTrue(result["ok"])
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["removed"], 1)
        self.assertIn("new-model", by_id)
        self.assertEqual(by_id["removed"]["access_status"], "removed")
        self.assertIn("dedicated", by_id)
        self.assertEqual(state["refreshes"], 1)

    def test_sync_does_not_churn_registry_when_catalog_is_unchanged(self):
        catalog = {
            "ok": True,
            "source": "test",
            "fetched_at": 1000,
            "payload": {"data": [{"id": "cheap", "pricing": {"input": 0.1, "output": 0.2}}]},
            "error": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            service, state, _ = self.service(tmp, serverless_catalog_payload=lambda force=False: catalog)
            # First sync populates and persists.
            service.sync_serverless_model_catalog(force=True, validate_access=False)
            baseline_refreshes = state["refreshes"]
            self.assertGreaterEqual(baseline_refreshes, 1)
            # A second identical sync (the passive GET /api/models path) must change
            # nothing and must NOT rewrite the registry or refresh globals again.
            result = service.sync_serverless_model_catalog(force=True, validate_access=False)

        self.assertEqual((result["added"], result["updated"], result["removed"]), (0, 0, 0))
        self.assertEqual(state["refreshes"], baseline_refreshes)

    def test_audit_updates_access_and_syncs_proxy(self):
        catalog_holder = {"payload": {"ok": False, "payload": {"data": []}, "error": "skip"}}
        with tempfile.TemporaryDirectory() as tmp:
            service, state, root = self.service(
                tmp,
                serverless_catalog_payload=lambda force=False: catalog_holder["payload"],
                probe_serverless_text_model=lambda model_id: (model_id == "allowed", 200 if model_id == "allowed" else 403, "denied"),
            )
            state["models"] = [
                {"id": "allowed", "display_name": "Allowed", "type": "text", "enabled": False, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "blocked", "display_name": "Blocked", "type": "text", "enabled": True, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "image", "type": "image", "enabled": True, "pricing": {"image": 0.08}},
            ]
            payload = service.audit_model_access_key()
            access_state = json.loads((root / "model-access-state.json").read_text(encoding="utf-8"))["models"]

        self.assertEqual(payload["checked"], 2)
        self.assertEqual(payload["allowed_count"], 1)
        self.assertEqual(payload["blocked_count"], 1)
        self.assertEqual(access_state["allowed"]["access_status"], "ok")
        self.assertEqual(access_state["blocked"]["access_status"], "forbidden")
        self.assertNotIn("access_status", state["models"][0])
        self.assertTrue(next(model for model in state["models"] if model["id"] == "blocked")["enabled"])
        self.assertEqual(state["proxy_syncs"], [True])

    def test_access_drift_tracks_regressions_removed_repeated_failures_and_restore(self):
        catalog_holder = {"payload": {"ok": False, "payload": {"data": []}, "error": "skip"}}
        mode = {"value": "ok"}

        def probe(model_id):
            if mode["value"] == "ok" or (mode["value"] == "restore" and model_id != "removed"):
                return True, 200, ""
            if model_id == "forbidden":
                return False, 403, "denied"
            if model_id == "rate":
                return False, 429, "limited"
            if model_id == "probe":
                return False, 502, "offline"
            return True, 200, ""

        with tempfile.TemporaryDirectory() as tmp:
            service, state, root = self.service(
                tmp,
                env={"MODEL_ACCESS_KEY": "stable-token"},
                serverless_catalog_payload=lambda force=False: catalog_holder["payload"],
                probe_serverless_text_model=probe,
            )
            state["models"] = [
                {"id": "forbidden", "type": "text", "enabled": True, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "rate", "type": "text", "enabled": True, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "probe", "type": "text", "enabled": True, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
                {"id": "removed", "type": "text", "enabled": True, "serverless": True, "pricing": {"input": 0.1, "output": 0.2}},
            ]
            first = service.audit_model_access_key()
            mode["value"] = "bad"
            second = service.audit_model_access_key()
            repeated = service.audit_model_access_key()
            catalog_holder["payload"] = {"ok": True, "source": "test", "fetched_at": 1000, "payload": {"data": [{"id": "forbidden"}, {"id": "rate"}, {"id": "probe"}]}, "error": ""}
            service.sync_serverless_model_catalog(force=True, validate_access=False)
            mode["value"] = "restore"
            restored = service.audit_model_access_key()
            drift_state = json.loads((root / "model-access-drift.json").read_text(encoding="utf-8"))
            access_state = json.loads((root / "model-access-state.json").read_text(encoding="utf-8"))["models"]

        self.assertEqual(first["access_drift"]["events"], [])
        statuses = {event["access_status"] for event in second["access_drift"]["events"]}
        self.assertTrue({"forbidden", "rate_limited", "probe_failed"}.issubset(statuses))
        self.assertEqual(access_state["forbidden"]["access_status"], "ok")
        self.assertTrue(any(event["code"] == "repeated_probe_failure" for event in repeated["access_drift"]["events"]))
        self.assertTrue(any(event["access_status"] == "removed" for event in drift_state["events"].values()))
        self.assertTrue(any(event["code"] == "restored" for event in restored["access_drift"]["events"]))
        self.assertTrue(drift_state["models"]["forbidden"]["last_ok_at"])


if __name__ == "__main__":
    unittest.main()
