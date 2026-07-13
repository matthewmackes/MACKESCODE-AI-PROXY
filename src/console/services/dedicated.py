"""DigitalOcean Dedicated Inference lifecycle orchestration."""
import datetime
import gzip
import json
import time
from http import HTTPStatus
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.console.policy import PolicyService


class DedicatedInferenceService:
    """Owns Dedicated Inference state, registry integration, and chat routing."""

    active_states = {"new", "creating", "provisioning", "active", "idle_warning", "draining", "cooldown", "tearing_down"}
    schema_version = 1
    # Sensitive operational metadata that must never reach a viewer-scoped status
    # payload or lifecycle event detail (GOVERNANCE: Dedicated endpoint access
    # tokens, public/private endpoint FQDNs, inference ids, VPC UUIDs, CA certs,
    # and raw DigitalOcean payloads are sensitive). Comparison is case-insensitive
    # and matches exact keys anywhere in a nested details/response structure.
    sensitive_detail_keys = frozenset({
        "access_token", "access_key", "token", "authorization", "bearer",
        "public_endpoint_fqdn", "private_endpoint_fqdn", "endpoints", "endpoint",
        "vpc_uuid", "vpc", "ca_certificate", "ca_cert", "inference_id", "id", "raw",
    })

    def __init__(
        self,
        default_config,
        steps,
        config_file,
        events_file,
        tail_jsonl,
        digitalocean_token,
        do_request,
        load_model_registry,
        save_model_registry,
        refresh_model_globals,
        models_payload,
        digitalocean_health_snapshot,
        serverless_chat_completion,
        active_text_models,
        default_text_model,
        local_usage_report=None,
        clock=None,
        legacy_config_file=None,
        event_bus=None,
        policy_service=None,
    ):
        self.default_config = dict(default_config)
        self.steps = list(steps)
        self.config_file = config_file
        self.legacy_config_file = legacy_config_file
        self.events_file = events_file
        self.tail_jsonl = tail_jsonl
        self.digitalocean_token = digitalocean_token
        self.do_request = do_request
        self.load_model_registry = load_model_registry
        self.save_model_registry = save_model_registry
        self.refresh_model_globals = refresh_model_globals
        self.models_payload = models_payload
        self.digitalocean_health_snapshot = digitalocean_health_snapshot
        self.serverless_chat_completion = serverless_chat_completion
        self.active_text_models = active_text_models
        self.default_text_model = default_text_model
        self.local_usage_report = local_usage_report or (lambda start_date, end_date: {"total_usd": 0.0, "by_model": []})
        self.clock = clock or time.time
        self.event_bus = event_bus
        self.policy_service = policy_service or PolicyService()

    def validate_config_document(self, data):
        if not isinstance(data, dict):
            raise ValueError("Dedicated Inference config must be a JSON object.")
        raw_version = data.get("schema_version", self.schema_version)
        try:
            schema_version = int(raw_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("Dedicated Inference config schema_version must be an integer.") from exc
        if schema_version != self.schema_version:
            raise ValueError("Dedicated Inference config schema_version %s is not supported; expected %s." % (schema_version, self.schema_version))
        issues = []
        if "schema_version" not in data:
            issues.append("Dedicated Inference config is missing schema_version; assuming schema_version 1.")
        if "state" in data and not isinstance(data.get("state"), str):
            raise ValueError("Dedicated Inference config state must be a string.")
        for key in ("scale", "idle_warning_seconds", "idle_teardown_seconds", "unhealthy_teardown_seconds"):
            if key in data:
                try:
                    int(data.get(key))
                except (TypeError, ValueError) as exc:
                    raise ValueError("Dedicated Inference config %s must be an integer." % key) from exc
        for key in ("price_per_hour", "daily_budget_usd", "warning_threshold", "cooldown_threshold"):
            if key in data:
                try:
                    float(data.get(key))
                except (TypeError, ValueError) as exc:
                    raise ValueError("Dedicated Inference config %s must be numeric." % key) from exc
        return issues

    def read_config_file(self, path):
        result = {"exists": path.exists(), "valid": True, "issues": [], "data": {}}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    result["issues"] = self.validate_config_document(data)
                    result["data"] = data
                else:
                    result.update({"valid": False, "issues": ["Dedicated Inference config must be a JSON object."]})
            except (OSError, ValueError) as exc:
                result.update({"valid": False, "issues": [str(exc)]})
        return result

    def config_status(self):
        result = self.read_config_file(self.config_file())
        return {key: value for key, value in result.items() if key != "data"}

    def load_config(self):
        cfg = dict(self.default_config)
        path = self.config_file()
        data = self.read_config_file(path)["data"]
        if not data and self.legacy_config_file:
            legacy_path = self.legacy_config_file()
            if legacy_path != path:
                data = self.read_config_file(legacy_path)["data"]
                if data:
                    self.save_config(data)
        if data:
            cfg.update(data)
        return cfg

    def save_config(self, cfg):
        merged = dict(self.default_config)
        merged.update(cfg or {})
        merged["schema_version"] = self.schema_version
        path = self.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return merged

    def redact_sensitive(self, value):
        """Recursively drop sensitive keys so lifecycle event details and status
        payloads never leak Dedicated endpoint access tokens, endpoint FQDNs,
        inference ids, VPC UUIDs, CA certs, or raw DigitalOcean responses to a
        viewer-scoped reader. Non-sensitive diagnostics (status codes, error
        messages) are preserved even when nested inside a raw ``response``."""
        if isinstance(value, dict):
            return {
                key: self.redact_sensitive(item)
                for key, item in value.items()
                if str(key).lower() not in self.sensitive_detail_keys
            }
        if isinstance(value, list):
            return [self.redact_sensitive(item) for item in value]
        return value

    def append_event(self, state, message, severity="info", details=None):
        event = {
            "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ts": self.clock(),
            "state": state,
            "severity": severity,
            "message": message,
            "details": self.redact_sensitive(details or {}),
        }
        path = self.events_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        if self.event_bus is not None:
            try:
                self.event_bus.publish("lifecycle.dedicated", severity=severity, subject={"type": "dedicated", "id": state}, correlation={}, payload=event)
            except Exception:
                pass
        return event

    def events(self, limit=80):
        rows = self.tail_jsonl(self.events_file(), limit=limit)
        rows.sort(key=lambda item: item.get("ts", 0), reverse=True)
        return rows

    def archive_old_events(self, retention_days=30):
        path = self.events_file()
        if not path.exists():
            return {"archived": 0, "archive_file": "", "retained": 0}
        cutoff = self.clock() - (max(1, int(retention_days)) * 86400)
        old_lines = []
        recent_lines = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {"archived": 0, "archive_file": "", "retained": 0}
        for line in lines:
            try:
                row = json.loads(line)
                ts = float(row.get("ts") or 0)
            except (TypeError, ValueError):
                recent_lines.append(line)
                continue
            if ts and ts < cutoff:
                old_lines.append(line)
            else:
                recent_lines.append(line)
        if not old_lines:
            return {"archived": 0, "archive_file": "", "retained": len(recent_lines)}
        archive_file = path.with_name("%s-%d.jsonl.gz" % (path.stem + "-archive", int(self.clock())))
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(archive_file, "wt", encoding="utf-8") as f:
            f.write("\n".join(old_lines) + "\n")
        path.write_text(("\n".join(recent_lines) + "\n") if recent_lines else "", encoding="utf-8")
        self.append_event("archive", "Archived old Dedicated lifecycle diagnostics", "info", {
            "archive_file": str(archive_file),
            "archived": len(old_lines),
            "retained": len(recent_lines),
            "retention_days": retention_days,
        })
        return {"archived": len(old_lines), "archive_file": str(archive_file), "retained": len(recent_lines)}

    def elapsed_seconds(self, cfg, now=None):
        now = now or self.clock()
        start = float(cfg.get("run_started_at") or 0)
        if not start or cfg.get("state") in {"not_configured", "deleted", "failed"}:
            return 0
        return max(0, int(now - start))

    def cost_usd(self, cfg, now=None):
        hourly = float(cfg.get("price_per_hour") or 0)
        return round((self.elapsed_seconds(cfg, now) / 3600.0) * hourly, 8)

    def clipped_seconds(self, start, end, window_start, window_end):
        left = max(float(start), float(window_start))
        right = min(float(end), float(window_end))
        return max(0.0, right - left)

    def runtime_cost_summary(self, cfg, now=None):
        now = now or self.clock()
        hourly = float(cfg.get("price_per_hour") or 0)
        month_start = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        day_start = now - 86400
        rows = self.tail_jsonl(self.events_file(), limit=100000)
        rows.sort(key=lambda item: float(item.get("ts") or 0))
        intervals = []
        open_start = None
        # Reconstruct billing intervals from structured lifecycle *state*
        # transitions only, never from human-readable message copy (PR-1.3): a
        # billing server opens an interval when it first enters a start state and
        # closes it when it reaches a terminal state. Reading the message text
        # meant a reworded event could silently drop cost from the budget guard.
        billing_start_states = {"new", "provisioning", "active"}
        billing_stop_states = {"deleted", "failed"}
        for row in rows:
            try:
                ts = float(row.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            state = str(row.get("state") or "")
            if state in billing_start_states and open_start is None:
                open_start = ts
            elif state in billing_stop_states and open_start is not None and ts >= open_start:
                intervals.append((open_start, ts))
                open_start = None
        if open_start is None and cfg.get("state") in self.active_states:
            open_start = float(cfg.get("run_started_at") or cfg.get("created_at") or 0) or None
        if open_start is not None:
            intervals.append((open_start, now))
        month_seconds = sum(self.clipped_seconds(start, end, month_start, now) for start, end in intervals)
        day_seconds = sum(self.clipped_seconds(start, end, day_start, now) for start, end in intervals)
        return {
            "hourly_usd": hourly,
            "month_seconds": int(month_seconds),
            "last_24h_seconds": int(day_seconds),
            "month_cost_usd": round((month_seconds / 3600.0) * hourly, 8),
            "last_24h_cost_usd": round((day_seconds / 3600.0) * hourly, 8),
            "interval_count": len(intervals),
            "source": "local Dedicated lifecycle events",
        }

    def budget_state(self, cfg, now=None):
        summary = self.runtime_cost_summary(cfg, now)
        limit = float(cfg.get("daily_budget_usd") or 0)
        warning_threshold = float(cfg.get("warning_threshold") or 0.8)
        critical_threshold = float(cfg.get("cooldown_threshold") or 0.95)
        used = float(summary.get("last_24h_cost_usd") or 0)
        percent = round((used / limit) * 100, 2) if limit else 0
        projected_one_hour = round(used + float(summary.get("hourly_usd") or 0), 8)
        projected_percent = round((projected_one_hour / limit) * 100, 2) if limit else 0
        warning_percent = round(warning_threshold * 100, 2)
        critical_percent = round(critical_threshold * 100, 2)
        return {
            "limit_usd": limit,
            "used_24h_usd": used,
            "percent": percent,
            "warning_threshold": warning_threshold,
            "critical_threshold": critical_threshold,
            "warning_percent": warning_percent,
            "critical_percent": critical_percent,
            "projected_one_hour_usd": projected_one_hour,
            "projected_one_hour_percent": projected_percent,
            "warning": bool(limit and percent >= warning_percent),
            "critical": bool(limit and percent >= critical_percent),
            "summary": summary,
        }

    def idle_seconds(self, cfg, now=None):
        now = now or self.clock()
        last = float(cfg.get("last_work_at") or cfg.get("run_started_at") or 0)
        if not last:
            return 0
        return max(0, int(now - last))

    def idle_policy_state(self, cfg, now=None):
        now = now or self.clock()
        idle = self.idle_seconds(cfg, now)
        warning_seconds = max(0, int(cfg.get("idle_warning_seconds") or 300))
        teardown_seconds = max(warning_seconds, int(cfg.get("idle_teardown_seconds") or 600))
        keep_alive_until = float(cfg.get("keep_alive_until") or 0)
        keep_alive_started_at = float(cfg.get("keep_alive_started_at") or 0)
        last_work_at = float(cfg.get("last_work_at") or 0)
        # Reference time idle is measured from (last work, else run start) — the
        # same basis idle_seconds uses.
        last_reference = float(cfg.get("last_work_at") or cfg.get("run_started_at") or 0)
        # Normal idle-policy teardown deadline.
        idle_deadline = (last_reference + teardown_seconds) if last_reference else 0
        # PR-1.4: a keep-alive extension may only ever push the effective teardown
        # deadline LATER, never earlier. The effective deadline is therefore the
        # max of the normal idle deadline and any operator keep-alive floor, so an
        # expiring *short* keep-alive can no longer force teardown while a longer
        # idle window still has time left.
        effective_deadline = max(idle_deadline, keep_alive_until) if keep_alive_until else idle_deadline
        extension_active_unused = bool(keep_alive_until and now < keep_alive_until and last_work_at <= keep_alive_started_at)
        extension_expired_unused = bool(keep_alive_until and now >= keep_alive_until and last_work_at <= keep_alive_started_at)
        warning = bool(cfg.get("state") == "active" and warning_seconds and idle >= warning_seconds)
        teardown_due = bool(
            cfg.get("state") == "active"
            and teardown_seconds
            and effective_deadline
            and now >= effective_deadline
        )
        countdown = max(0, int(effective_deadline - now)) if effective_deadline else 0
        return {
            "idle_seconds": idle,
            "warning_seconds": warning_seconds,
            "teardown_seconds": teardown_seconds,
            "warning": warning,
            "teardown_due": teardown_due,
            "teardown_countdown_seconds": countdown if cfg.get("state") == "active" else 0,
            "keep_alive_until": keep_alive_until,
            "keep_alive_started_at": keep_alive_started_at,
            "effective_teardown_deadline": effective_deadline,
            "extension_active_unused": extension_active_unused,
            "extension_expired_unused": extension_expired_unused,
        }

    def unhealthy_policy_state(self, cfg, now=None):
        now = now or self.clock()
        started = float(cfg.get("unhealthy_started_at") or 0)
        teardown_seconds = max(0, int(cfg.get("unhealthy_teardown_seconds") or 300))
        elapsed = max(0, int(now - started)) if started else 0
        return {
            "failed_checks": int(cfg.get("unhealthy_failed_checks") or 0),
            "unhealthy": bool(started),
            "unhealthy_started_at": started,
            "teardown_seconds": teardown_seconds,
            "teardown_countdown_seconds": max(0, teardown_seconds - elapsed) if started else 0,
            "teardown_due": bool(started and elapsed >= teardown_seconds),
            "last_error": cfg.get("last_error") or "",
        }

    def record_health_success(self, cfg):
        if cfg.get("unhealthy_failed_checks") or cfg.get("unhealthy_started_at"):
            cfg["unhealthy_failed_checks"] = 0
            cfg["unhealthy_started_at"] = 0
            self.append_event("healthy", "Dedicated health checks recovered", "success", {"model_id": cfg.get("model_id")})
        return cfg

    def record_health_failure(self, cfg, reason, details=None):
        cfg["unhealthy_failed_checks"] = int(cfg.get("unhealthy_failed_checks") or 0) + 1
        cfg["last_error"] = reason
        if cfg["unhealthy_failed_checks"] >= 3 and not cfg.get("unhealthy_started_at"):
            cfg["unhealthy_started_at"] = self.clock()
            self.append_event("unhealthy", "Dedicated health countdown started after repeated failures", "error", {
                "failed_checks": cfg["unhealthy_failed_checks"],
                "reason": reason,
                "details": details or {},
                "model_id": cfg.get("model_id"),
                "inference_id": cfg.get("inference_id"),
            })
        return cfg

    def enforce_policy(self):
        self.archive_old_events()
        cfg = self.load_config()
        idle_policy = self.idle_policy_state(cfg)
        unhealthy_policy = self.unhealthy_policy_state(cfg)
        policy_decision = self.policy_service.dedicated_lifecycle_decision(cfg, idle_policy, unhealthy_policy).to_dict()
        budget_state = self.budget_state(cfg)
        if cfg.get("state") != "active":
            return {"action": "none", "reason": "not_active", "policy_decision": policy_decision, "idle_policy": idle_policy, "unhealthy_policy": unhealthy_policy, "budget_state": budget_state, "dedicated": self.public_payload(cfg)}
        # Numeric budget guard (PR-1.3): an over-budget active billing server is
        # torn down by the headless policy path itself, using the numeric
        # budget_state (never reconstructed from human-readable event copy), so
        # enforcement does not depend on a browser polling the status endpoint.
        if budget_state["critical"]:
            self.append_event("budget_teardown", "Dedicated over-budget guard triggered teardown", "error", {
                "reason": "budget_exceeded",
                "budget_state": budget_state,
                "budget_percent": budget_state["percent"],
                "used_24h_usd": budget_state["used_24h_usd"],
                "limit_usd": budget_state["limit_usd"],
                "model_id": cfg.get("model_id"),
            })
            status, payload = self.teardown({"reason": "budget_exceeded"})
            return {"action": "teardown", "reason": "budget_exceeded", "status": int(status), "payload": payload, "policy_decision": policy_decision, "budget_state": budget_state}
        if unhealthy_policy["teardown_due"]:
            self.append_event("unhealthy_teardown", "Dedicated unhealthy policy triggered teardown", "error", {
                "unhealthy_policy": unhealthy_policy,
                "model_id": cfg.get("model_id"),
                "inference_id": cfg.get("inference_id"),
                "policy_decision": policy_decision,
            })
            status, payload = self.teardown({"reason": "unhealthy_timeout"})
            return {"action": "teardown", "reason": "unhealthy_timeout", "status": int(status), "payload": payload, "policy_decision": policy_decision}
        if idle_policy["teardown_due"]:
            reason = "keep_alive_extension_expired" if idle_policy["extension_expired_unused"] else "idle_timeout"
            self.append_event("idle_teardown", "Dedicated idle policy triggered teardown", "warning", {
                "reason": reason,
                "idle_policy": idle_policy,
                "model_id": cfg.get("model_id"),
                "inference_id": cfg.get("inference_id"),
                "policy_decision": policy_decision,
            })
            status, payload = self.teardown({"reason": reason})
            return {"action": "teardown", "reason": reason, "status": int(status), "payload": payload, "policy_decision": policy_decision}
        if idle_policy["warning"]:
            warning_started = float(cfg.get("idle_warning_started_at") or 0)
            last_work = float(cfg.get("last_work_at") or cfg.get("run_started_at") or 0)
            if warning_started < last_work:
                cfg["idle_warning_started_at"] = self.clock()
                self.save_config(cfg)
                self.append_event("idle_warning", "Dedicated server is idle and teardown countdown is active", "warning", {
                    "idle_policy": idle_policy,
                    "model_id": cfg.get("model_id"),
                    "inference_id": cfg.get("inference_id"),
                    "policy_decision": policy_decision,
                })
                return {"action": "warning", "reason": "idle_warning", "policy_decision": policy_decision, "idle_policy": idle_policy, "budget_state": budget_state, "dedicated": self.public_payload(cfg)}
        return {"action": "none", "reason": "within_policy", "policy_decision": policy_decision, "idle_policy": idle_policy, "unhealthy_policy": unhealthy_policy, "budget_state": budget_state, "dedicated": self.public_payload(cfg)}

    def keep_alive(self, data):
        data = data or {}
        cfg = self.load_config()
        allowed = {300, 600, 1800, 3600}
        try:
            seconds = int(data.get("seconds") or data.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            seconds = 0
        policy_decision = self.policy_service.dedicated_keep_alive_decision(cfg, seconds, allowed).to_dict()
        if seconds not in allowed:
            return HTTPStatus.BAD_REQUEST, {"error": "Keep-alive duration must be one of 300, 600, 1800, or 3600 seconds.", "policy_decision": policy_decision}
        if cfg.get("state") != "active":
            return HTTPStatus.CONFLICT, {"error": "Keep-alive is only available while Dedicated Inference is active.", "dedicated": self.public_payload(cfg), "policy_decision": policy_decision}
        now = self.clock()
        cfg["keep_alive_started_at"] = now
        cfg["keep_alive_until"] = now + seconds
        cfg["idle_warning_started_at"] = 0
        self.save_config(cfg)
        self.append_event("keep_alive", "Dedicated idle teardown extended", "info", {
            "seconds": seconds,
            "until": cfg["keep_alive_until"],
            "operator": data.get("operator") or data.get("session_id") or "console-token-user",
            "idle_policy": self.idle_policy_state(cfg, now),
            "policy_decision": policy_decision,
        })
        payload = self.status_payload(poll=False)
        payload["policy_decision"] = policy_decision
        return HTTPStatus.OK, payload

    def public_payload(self, cfg):
        now = self.clock()
        clean = dict(cfg)
        # Redact sensitive operational metadata before this reaches a
        # viewer-scoped status payload (PR-1.5 / GOVERNANCE). Expose booleans so
        # the GUI can still show configured/ready state without the secret value,
        # mirroring the existing access_token redaction pattern.
        clean["access_token_configured"] = bool(cfg.get("access_token"))
        clean["inference_configured"] = bool(cfg.get("inference_id"))
        clean["endpoint_configured"] = bool(self.endpoint(cfg))
        clean["public_endpoint_configured"] = bool(cfg.get("public_endpoint_fqdn"))
        clean["private_endpoint_configured"] = bool(cfg.get("private_endpoint_fqdn"))
        for key in ("access_token", "inference_id", "public_endpoint_fqdn",
                    "private_endpoint_fqdn", "vpc_uuid", "ca_certificate"):
            if key in clean:
                clean[key] = ""
        clean["raw"] = {}
        clean.update({
            "elapsed_seconds": self.elapsed_seconds(cfg, now),
            "idle_seconds": self.idle_seconds(cfg, now),
            "idle_policy": self.idle_policy_state(cfg, now),
            "unhealthy_policy": self.unhealthy_policy_state(cfg, now),
            "estimated_cost_usd": self.cost_usd(cfg, now),
            "build_age_seconds": max(0, int(now - float(cfg.get("created_at") or now))),
            "status_age_seconds": max(0, int(now - float(cfg.get("last_status_at") or cfg.get("created_at") or now))),
            "token_configured": bool(self.digitalocean_token()),
            "config_file": str(self.config_file()),
            "config_status": self.config_status(),
            "events_file": str(self.events_file()),
            "steps": self.steps,
        })
        budget = float(cfg.get("daily_budget_usd") or 0)
        clean["budget_percent"] = round((clean["estimated_cost_usd"] / budget) * 100, 2) if budget else 0
        clean["budget_state"] = self.budget_state(cfg, now)
        clean["budget_state"]["policy_decision"] = self.policy_service.dedicated_build_budget_decision(clean["budget_state"], cfg=cfg).to_dict()
        return clean

    def extract_id(self, response):
        if not isinstance(response, dict):
            return ""
        for key in ("dedicated_inference", "inference", "data"):
            item = response.get(key)
            if isinstance(item, dict) and item.get("id"):
                return str(item.get("id"))
        return str(response.get("id") or "")

    def extract_resource(self, response):
        if not isinstance(response, dict):
            return {}
        for key in ("dedicated_inference", "inference", "data"):
            item = response.get(key)
            if isinstance(item, dict):
                return item
        return response

    def endpoint(self, cfg):
        endpoint = cfg.get("public_endpoint_fqdn") if cfg.get("enable_public_endpoint") else cfg.get("private_endpoint_fqdn")
        endpoint = str(endpoint or cfg.get("public_endpoint_fqdn") or cfg.get("private_endpoint_fqdn") or "").strip()
        if endpoint and not endpoint.startswith("http"):
            endpoint = "https://" + endpoint
        return endpoint.rstrip("/")

    def status_message(self, cfg):
        state = cfg.get("state") or "not_configured"
        model = cfg.get("display_name") or cfg.get("model_id") or "Dedicated Inference"
        server_id = cfg.get("inference_id") or "not assigned yet"
        region = cfg.get("region") or "unknown region"
        gpu = cfg.get("accelerator_slug") or "unknown accelerator"
        endpoint = self.endpoint(cfg)
        if state in {"creating", "new", "provisioning", "updating"}:
            step = "DigitalOcean is still building the Dedicated Inference endpoint."
            if not endpoint:
                step += " A public endpoint has not been assigned yet."
            return "%s is not ready yet. %s Current state: %s. Server: %s. Region/GPU: %s / %s. The request was not sent to the model; refresh Dedicated Inference status or wait for the build to reach active." % (model, step, state, server_id, region, gpu)
        if state in {"failed", "error"}:
            return "%s is unavailable because the Dedicated Inference build failed. Server: %s. Last error: %s" % (model, server_id, cfg.get("last_error") or "DigitalOcean did not provide a detailed error.")
        if state in {"deleted", "tearing_down", "not_configured"}:
            return "%s is not available because the Dedicated Inference instance is %s. Build a server before selecting this model." % (model, state)
        if not endpoint:
            return "%s is marked %s, but no endpoint is available yet. Server: %s. Refresh status before retrying." % (model, state, server_id)
        if not cfg.get("access_token"):
            return "%s has an endpoint, but the access token has not been issued yet. Server: %s. Refresh status before retrying." % (model, server_id)
        return "%s is not ready for requests. Current state: %s. Server: %s." % (model, state, server_id)

    def not_ready_payload(self, cfg, requested_model):
        lifecycle = self.public_payload(cfg)
        message = self.status_message(cfg)
        do_health = self.digitalocean_health_snapshot()
        state = lifecycle.get("state")
        if state in {"failed", "error"}:
            next_step = "Rebuild Dedicated Inference with another available GPU or region, or select a Serverless model."
        elif state in {"deleted", "tearing_down", "not_configured"}:
            next_step = "Build a Dedicated Inference server before selecting this model."
            decision = "build_server_prompt"
            reason = "dedicated_not_online"
        else:
            next_step = "Wait for DigitalOcean to report active, then the app will register and enable the Dedicated model globally."
            decision = "dedicated_wait_not_ready"
            reason = "dedicated_not_ready"
        if state in {"failed", "error"}:
            decision = "dedicated_failed_rebuild_or_fallback"
            reason = "dedicated_failed"
        return {
            "error": message,
            "message": message,
            "routing": {
                "requested": requested_model,
                "used": None,
                "backend": "dedicated",
                "reason": reason,
                "policy_decision": {
                    "decision": decision,
                    "model": requested_model,
                    "state": state,
                    "next_step": next_step,
                },
            },
            "dedicated": lifecycle,
            "digitalocean": do_health,
            "lifecycle": {
                "requested_model": requested_model,
                "state": lifecycle.get("state"),
                "server_id": cfg.get("inference_id"),
                "region": lifecycle.get("region"),
                "model_slug": lifecycle.get("model_slug"),
                "accelerator_slug": lifecycle.get("accelerator_slug"),
                "endpoint_ready": bool(self.endpoint(cfg)),
                "access_token_ready": bool(cfg.get("access_token")),
                "build_age_seconds": lifecycle.get("build_age_seconds"),
                "status_age_seconds": lifecycle.get("status_age_seconds"),
                "last_error": lifecycle.get("last_error") or "",
                "next_step": next_step,
            },
        }

    def model_entry(self, cfg, enabled=None):
        """Build the global registry entry for the Dedicated model.

        The model registry (config/models.json) is a git-tracked file, so this
        entry carries only non-sensitive routing facts (ADR-0005 / GOVERNANCE:
        endpoint FQDNs, inference ids, and raw DigitalOcean payloads are
        sensitive operational metadata). The live identifiers stay solely in the
        runtime Dedicated config under the cache dir — save_config() — which is
        what chat routing and the proxy already read; nothing may resolve the
        endpoint or server id from the registry entry."""
        hourly = float(cfg.get("price_per_hour") or 0)
        active = cfg.get("state") == "active" and bool(self.endpoint(cfg))
        if enabled is None:
            enabled = active
        return {
            "id": cfg.get("model_id") or "dedicated-inference",
            "display_name": cfg.get("display_name") or "Dedicated Inference",
            "type": "text",
            "provider": "DigitalOcean Dedicated",
            "enabled": bool(enabled),
            "aliases": ["dedicated", "dedicated-inference"],
            "pricing": {"input": 0, "output": 0, "hourly": hourly},
            "context_window": int(cfg.get("context_window") or 0),
            "state": cfg.get("state") or "not_configured",
            "dedicated": {
                "managed": True,
                "state": cfg.get("state") or "not_configured",
                "region": cfg.get("region") or "",
                "model_slug": cfg.get("model_slug") or "",
                "accelerator_slug": cfg.get("accelerator_slug") or "",
                "scale": int(cfg.get("scale") or 1),
                "hourly_usd": hourly,
            },
        }

    def register_model(self, cfg, enabled=None):
        entry = self.model_entry(cfg, enabled=enabled)
        models = self.load_model_registry(include_disabled=True)
        existing = next((m for m in models if m.get("id") == entry["id"]), None)
        # register_model runs on every remote state refresh (browser poll and the
        # headless worker). Skip the registry write when the entry is unchanged so
        # a status poll no longer churns the governance-locked registry file.
        if existing == entry:
            return entry
        models = [m for m in models if m.get("id") != entry["id"]]
        models.append(entry)
        self.save_model_registry(models)
        self.refresh_model_globals()
        self.append_event("registering_model", "Updated Dedicated model registry entry", "success", {"model_id": entry["id"], "enabled": entry["enabled"], "state": entry.get("state")})
        return entry

    def remove_model(self, cfg):
        model_id = cfg.get("model_id") or "dedicated-inference"
        models = [m for m in self.load_model_registry(include_disabled=True) if m.get("id") != model_id]
        self.save_model_registry(models)
        self.refresh_model_globals()
        self.append_event("tearing_down", "Removed Dedicated model from global registry", "warning", {"model_id": model_id})

    def preflight(self, data=None):
        cfg = self.load_config()
        cfg.update({k: v for k, v in (data or {}).items() if k in self.default_config})
        errors = []
        warnings = []
        if not self.digitalocean_token():
            errors.append("Set DIGITALOCEAN_TOKEN or DIGITALOCEAN_TOKEN_FILE for Dedicated Inference automation.")
        for key, label in (("name", "Name"), ("region", "Region"), ("vpc_uuid", "VPC UUID"), ("model_slug", "Model slug"), ("model_provider", "Model provider"), ("accelerator_slug", "Accelerator slug")):
            if not str(cfg.get(key) or "").strip():
                errors.append("%s is required." % label)
        if cfg.get("region") not in {"atl1", "nyc2", "tor1"}:
            warnings.append("DigitalOcean currently documents Dedicated Inference regions as atl1, nyc2, and tor1.")
        budget = float(cfg.get("daily_budget_usd") or 0)
        hourly = float(cfg.get("price_per_hour") or 0)
        if budget and hourly and hourly > budget:
            warnings.append("Selected hourly cost exceeds the configured daily budget.")
        budget_state = self.budget_state(cfg)
        if budget_state["warning"]:
            warnings.append("Dedicated daily budget is at %.2f%% of the configured limit." % budget_state["percent"])
        return {"ok": not errors, "errors": errors, "warnings": warnings, "config": self.public_payload(cfg)}

    def value_in_payload(self, payload, needle):
        needle = str(needle or "").strip().lower()
        if not needle:
            return False
        if isinstance(payload, dict):
            return any(self.value_in_payload(value, needle) for value in payload.values())
        if isinstance(payload, list):
            return any(self.value_in_payload(value, needle) for value in payload)
        return str(payload or "").strip().lower() == needle

    def capacity_plan(self, data=None):
        cfg = self.load_config()
        cfg.update({k: v for k, v in (data or {}).items() if k in self.default_config})
        now = self.clock()
        try:
            hourly = max(0.0, float(cfg.get("price_per_hour") or 0.0))
        except (TypeError, ValueError):
            hourly = 0.0
        try:
            projected_daily_serverless = float((data or {}).get("projected_serverless_daily_usd") or 0.0)
        except (TypeError, ValueError):
            projected_daily_serverless = 0.0
        if not projected_daily_serverless:
            today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
            projected_daily_serverless = float((self.local_usage_report(today - datetime.timedelta(days=1), today) or {}).get("total_usd") or 0.0)
        dedicated_daily = round(hourly * 24.0, 8)
        dedicated_monthly = round(hourly * 24.0 * 30.0, 8)
        delta_daily = round(dedicated_daily - projected_daily_serverless, 8)
        idle_policy = self.idle_policy_state(cfg, now)
        idle_teardown_hours = round(float(idle_policy.get("teardown_seconds") or 0) / 3600.0, 4)
        idle_window_cost = round(hourly * idle_teardown_hours, 8)
        preflight = self.preflight(cfg)
        health = self.digitalocean_health_snapshot() or {}
        token = self.digitalocean_token()
        sizes = {"status": 0, "ok": False, "payload": {}, "error": "DigitalOcean token is not configured"}
        gpu_config = {"status": 0, "ok": False, "payload": {}, "error": "DigitalOcean token is not configured"}
        if token:
            size_status, size_payload = self.do_request("/v2/dedicated-inferences/sizes", token, method="GET", timeout=60)
            gpu_status, gpu_payload = self.do_request("/v2/dedicated-inferences/gpu-model-config", token, method="GET", timeout=60)
            sizes = {"status": int(size_status), "ok": int(size_status) < 400, "payload": size_payload if isinstance(size_payload, dict) else {}, "error": "" if int(size_status) < 400 else json.dumps(size_payload)[:500]}
            gpu_config = {"status": int(gpu_status), "ok": int(gpu_status) < 400, "payload": gpu_payload if isinstance(gpu_payload, dict) else {}, "error": "" if int(gpu_status) < 400 else json.dumps(gpu_payload)[:500]}
        region = str(cfg.get("region") or "")
        accelerator = str(cfg.get("accelerator_slug") or "")
        model_slug = str(cfg.get("model_slug") or "")
        region_known = region in {"atl1", "nyc2", "tor1"}
        gpu_seen = self.value_in_payload(sizes.get("payload"), accelerator) or self.value_in_payload(gpu_config.get("payload"), accelerator)
        model_seen = self.value_in_payload(gpu_config.get("payload"), model_slug)
        capacity_uncertain = not token or not sizes["ok"] or not gpu_config["ok"] or not gpu_seen or not model_seen
        notes = []
        if not hourly:
            notes.append("Dedicated hourly price is missing; cost comparison is incomplete.")
        if capacity_uncertain:
            notes.append("Live capacity or GPU/model fit is uncertain from DigitalOcean discovery.")
        if not region_known:
            notes.append("Region is outside the currently documented Dedicated Inference regions.")
        if (health.get("account") or {}).get("status") not in {None, "active", "ok"}:
            notes.append("DigitalOcean account status may block Dedicated capacity.")
        if (health.get("prepay") or {}).get("status") == "payment_due":
            notes.append("DigitalOcean billing/prepay status needs attention before build.")
        recommendation = "build" if preflight["ok"] and hourly and not capacity_uncertain and delta_daily <= 0 else "review"
        if not preflight["ok"] or not token:
            recommendation = "blocked"
        elif hourly and projected_daily_serverless and delta_daily > 0:
            recommendation = "prefer_serverless"
        return {
            "generated_at": now,
            "recommendation": recommendation,
            "config": self.public_payload(cfg),
            "cost": {
                "hourly_usd": round(hourly, 8),
                "daily_usd": dedicated_daily,
                "monthly_30d_usd": dedicated_monthly,
                "idle_teardown_hours": idle_teardown_hours,
                "idle_window_cost_usd": idle_window_cost,
            },
            "serverless_comparison": {
                "projected_daily_usd": round(projected_daily_serverless, 8),
                "break_even_daily_serverless_usd": dedicated_daily,
                "delta_daily_usd": delta_daily,
                "dedicated_cheaper": bool(projected_daily_serverless and delta_daily <= 0),
            },
            "capacity": {
                "region": region,
                "region_known": region_known,
                "accelerator_slug": accelerator,
                "accelerator_seen": bool(gpu_seen),
                "model_slug": model_slug,
                "model_seen": bool(model_seen),
                "uncertain": capacity_uncertain,
                "sizes_status": sizes["status"],
                "gpu_model_config_status": gpu_config["status"],
            },
            "readiness": {
                "preflight": preflight,
                "account": health.get("account") if isinstance(health, dict) else None,
                "billing": health.get("prepay") if isinstance(health, dict) else None,
            },
            "fallback": {
                "model": cfg.get("fallback_model") or self.default_text_model(),
                "active_text_models": self.active_text_models(),
            },
            "uncertainty_notes": notes,
            "live_discovery": {"sizes": sizes, "gpu_model_config": gpu_config},
        }

    def update_from_resource(self, cfg, resource):
        status = str(resource.get("status") or cfg.get("state") or "provisioning")
        endpoints = resource.get("endpoints") if isinstance(resource.get("endpoints"), dict) else {}
        cfg["raw"] = resource
        cfg["last_status_at"] = self.clock()
        latest_public = endpoints.get("public_endpoint_fqdn") or resource.get("public_endpoint_fqdn") or ""
        latest_private = endpoints.get("private_endpoint_fqdn") or resource.get("private_endpoint_fqdn") or ""
        cfg["public_endpoint_fqdn"] = latest_public or (cfg.get("public_endpoint_fqdn") if status in {"active", "ready"} else "")
        cfg["private_endpoint_fqdn"] = latest_private or (cfg.get("private_endpoint_fqdn") if status in {"active", "ready"} else "")
        if status in {"active", "ready"}:
            cfg["state"] = "active"
            if not cfg.get("run_started_at"):
                cfg["run_started_at"] = self.clock()
            if not cfg.get("last_work_at"):
                cfg["last_work_at"] = cfg["run_started_at"]
        elif status in {"deleting", "deleted"}:
            cfg["state"] = "tearing_down" if status == "deleting" else "deleted"
        elif status == "error":
            cfg["state"] = "failed"
            cfg["last_error"] = resource.get("error") or "DigitalOcean reported error state"
        elif status:
            cfg["state"] = status
        issue = self.resource_issue(resource)
        if issue:
            cfg["state"] = "failed"
            cfg["last_error"] = issue
        elif str(cfg.get("last_error") or "").startswith("DigitalOcean marked "):
            cfg["last_error"] = ""
        return cfg

    def resource_issue(self, resource):
        if not isinstance(resource, dict):
            return ""
        specs = []
        for key in ("pending_deployment_spec", "deployment_spec", "current_deployment_spec", "spec"):
            if isinstance(resource.get(key), dict):
                specs.append(resource[key])
        for spec in specs:
            spec_state = str(spec.get("status") or spec.get("state") or "").strip().lower()
            for deployment in spec.get("model_deployments") or []:
                if not isinstance(deployment, dict):
                    continue
                model_slug = deployment.get("model_slug") or deployment.get("provider_model_id") or "model"
                for accelerator in deployment.get("accelerators") or []:
                    if not isinstance(accelerator, dict):
                        continue
                    state = str(accelerator.get("status") or accelerator.get("state") or "").strip().lower()
                    if state in {"invalid", "error", "failed"}:
                        if spec_state in {"", "pending", "provisioning"} and not accelerator.get("accelerator_id"):
                            continue
                        slug = accelerator.get("accelerator_slug") or accelerator.get("accelerator_id") or "accelerator"
                        return "DigitalOcean marked %s for %s as %s. Rebuild with another available GPU or region." % (slug, model_slug, state)
        return ""

    def refresh_remote_state(self, cfg):
        """Poll DigitalOcean for the live inference state and reconcile local config.
        Shared by status_payload (browser poll) and reconcile (headless worker) so
        lifecycle advancement and health tracking never depend on a browser page
        staying open (a GOVERNANCE cost-safety lock). Returns the updated cfg; a
        no-op when there is no token or no live inference to poll."""
        token = self.digitalocean_token()
        if not (token and cfg.get("inference_id") and cfg.get("state") not in {"deleted", "not_configured"}):
            return cfg
        status, response = self.do_request("/v2/dedicated-inferences/%s" % quote(str(cfg["inference_id"]), safe=""), token, method="GET")
        if status < 400:
            previous = cfg.get("state")
            cfg = self.update_from_resource(cfg, self.extract_resource(response))
            cfg = self.record_health_success(cfg)
            if cfg.get("state") != previous:
                self.append_event(cfg.get("state"), "DigitalOcean state changed to %s" % cfg.get("state"), "info", {"previous": previous})
            if cfg.get("state") == "active" and not cfg.get("access_token"):
                cfg, _ = self.create_token(cfg)
            if cfg.get("inference_id") and cfg.get("state") not in {"deleted", "not_configured", "tearing_down"}:
                self.register_model(cfg)
            self.save_config(cfg)
        else:
            error = json.dumps(response)[:1000]
            cfg = self.record_health_failure(cfg, error, {"status": status, "response": response})
            self.save_config(cfg)
            self.append_event("status", "Failed to refresh Dedicated status", "error", {"status": status, "response": response})
        return cfg

    def status_payload(self, poll=True):
        cfg = self.load_config()
        if poll:
            cfg = self.refresh_remote_state(cfg)
        return {"dedicated": self.public_payload(cfg), "events": self.events(), "models": self.models_payload(), "digitalocean": self.digitalocean_health_snapshot()}

    def reconcile(self):
        """Headless lifecycle tick for the background policy worker: refresh the
        live DigitalOcean state (advancing provisioning->active, recording health
        failures) and then apply idle/unhealthy/budget policy. Without the refresh
        step, enforce_policy only sees stale local state and idle/unhealthy
        teardown never fires unless a browser is polling the status endpoint."""
        cfg = self.load_config()
        self.refresh_remote_state(cfg)
        return self.enforce_policy()

    def create_token(self, cfg):
        token = self.digitalocean_token()
        if not token or not cfg.get("inference_id"):
            return cfg, None
        status, response = self.do_request("/v2/dedicated-inferences/%s/tokens" % quote(str(cfg["inference_id"]), safe=""), token, {"name": "matts-console"}, method="POST")
        if status < 400:
            item = self.extract_resource(response)
            token_value = item.get("token")
            if isinstance(token_value, dict):
                token_value = token_value.get("value") or token_value.get("access_key") or token_value.get("token")
            cfg["access_token"] = token_value or item.get("access_key") or item.get("value") or cfg.get("access_token") or ""
            self.append_event("token_issuing", "Dedicated access token created", "success")
        else:
            self.append_event("token_issuing", "Dedicated access token creation failed", "warning", {"status": status, "response": response})
        return cfg, {"status": status, "response": response}

    def build(self, data):
        data = data or {}
        cfg = self.load_config()
        for key in self.default_config:
            if key in data:
                cfg[key] = data[key]
        cfg["scale"] = max(1, int(cfg.get("scale") or 1))
        cfg["price_per_hour"] = float(cfg.get("price_per_hour") or 0)
        cfg["daily_budget_usd"] = float(cfg.get("daily_budget_usd") or 0)
        # Idempotency guard: never POST a second /v2/dedicated-inferences while a
        # billing server is already live or in flight. A double build (double
        # click, retry, or concurrent session) would overwrite inference_id and
        # orphan the first GPU server with no teardown path. The operator must
        # tear down first, or pass rebuild=true to intentionally replace it.
        current_state = str(cfg.get("state") or "")
        has_live_server = bool(cfg.get("inference_id")) and current_state not in {"deleted", "not_configured", "failed", ""}
        live_in_flight = current_state in {"creating", "provisioning", "active", "idle_warning", "draining", "cooldown", "tearing_down"}
        if (has_live_server or live_in_flight) and not bool(data.get("rebuild")):
            message = (
                "A Dedicated Inference server is already %s (inference_id=%s). Refusing to build a "
                "second billing server; tear it down first, or resend with rebuild=true to replace it."
                % (current_state or "provisioned", cfg.get("inference_id") or "unknown")
            )
            self.append_event("build_blocked", message, "warning", {"state": current_state, "inference_id": cfg.get("inference_id")})
            return HTTPStatus.CONFLICT, {"error": message, "message": message, "dedicated": self.public_payload(cfg)}
        preflight = self.preflight(cfg)
        self.append_event("preflight", "Checking DigitalOcean permissions and required fields", "info", {"ok": preflight["ok"]})
        if not preflight["ok"]:
            cfg["state"] = "failed"
            cfg["last_error"] = "; ".join(preflight["errors"])
            self.save_config(cfg)
            return HTTPStatus.BAD_REQUEST, {"error": cfg["last_error"], "preflight": preflight, "dedicated": self.public_payload(cfg)}
        budget_state = self.budget_state(cfg)
        budget_policy_decision = self.policy_service.dedicated_build_budget_decision(budget_state, cfg=cfg).to_dict()
        budget_override = bool(data.get("budget_override") or data.get("override_budget"))
        if budget_state["critical"] and not budget_override:
            message = "Dedicated build blocked because the daily budget is at %.2f%% of the configured limit. Use a Serverless fallback or explicitly override the budget guard." % budget_state["percent"]
            cfg["last_error"] = message
            self.save_config(cfg)
            self.append_event("budget_blocked", message, "warning", {
                "budget_state": budget_state,
                "model_id": cfg.get("model_id"),
                "model_slug": cfg.get("model_slug"),
                "region": cfg.get("region"),
                "accelerator_slug": cfg.get("accelerator_slug"),
                "fallback_model": cfg.get("fallback_model"),
                "policy_decision": budget_policy_decision,
            })
            return HTTPStatus.PAYMENT_REQUIRED, {"error": message, "message": message, "budget_state": budget_state, "policy_decision": budget_policy_decision, "preflight": preflight, "dedicated": self.public_payload(cfg)}
        if budget_state["critical"] and budget_override:
            budget_policy_decision["overrides"] = {"budget_override": True, "operator": data.get("operator") or data.get("session_id") or data.get("console_token") or "console-token-user"}
            self.append_event("budget_override", "Dedicated daily budget guard overridden for build", "warning", {
                "budget_state": budget_state,
                "model_id": cfg.get("model_id"),
                "model_slug": cfg.get("model_slug"),
                "region": cfg.get("region"),
                "accelerator_slug": cfg.get("accelerator_slug"),
                "price_per_hour": cfg.get("price_per_hour"),
                "fallback_model": cfg.get("fallback_model"),
                "operator": data.get("operator") or data.get("session_id") or data.get("console_token") or "console-token-user",
                "policy_decision": budget_policy_decision,
            })
        cfg["state"] = "creating"
        cfg["created_at"] = self.clock()
        cfg["run_started_at"] = 0
        cfg["last_work_at"] = 0
        cfg["last_error"] = ""
        self.save_config(cfg)
        self.append_event("planning", "Build plan accepted", "info", {"region": cfg["region"], "model_slug": cfg["model_slug"], "accelerator_slug": cfg["accelerator_slug"]})
        payload = {
            "spec": {
                "version": int(cfg.get("version") or 1),
                "name": cfg["name"],
                "region": cfg["region"],
                "vpc": {"uuid": cfg["vpc_uuid"]},
                "enable_public_endpoint": bool(cfg.get("enable_public_endpoint")),
                "model_deployments": [{
                    "name": cfg.get("deployment_name") or "primary",
                    "model_slug": cfg["model_slug"],
                    "model_provider": cfg["model_provider"],
                    "accelerators": [{
                        "scale": int(cfg.get("scale") or 1),
                        "type": cfg.get("accelerator_type") or "gpu",
                        "accelerator_slug": cfg["accelerator_slug"],
                    }],
                }],
            },
        }
        self.append_event("creating", "Requesting Dedicated Inference capacity", "info", {"payload": payload})
        status, response = self.do_request("/v2/dedicated-inferences", self.digitalocean_token(), payload, method="POST", timeout=120)
        cfg["raw"] = response
        if status >= 400:
            cfg["state"] = "failed"
            cfg["last_error"] = json.dumps(response)[:1200]
            self.save_config(cfg)
            self.append_event("failed", "DigitalOcean rejected Dedicated build", "error", {"status": status, "response": response})
            return status, {"error": cfg["last_error"], "response": response, "dedicated": self.public_payload(cfg)}
        cfg["inference_id"] = self.extract_id(response)
        create_token = response.get("token") if isinstance(response, dict) and isinstance(response.get("token"), dict) else {}
        if create_token.get("value"):
            cfg["access_token"] = create_token.get("value")
        cfg["state"] = "provisioning"
        self.save_config(cfg)
        self.register_model(cfg, enabled=False)
        self.append_event("provisioning", "Dedicated Inference creation accepted by DigitalOcean", "success", {"inference_id": cfg.get("inference_id"), "status": status})
        if cfg.get("inference_id") and not cfg.get("access_token"):
            cfg, _ = self.create_token(cfg)
            self.save_config(cfg)
        return HTTPStatus.ACCEPTED, self.status_payload(poll=True)

    def teardown(self, data=None):
        cfg = self.load_config()
        self.remove_model(cfg)
        cfg["state"] = "tearing_down"
        cfg["last_error"] = ""
        self.save_config(cfg)
        token = self.digitalocean_token()
        status = HTTPStatus.ACCEPTED
        response = {"ok": True, "note": "No Dedicated inference id was configured."}
        if token and cfg.get("inference_id"):
            self.append_event("tearing_down", "Destroying Dedicated Inference immediately", "warning", {"inference_id": cfg["inference_id"]})
            status, response = self.do_request("/v2/dedicated-inferences/%s" % quote(str(cfg["inference_id"]), safe=""), token, method="DELETE", timeout=60)
        if int(status) >= 400:
            cfg["state"] = "failed"
            cfg["last_error"] = json.dumps(response)[:1200]
            self.append_event("failed", "Dedicated teardown failed", "error", {"status": int(status), "response": response})
        else:
            cfg["state"] = "deleted"
            cfg["inference_id"] = ""
            cfg["access_token"] = ""
            cfg["public_endpoint_fqdn"] = ""
            cfg["private_endpoint_fqdn"] = ""
            cfg["run_started_at"] = 0
            cfg["last_work_at"] = 0
            self.append_event("deleted", "Dedicated model removed and teardown requested", "success", {"response": response})
        self.save_config(cfg)
        return status, self.status_payload(poll=False)

    def policy(self, data):
        cfg = self.load_config()
        for key in ("daily_budget_usd", "warning_threshold", "cooldown_threshold", "idle_warning_seconds", "idle_teardown_seconds", "unhealthy_teardown_seconds", "auto_rebuild", "fallback_model"):
            if key in data:
                cfg[key] = data[key]
        cfg["daily_budget_usd"] = float(cfg.get("daily_budget_usd") or 0)
        cfg["warning_threshold"] = float(cfg.get("warning_threshold") or 0.8)
        cfg["cooldown_threshold"] = float(cfg.get("cooldown_threshold") or 0.95)
        cfg["idle_warning_seconds"] = int(cfg.get("idle_warning_seconds") or 300)
        cfg["idle_teardown_seconds"] = int(cfg.get("idle_teardown_seconds") or 600)
        cfg["unhealthy_teardown_seconds"] = int(cfg.get("unhealthy_teardown_seconds") or 300)
        self.save_config(cfg)
        self.append_event("policy", "Dedicated policy updated", "success", {"policy": self.public_payload(cfg)})
        return HTTPStatus.OK, self.status_payload(poll=False)

    def discovery(self, path):
        token = self.digitalocean_token()
        if not token:
            return HTTPStatus.BAD_REQUEST, {"error": "DigitalOcean token is not configured"}
        status, response = self.do_request(path, token, method="GET", timeout=60)
        return status, response

    def is_model(self, model):
        cfg = self.load_config()
        return bool(model and model == cfg.get("model_id"))

    def chat_completion(self, data, cfg):
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        fallback_model = cfg.get("fallback_model")
        fallback = fallback_model if fallback_model in self.active_text_models() else self.default_text_model()
        endpoint = self.endpoint(cfg)
        unhealthy_policy = self.unhealthy_policy_state(cfg)
        if unhealthy_policy["unhealthy"]:
            message = "Dedicated Inference is marked unhealthy after repeated failed checks. Use the Serverless fallback '%s' or wait for recovery; teardown will occur in %s seconds if health does not recover." % (fallback, unhealthy_policy["teardown_countdown_seconds"])
            return HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": message,
                "message": message,
                "routing": {
                    "requested": data.get("model"),
                    "used": None,
                    "backend": "dedicated",
                    "reason": "dedicated_unhealthy",
                    "fallback_model": fallback,
                    "unhealthy_policy": unhealthy_policy,
                },
                "dedicated": self.public_payload(cfg),
            }
        budget_state = self.budget_state(cfg)
        if budget_state["critical"]:
            policy_decision = self.policy_service.dedicated_build_budget_decision(budget_state, cfg=cfg).to_dict()
            notice = "Dedicated Inference is over the configured daily budget guard, so this request was routed to %s instead." % fallback
            self.append_event("budget_blocked_fallback", notice, "warning", {
                "budget_state": budget_state,
                "requested": data.get("model"),
                "fallback_model": fallback,
                "policy_decision": policy_decision,
            })
            status, fallback_payload = self.serverless_chat_completion(data, fallback, allow_unregistered=True)
            if isinstance(fallback_payload, dict):
                fallback_payload["notice"] = notice
                fallback_payload["pre_reply_notice"] = notice
                fallback_payload["routing"] = {
                    "requested": data.get("model"),
                    "used": fallback,
                    "reason": "budget_blocked_fallback",
                    "backend": "serverless",
                    "budget_state": budget_state,
                    "policy_decision": {**policy_decision, "action": "budget_blocked_fallback", "subject": {**policy_decision.get("subject", {}), "fallback_model": fallback}},
                }
            return status, fallback_payload
        if cfg.get("state") != "active" or not endpoint or not cfg.get("access_token"):
            payload = self.not_ready_payload(cfg, data.get("model"))
            self.append_event("waiting", "Dedicated request blocked because endpoint is not ready", "warning", payload.get("lifecycle"))
            return HTTPStatus.CONFLICT, payload
        payload = {
            "model": cfg.get("model_slug") or data.get("model"),
            "messages": messages,
            "max_tokens": max(1, min(8192, int(data.get("max_tokens") or 512))),
            "stream": False,
        }
        if "qwen3" in str(cfg.get("model_slug") or "").lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if data.get("temperature") not in (None, ""):
            payload["temperature"] = float(data["temperature"])
        req = Request(endpoint + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={
            "content-type": "application/json",
            "authorization": "Bearer " + cfg.get("access_token"),
            "user-agent": "matts-console/1.0",
        }, method="POST")
        try:
            with urlopen(req, timeout=240) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode("utf-8", errors="replace"))
            except ValueError:
                error = {"error": exc.reason}
            cfg = self.record_health_failure(cfg, json.dumps(error)[:1000], {"status": exc.code, "response": error})
            self.save_config(cfg)
            self.append_event("fallback", "Dedicated request failed; routed chat to Serverless", "warning", {"status": exc.code, "response": error})
            status, fallback_payload = self.serverless_chat_completion(data, fallback, allow_unregistered=True)
            if isinstance(fallback_payload, dict):
                fallback_payload["routing"] = {"requested": data.get("model"), "used": fallback, "reason": "dedicated_request_failed_fallback", "backend": "serverless", "policy_decision": {"decision": "dedicated_request_failed_fallback", "model": data.get("model"), "fallback_model": fallback, "status": exc.code}}
            return status, fallback_payload
        except URLError as exc:
            cfg = self.record_health_failure(cfg, str(exc.reason), {"error": str(exc.reason)})
            self.save_config(cfg)
            self.append_event("fallback", "Dedicated endpoint unreachable; routed chat to Serverless", "warning", {"error": str(exc.reason)})
            status, fallback_payload = self.serverless_chat_completion(data, fallback, allow_unregistered=True)
            if isinstance(fallback_payload, dict):
                fallback_payload["routing"] = {"requested": data.get("model"), "used": fallback, "reason": "dedicated_unreachable_fallback", "backend": "serverless", "policy_decision": {"decision": "dedicated_unreachable_fallback", "model": data.get("model"), "fallback_model": fallback}}
            return status, fallback_payload
        text = ""
        choices = raw.get("choices") if isinstance(raw, dict) else []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
            text = message.get("content") or choices[0].get("text") or ""
        cfg["last_work_at"] = self.clock()
        cfg["idle_warning_started_at"] = 0
        cfg = self.record_health_success(cfg)
        self.save_config(cfg)
        self.append_event("active", "Dedicated served chat request", "success", {"model": cfg.get("model_id")})
        usage = raw.get("usage") if isinstance(raw, dict) else {}
        return HTTPStatus.OK, {"text": text, "raw": raw, "usage": usage or {}, "cost": {"total_cost_usd": self.cost_usd(cfg)}, "routing": {"requested": data.get("model"), "used": cfg.get("model_id"), "backend": "dedicated", "policy_decision": {"decision": "dedicated_online_preference", "model": cfg.get("model_id"), "state": cfg.get("state")}}}
