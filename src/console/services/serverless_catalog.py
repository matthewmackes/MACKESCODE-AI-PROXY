"""DigitalOcean Serverless model catalog and access-audit helpers."""
import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ServerlessCatalogService:
    """Owns Serverless model catalog sync and model-access key probing."""

    def __init__(
        self,
        *,
        env,
        token_file,
        home_dir,
        script_dir,
        embedded_access_key,
        catalog_cache_file,
        catalog_ttl_seconds,
        model_enabled_by_default,
        catalog_pricing_from_item,
        serverless_model_type,
        display_name_from_model_id,
        model_types,
        documented_pricing,
        load_model_registry,
        save_model_registry,
        refresh_model_globals,
        proxy_sync_payload,
        model_options,
        model_metadata_map,
        active_text_models,
        auto_enable_max_usd,
        urlopen_func=None,
        clock=None,
        read_model_access_token=None,
        fetch_serverless_catalog=None,
        serverless_catalog_payload=None,
        probe_serverless_text_model=None,
        model_access_drift_file=None,
        model_access_state_file=None,
        append_audit=None,
    ):
        self.env = env
        self.token_file = token_file
        self.home_dir = home_dir
        self.script_dir = script_dir
        self.embedded_access_key = embedded_access_key
        self.catalog_cache_file = catalog_cache_file
        self.catalog_ttl_seconds = int(catalog_ttl_seconds)
        self.model_enabled_by_default = model_enabled_by_default
        self.catalog_pricing_from_item = catalog_pricing_from_item
        self.serverless_model_type = serverless_model_type
        self.display_name_from_model_id = display_name_from_model_id
        self.model_types = set(model_types)
        self.documented_pricing = documented_pricing
        self.load_model_registry = load_model_registry
        self.save_model_registry = save_model_registry
        self.refresh_model_globals = refresh_model_globals
        self.proxy_sync_payload = proxy_sync_payload
        self.model_options = model_options
        self.model_metadata_map = model_metadata_map
        self.active_text_models = active_text_models
        self.auto_enable_max_usd = auto_enable_max_usd
        self.urlopen = urlopen_func or urlopen
        self.clock = clock or time.time
        self.read_model_access_token_func = read_model_access_token
        self.fetch_serverless_catalog_func = fetch_serverless_catalog
        self.serverless_catalog_payload_func = serverless_catalog_payload
        self.probe_serverless_text_model_func = probe_serverless_text_model
        self.model_access_drift_file = model_access_drift_file
        self.model_access_state_file = model_access_state_file
        self.append_audit = append_audit or (lambda *args, **kwargs: None)

    def model_access_drift_path(self):
        if self.model_access_drift_file:
            path = self.model_access_drift_file()
        else:
            path = self.catalog_cache_file().parent / "model-access-drift.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def default_access_drift_state(self):
        return {"schema_version": 1, "models": {}, "events": {}}

    def model_access_state_path(self):
        if self.model_access_state_file:
            path = self.model_access_state_file()
        else:
            path = self.catalog_cache_file().parent / "model-access-state.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def default_access_state(self):
        return {"schema_version": 1, "updated_at": 0, "models": {}}

    def load_access_state(self):
        path = self.model_access_state_path()
        if not path.exists():
            return self.default_access_state()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.default_access_state()
        if not isinstance(data, dict):
            return self.default_access_state()
        return {
            "schema_version": 1,
            "updated_at": data.get("updated_at", 0),
            "models": data.get("models") if isinstance(data.get("models"), dict) else {},
        }

    def save_access_state(self, models, updated_at=None):
        path = self.model_access_state_path()
        payload = {
            "schema_version": 1,
            "updated_at": float(updated_at if updated_at is not None else self.clock()),
            "models": models if isinstance(models, dict) else {},
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return payload

    def load_access_drift_state(self):
        path = self.model_access_drift_path()
        if not path.exists():
            return self.default_access_drift_state()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.default_access_drift_state()
        return {
            "schema_version": 1,
            "models": data.get("models") if isinstance(data.get("models"), dict) else {},
            "events": data.get("events") if isinstance(data.get("events"), dict) else {},
        }

    def save_access_drift_state(self, state):
        path = self.model_access_drift_path()
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return state

    def access_drift_payload(self):
        state = self.load_access_drift_state()
        events = [event for event in (state.get("events") or {}).values() if not event.get("acknowledged_at")]
        events.sort(key=lambda event: (float(event.get("created_at") or 0), event.get("id") or ""), reverse=True)
        return {"state_file": str(self.model_access_drift_path()), "events": events, "active_count": len(events), "models": state.get("models") or {}}

    def acknowledge_access_drift(self, data, actor=None):
        data = data if isinstance(data, dict) else {}
        state = self.load_access_drift_state()
        events = state.get("events") if isinstance(state.get("events"), dict) else {}
        ids = data.get("ids") if isinstance(data.get("ids"), list) else []
        if not ids:
            ids = [event_id for event_id, event in events.items() if not event.get("acknowledged_at")]
        now = float(self.clock())
        acknowledged = []
        for event_id in ids:
            event = events.get(str(event_id))
            if not isinstance(event, dict):
                continue
            event["acknowledged_at"] = now
            event["acknowledged_by"] = actor if isinstance(actor, dict) else {}
            acknowledged.append(event_id)
        self.save_access_drift_state(state)
        self.append_audit("model_access_drift.acknowledge", actor=actor or {}, outcome="completed", permission="model_access.audit", request={"ids": acknowledged}, status=200)
        payload = self.access_drift_payload()
        payload["acknowledged"] = acknowledged
        return payload

    def access_status_from_probe(self, ok, status):
        if ok:
            return "ok"
        return "forbidden" if int(status) in {401, 403} else ("rate_limited" if int(status) == 429 else "probe_failed")

    def record_access_drift(self, outcomes, source="audit"):
        if not outcomes:
            return {"events": [], "active_count": self.access_drift_payload()["active_count"], "state_file": str(self.model_access_drift_path())}
        state = self.load_access_drift_state()
        models = state.setdefault("models", {})
        events = state.setdefault("events", {})
        key = self.active_model_access_key_info()
        now = float(self.clock())
        new_events = []
        bad_statuses = {"forbidden", "rate_limited", "probe_failed", "removed", "unauthorized"}
        for outcome in outcomes:
            model_id = str(outcome.get("id") or "")
            if not model_id:
                continue
            current = str(outcome.get("access_status") or "unknown")
            previous = models.get(model_id) if isinstance(models.get(model_id), dict) else {}
            previous_status = str(previous.get("access_status") or "")
            same_key = not previous.get("key_fingerprint") or previous.get("key_fingerprint") == key.get("fingerprint")
            previous_good = previous_status == "ok" or float(previous.get("last_ok_at") or 0) > 0
            failure_count = 0 if current == "ok" else int(previous.get("failure_count") or 0) + 1
            event = None
            if current == "ok" and previous_status in bad_statuses and same_key:
                event = self.access_drift_event("restored", "low", outcome, previous, "Model access restored", source, now, key, failure_count)
            elif current == "removed" and previous_good:
                event = self.access_drift_event("removed", "high", outcome, previous, "Model removed from provider catalog", source, now, key, failure_count)
            elif current in {"forbidden", "rate_limited", "probe_failed"} and previous_good and same_key:
                code = "repeated_probe_failure" if current == "probe_failed" and failure_count >= 2 else "access_regression"
                severity = "high" if current == "forbidden" else "medium"
                event = self.access_drift_event(code, severity, outcome, previous, "Model access regressed to %s" % current, source, now, key, failure_count)
            record = {
                "id": model_id,
                "display_name": outcome.get("display_name") or previous.get("display_name") or model_id,
                "access_status": current,
                "http_status": int(outcome.get("status") or 0),
                "last_error": outcome.get("error") or "",
                "last_checked_at": now,
                "key_fingerprint": key.get("fingerprint") or "",
                "failure_count": failure_count,
                "last_ok_at": now if current == "ok" else float(previous.get("last_ok_at") or 0),
            }
            models[model_id] = record
            if event:
                existing = events.get(event["id"]) if isinstance(events.get(event["id"]), dict) else {}
                if existing.get("acknowledged_at"):
                    event["acknowledged_at"] = existing.get("acknowledged_at")
                    event["acknowledged_by"] = existing.get("acknowledged_by") or {}
                events[event["id"]] = event
                new_events.append(event)
                self.append_audit("model_access_drift.%s" % event["code"], actor={}, outcome="completed", permission="model_access.audit", request={"model": model_id, "access_status": current, "source": source}, status=200)
        self.save_access_drift_state(state)
        self.save_access_state(models, updated_at=now)
        active = [event for event in events.values() if not event.get("acknowledged_at")]
        return {"events": new_events, "active_count": len(active), "state_file": str(self.model_access_drift_path())}

    def access_drift_event(self, code, severity, outcome, previous, title, source, now, key, failure_count):
        model_id = str(outcome.get("id") or "")
        current = str(outcome.get("access_status") or "")
        event_id = "model_access_%s_%s_%s" % (code, model_id.replace("/", "-"), current)
        return {
            "id": event_id,
            "code": code,
            "severity": severity,
            "model_id": model_id,
            "display_name": outcome.get("display_name") or previous.get("display_name") or model_id,
            "title": title,
            "detail": outcome.get("error") or previous.get("last_error") or "",
            "previous_status": previous.get("access_status") or "",
            "access_status": current,
            "http_status": int(outcome.get("status") or 0),
            "failure_count": int(failure_count or 0),
            "key_fingerprint": key.get("fingerprint") or "",
            "source": source,
            "created_at": now,
            "acknowledged_at": None,
            "acknowledged_by": {},
        }

    def model_access_key_candidates(self):
        candidates = []
        for name in ("MODEL_ACCESS_KEY", "DIGITALOCEAN_MODEL_ACCESS_KEY", "MATTS_VALUE_SET_ACCESS_TOKEN"):
            value = self.env.get(name, "").strip()
            if value:
                candidates.append({"source": "env:%s" % name, "token": value, "path": ""})
        for path in (
            self.token_file(),
            self.home_dir() / ".mcnf-do-model-access-token",
            self.script_dir() / ".mcnf-do-model-access-token",
            Path("/root/.mcnf-do-model-access-token"),
        ):
            try:
                token = path.read_text(encoding="utf-8").strip()
                if token:
                    candidates.append({"source": "file:%s" % path, "token": token, "path": str(path)})
            except OSError:
                continue
        candidates.append({"source": "embedded:fallback", "token": self.embedded_access_key, "path": ""})
        return candidates

    def active_model_access_key_info(self):
        item = self.model_access_key_candidates()[0]
        token = item["token"]
        fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        masked = token[:6] + "..." + token[-4:] if len(token) > 12 else "***"
        return {
            "source": item["source"],
            "path": item.get("path") or "",
            "fingerprint": fingerprint,
            "masked": masked,
            "length": len(token),
            "configured": bool(token),
        }

    def read_model_access_token(self):
        if self.read_model_access_token_func:
            return self.read_model_access_token_func()
        return self.model_access_key_candidates()[0]["token"]

    def fetch_serverless_catalog(self):
        token = self.read_model_access_token()
        req = Request("https://inference.do-ai.run/v1/models", headers={
            "content-type": "application/json",
            "authorization": "Bearer " + token,
            "user-agent": "matts-console/1.0",
        }, method="GET")
        with self.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def serverless_catalog_payload(self, force=False):
        path = self.catalog_cache_file()
        if not force and path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if self.clock() - float(cached.get("fetched_at") or 0) < self.catalog_ttl_seconds:
                    return cached
            except (OSError, ValueError, TypeError):
                pass
        try:
            fetch = self.fetch_serverless_catalog_func or self.fetch_serverless_catalog
            payload = fetch()
            cached = {
                "ok": True,
                "fetched_at": self.clock(),
                "source": "https://inference.do-ai.run/v1/models",
                "payload": payload,
                "error": "",
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cached, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            path.chmod(0o600)
            return cached
        except Exception as exc:
            if path.exists():
                try:
                    cached = json.loads(path.read_text(encoding="utf-8"))
                    cached["ok"] = False
                    cached["error"] = str(exc)
                    cached["source"] = "cache_after_fetch_error"
                    return cached
                except (OSError, ValueError):
                    pass
            return {"ok": False, "fetched_at": 0, "source": "fallback", "payload": {"data": []}, "error": str(exc)}

    def serverless_registry_entry(self, item, existing=None):
        existing = existing or {}
        model_id = str(item.get("id") or "").strip()
        pricing = self.catalog_pricing_from_item(item)
        pricing_source = "digitalocean_catalog" if pricing else ""
        documented = self.documented_pricing() if callable(self.documented_pricing) else self.documented_pricing
        if not pricing:
            pricing = dict(documented.get(model_id) or {})
            pricing_source = "digitalocean_pricing_docs_2026_07_01" if pricing else ""
        if not pricing and isinstance(existing.get("pricing"), dict):
            pricing = dict(existing["pricing"])
            pricing_source = existing.get("pricing_source") or "existing_registry"
        model_type = self.serverless_model_type(model_id)
        auto_enabled = self.model_enabled_by_default(pricing)
        enabled = bool(existing.get("enabled")) if existing else auto_enabled
        return {
            "id": model_id,
            "display_name": existing.get("display_name") or self.display_name_from_model_id(model_id),
            "type": existing.get("type") if existing.get("type") in self.model_types else model_type,
            "provider": "DigitalOcean",
            "enabled": enabled,
            "aliases": existing.get("aliases") if isinstance(existing.get("aliases"), list) else [],
            "pricing": pricing,
            "context_window": int(item.get("context_length") or existing.get("context_window") or 0),
            "serverless": True,
            "owned_by": item.get("owned_by") or existing.get("owned_by") or "",
            "created": item.get("created") or existing.get("created") or 0,
            "max_output_tokens": item.get("max_output_tokens") or existing.get("max_output_tokens") or 0,
            "pricing_source": pricing_source or "unknown",
            # Preserve the flag across syncs; a catalog-managed model must not flip
            # to auto_managed=False on the next sync (that made the entry non-
            # idempotent and forced a registry rewrite on every poll). New catalog
            # entries default to auto_managed=True.
            "auto_managed": bool(existing.get("auto_managed", True)) if existing else True,
            "access_status": existing.get("access_status") or "not_checked",
            "last_error": existing.get("last_error") or "",
        }

    def probe_serverless_text_model(self, model_id):
        token = self.read_model_access_token()
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply only ok"}],
            "max_tokens": 2,
            "stream": False,
        }
        req = Request("https://inference.do-ai.run/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={
            "content-type": "application/json",
            "authorization": "Bearer " + token,
            "user-agent": "matts-console/1.0",
        }, method="POST")
        try:
            with self.urlopen(req, timeout=30) as resp:
                return True, resp.status, ""
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return False, exc.code, body[:1000]
        except URLError as exc:
            return False, 502, str(exc.reason)

    def validate_serverless_access(self, models):
        checked = 0
        disabled = 0
        outcomes = []
        probe = self.probe_serverless_text_model_func or self.probe_serverless_text_model
        for model in models:
            if not model.get("serverless") or model.get("type") != "text":
                continue
            checked += 1
            ok, status, detail = probe(model["id"])
            row = {
                "id": model["id"],
                "display_name": model.get("display_name") or model["id"],
                "owned_by": model.get("owned_by") or "",
                "pricing": model.get("pricing") or {},
                "status": int(status),
                "error": detail,
            }
            if ok:
                model["access_status"] = "ok"
                model["last_error"] = ""
                row["access_status"] = "ok"
                outcomes.append(row)
                continue
            model["access_status"] = "forbidden" if int(status) in {401, 403} else ("rate_limited" if int(status) == 429 else "probe_failed")
            model["last_error"] = detail
            row["access_status"] = model["access_status"]
            outcomes.append(row)
            disabled += 1
        self._last_access_validation_outcomes = outcomes
        return {"checked": checked, "disabled": disabled}

    def audit_model_access_key(self):
        self.sync_serverless_model_catalog(force=False, validate_access=False)
        models = self.load_model_registry(include_disabled=True)
        checked = 0
        allowed = []
        blocked = []
        skipped = []
        probe = self.probe_serverless_text_model_func or self.probe_serverless_text_model
        for model in models:
            if not model.get("serverless") or model.get("type") != "text":
                continue
            checked += 1
            ok, status, detail = probe(model["id"])
            row = {
                "id": model["id"],
                "display_name": model.get("display_name") or model["id"],
                "owned_by": model.get("owned_by") or "",
                "pricing": model.get("pricing") or {},
                "status": int(status),
            }
            access_status = self.access_status_from_probe(ok, status)
            if ok:
                model["access_status"] = "ok"
                model["last_error"] = ""
                row["access_status"] = "ok"
                allowed.append(row)
                continue
            model["access_status"] = access_status
            model["last_error"] = detail
            row["access_status"] = access_status
            row["error"] = detail
            if int(status) in {401, 403}:
                blocked.append(row)
            else:
                skipped.append(row)
        outcomes = allowed + blocked + skipped
        access_drift = self.record_access_drift(outcomes, source="audit")
        self.refresh_model_globals()
        sync = self.proxy_sync_payload(force=True)
        return {
            "ok": True,
            "checked_at": self.clock(),
            "key": self.active_model_access_key_info(),
            "checked": checked,
            "allowed_count": len(allowed),
            "blocked_count": len(blocked),
            "skipped_count": len(skipped),
            "allowed": allowed,
            "blocked": blocked,
            "skipped": skipped,
            "access_drift": access_drift,
            "active_text_models": self.active_text_models(),
            "text_model_options": self.model_options("text", include_disabled=True),
            "image_model_options": self.model_options("image", include_disabled=True),
            "model_metadata": self.model_metadata_map(),
            "proxy_sync": sync,
            "note": "DigitalOcean does not expose the selected-model scope for a secret key through the serverless runtime API; this audit verifies access by probing each serverless text model.",
        }

    def sync_serverless_model_catalog(self, force=False, validate_access=False):
        catalog_payload = self.serverless_catalog_payload_func or self.serverless_catalog_payload
        catalog = catalog_payload(force=force)
        data = catalog.get("payload", {}).get("data", []) if isinstance(catalog.get("payload"), dict) else []
        if not isinstance(data, list) or not data:
            return {
                "ok": False,
                "error": catalog.get("error") or "DigitalOcean catalog did not return models",
                "added": 0,
                "updated": 0,
                "total": len(self.load_model_registry(include_disabled=True)),
                "catalog": catalog,
            }
        existing_models = self.load_model_registry(include_disabled=True)
        by_id = {model["id"]: model for model in existing_models}
        added = 0
        updated = 0
        seen_catalog_ids = set()
        for item in data:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            seen_catalog_ids.add(model_id)
            existing = by_id.get(model_id)
            if existing and isinstance(existing.get("dedicated"), dict):
                continue
            entry = self.serverless_registry_entry(item, existing=existing)
            if existing != entry:
                updated += 1 if existing else 0
                added += 0 if existing else 1
                by_id[model_id] = entry
        removed = 0
        for model_id, model in list(by_id.items()):
            if model_id in seen_catalog_ids or not model.get("serverless") or isinstance(model.get("dedicated"), dict):
                continue
            if model.get("access_status") != "removed" or model.get("enabled") is not False:
                model["enabled"] = False
                model["access_status"] = "removed"
                model["last_error"] = "DigitalOcean catalog no longer lists this model."
                by_id[model_id] = model
                removed += 1
        removed_outcomes = [
            {"id": model.get("id"), "display_name": model.get("display_name") or model.get("id"), "access_status": "removed", "status": 410, "error": model.get("last_error") or ""}
            for model in by_id.values()
            if model.get("access_status") == "removed" and not isinstance(model.get("dedicated"), dict)
        ]
        access_drift = self.record_access_drift(removed_outcomes, source="catalog_sync") if removed_outcomes else self.access_drift_payload()
        dedicated = [model for model in existing_models if isinstance(model.get("dedicated"), dict) and model["id"] not in by_id]
        merged = list(by_id.values()) + dedicated
        access = self.validate_serverless_access(merged) if validate_access else {"checked": 0, "disabled": 0}
        if validate_access:
            validation_outcomes = getattr(self, "_last_access_validation_outcomes", [])
            access_drift = self.record_access_drift(validation_outcomes, source="catalog_sync") if validation_outcomes else access_drift
        merged.sort(key=lambda model: (0 if model.get("serverless") else 1, str(model.get("type") or ""), str(model.get("id") or "")))
        # Only rewrite the governance-locked registry when something actually
        # changed. This is triggered by every GET /api/models, /api/status, and
        # /api/dedicated/status via models_payload(refresh_catalog=True); an
        # unconditional save churned the file (and refreshed globals) on every
        # poll from multiple threads. Access probes persist to the runtime
        # model-access state file instead of rewriting the governed registry.
        changed = bool(added or updated or removed)
        if changed:
            saved = self.save_model_registry(merged)
            self.refresh_model_globals()
        else:
            saved = list(merged)
        return {
            "ok": True,
            "added": added,
            "updated": updated,
            "removed": removed,
            "total": len(saved),
            "catalog": {
                "ok": catalog.get("ok"),
                "source": catalog.get("source"),
                "fetched_at": catalog.get("fetched_at"),
                "error": catalog.get("error"),
            },
            "auto_enable_threshold_usd": self.auto_enable_max_usd,
            "access_validation": access,
            "access_drift": access_drift,
            "text_model_options": self.model_options("text", include_disabled=True),
            "image_model_options": self.model_options("image", include_disabled=True),
            "model_metadata": self.model_metadata_map(),
        }
