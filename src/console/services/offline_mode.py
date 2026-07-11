"""Offline/degraded mode aggregation."""
import time


class OfflineModeService:
    """Report provider availability and safe local fallback workflows."""

    def __init__(
        self,
        provider_health_payload,
        serverless_catalog_payload,
        models_payload,
        list_eval_datasets,
        list_eval_runs,
        clock=None,
    ):
        self.provider_health_payload = provider_health_payload
        self.serverless_catalog_payload = serverless_catalog_payload
        self.models_payload = models_payload
        self.list_eval_datasets = list_eval_datasets
        self.list_eval_runs = list_eval_runs
        self.clock = clock or time.time

    def payload(self):
        now = float(self.clock())
        provider = self.safe_call(self.provider_health_payload, {"providers": [], "findings": []})
        catalog = self.safe_call(lambda: self.serverless_catalog_payload(force=False), {"ok": False, "payload": {"data": []}, "source": "unavailable", "fetched_at": 0, "error": "catalog unavailable"})
        models = self.safe_call(lambda: self.models_payload(refresh_catalog=False), {"models": [], "text_model_options": [], "image_model_options": []})
        datasets = self.safe_call(self.list_eval_datasets, [])
        runs = self.safe_call(lambda: self.list_eval_runs(limit=10), [])
        mode, reasons = self.mode(provider, catalog)
        cache = self.cache_summary(now, catalog, models, datasets, runs)
        live_guard = mode in {"offline", "degraded"}
        return {
            "generated_at": now,
            "mode": mode,
            "reasons": reasons,
            "provider": {
                "status": ((provider.get("providers") or [{}])[0] or {}).get("status") or "unknown",
                "findings": provider.get("findings") or [],
            },
            "cache": cache,
            "local_workflows": [
                {"id": "model_registry", "label": "Browse model registry", "available": True, "source": "local_registry"},
                {"id": "eval_datasets", "label": "Edit eval datasets", "available": True, "count": len(datasets or []), "source": "local_files"},
                {"id": "eval_history", "label": "Review prior eval runs", "available": True, "count": len(runs or []), "source": "runtime_cache"},
                {"id": "reports", "label": "Browse saved reports and traces", "available": True, "source": "runtime_cache"},
                {"id": "profiles", "label": "Edit saved profiles and templates", "available": True, "source": "local_runtime"},
            ],
            "live_cloud_actions": [
                {"id": "serverless_catalog_refresh", "label": "Refresh Serverless catalog", "requires_live_provider": True, "guarded": live_guard},
                {"id": "model_access_audit", "label": "Audit model access key", "requires_live_provider": True, "guarded": live_guard},
                {"id": "dedicated_build", "label": "Build Dedicated Inference", "requires_live_provider": True, "guarded": live_guard},
                {"id": "dedicated_discovery", "label": "Discover Dedicated sizes/GPU configs", "requires_live_provider": True, "guarded": live_guard},
                {"id": "billing_report", "label": "Fetch DigitalOcean billing", "requires_live_provider": True, "guarded": live_guard},
            ],
            "ui_policy": {
                "disable_live_cloud_actions": mode == "offline",
                "confirm_live_cloud_actions": mode == "degraded",
                "banner": self.banner(mode, reasons),
            },
        }

    def mode(self, provider, catalog):
        reasons = []
        provider_row = ((provider.get("providers") or [{}])[0] or {}) if isinstance(provider, dict) else {}
        provider_status = str(provider_row.get("status") or "unknown").lower()
        issue_type = str(provider_row.get("issue_type") or "none")
        catalog_source = str(catalog.get("source") or "")
        catalog_ok = bool(catalog.get("ok"))
        catalog_data = catalog.get("payload", {}).get("data", []) if isinstance(catalog.get("payload"), dict) else []
        if provider_status in {"degraded", "failed", "error"}:
            reasons.append("provider_%s" % provider_status)
        if issue_type not in {"", "none", "not_configured"}:
            reasons.append(issue_type)
        if not catalog_ok:
            reasons.append("serverless_catalog_unavailable")
        if catalog_source in {"fallback", "unavailable"} and not catalog_data:
            return "offline", sorted(set(reasons or ["provider_unreachable"]))
        if catalog_source == "cache_after_fetch_error":
            reasons.append("using_stale_serverless_cache")
            return "degraded", sorted(set(reasons))
        if reasons:
            return "degraded", sorted(set(reasons))
        return "online", []

    def cache_summary(self, now, catalog, models, datasets, runs):
        fetched_at = float(catalog.get("fetched_at") or 0.0)
        catalog_age = max(0.0, now - fetched_at) if fetched_at else None
        stale = catalog_age is None or catalog_age > 86400
        source = catalog.get("source") or "unknown"
        if catalog.get("ok") and not stale:
            confidence = "fresh"
        elif catalog.get("payload", {}).get("data") if isinstance(catalog.get("payload"), dict) else False:
            confidence = "stale"
        else:
            confidence = "empty"
        return {
            "serverless_catalog": {
                "ok": bool(catalog.get("ok")),
                "source": source,
                "fetched_at": fetched_at,
                "age_seconds": catalog_age,
                "stale": stale,
                "confidence": confidence,
                "error": catalog.get("error") or "",
                "models": len(catalog.get("payload", {}).get("data", [])) if isinstance(catalog.get("payload"), dict) else 0,
            },
            "model_registry": {"source": "local_registry", "models": len(models.get("models") or [])},
            "eval_datasets": {"source": "local_files", "datasets": len(datasets or [])},
            "eval_runs": {"source": "runtime_cache", "runs_sampled": len(runs or [])},
        }

    def banner(self, mode, reasons):
        if mode == "online":
            return "Provider APIs are reachable."
        if mode == "offline":
            return "Offline mode: local cached workflows are available; live cloud actions are disabled."
        return "Degraded mode: cached data is available; live cloud actions require confirmation."

    def safe_call(self, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            if isinstance(fallback, dict):
                fallback = dict(fallback)
                fallback["error"] = str(exc)
            return fallback
