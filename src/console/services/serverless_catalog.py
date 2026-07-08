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
            "auto_managed": not bool(existing),
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
        probe = self.probe_serverless_text_model_func or self.probe_serverless_text_model
        for model in models:
            if not model.get("serverless") or model.get("type") != "text":
                continue
            pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
            if not self.model_enabled_by_default(pricing):
                continue
            checked += 1
            ok, status, detail = probe(model["id"])
            if ok:
                model["enabled"] = True
                model["access_status"] = "ok"
                model["last_error"] = ""
                continue
            model["access_status"] = "forbidden" if int(status) in {401, 403} else ("rate_limited" if int(status) == 429 else "probe_failed")
            model["last_error"] = detail
            if int(status) in {401, 403}:
                model["enabled"] = False
                disabled += 1
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
            if ok:
                model["access_status"] = "ok"
                model["last_error"] = ""
                model["enabled"] = True
                allowed.append(row)
                continue
            access_status = "forbidden" if int(status) in {401, 403} else ("rate_limited" if int(status) == 429 else "probe_failed")
            model["access_status"] = access_status
            model["last_error"] = detail
            row["access_status"] = access_status
            row["error"] = detail
            if int(status) in {401, 403}:
                model["enabled"] = False
                blocked.append(row)
            else:
                skipped.append(row)
        self.save_model_registry(models)
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
            if self.model_enabled_by_default(entry.get("pricing") or {}) and not validate_access and entry.get("access_status") != "forbidden":
                entry["enabled"] = True
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
        dedicated = [model for model in existing_models if isinstance(model.get("dedicated"), dict) and model["id"] not in by_id]
        merged = list(by_id.values()) + dedicated
        access = self.validate_serverless_access(merged) if validate_access else {"checked": 0, "disabled": 0}
        merged.sort(key=lambda model: (0 if model.get("serverless") else 1, str(model.get("type") or ""), str(model.get("id") or "")))
        saved = self.save_model_registry(merged)
        self.refresh_model_globals()
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
            "text_model_options": self.model_options("text", include_disabled=True),
            "image_model_options": self.model_options("image", include_disabled=True),
            "model_metadata": self.model_metadata_map(),
        }
