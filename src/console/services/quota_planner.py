"""Quota planning and accounting for console API actions."""
import calendar
import json
import time

from src.console.policy import PolicyService


ACTION_PATHS = {
    "/api/chat": "chat",
    "/api/chat/compare": "comparison",
    "/api/evals/run": "eval",
    "/api/generate": "image",
    "/api/dedicated/build": "dedicated",
    "/api/dedicated/resume": "dedicated",
    "/api/test-models": "smoke_test",
}


class QuotaPlannerService:
    """Evaluate request quota policy and append a compact usage ledger."""

    def __init__(self, config=None, quota_file=None, append_audit=None, append_trace=None, clock=None, policy_service=None):
        self.config = config or {}
        self.quota_file = quota_file
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.append_trace = append_trace or (lambda record: record)
        self.clock = clock or time.time
        self.policy_service = policy_service or PolicyService()

    def enabled(self):
        return bool(self.config.get("enabled", False))

    def warn_fraction(self):
        try:
            return min(1.0, max(0.0, float(self.config.get("warn_fraction", 0.8))))
        except (TypeError, ValueError):
            return 0.8

    def managed_action(self, path, data=None):
        data = data if isinstance(data, dict) else {}
        action = str(data.get("action") or "").strip()
        if action:
            return action
        return ACTION_PATHS.get(str(path or ""))

    def request_payload(self, data):
        data = data if isinstance(data, dict) else {}
        payload = data.get("payload")
        if isinstance(payload, dict):
            merged = dict(payload)
            for key in ("forecast", "actor", "session_id"):
                if key in data and key not in merged:
                    merged[key] = data[key]
            return merged
        return data

    def forecast_usd(self, data):
        data = data if isinstance(data, dict) else {}
        forecast = data.get("forecast") if isinstance(data.get("forecast"), dict) else None
        if forecast is None and isinstance(data.get("payload"), dict):
            forecast = data.get("payload", {}).get("forecast") if isinstance(data.get("payload", {}).get("forecast"), dict) else None
        if forecast is None:
            forecast = data
        for key in ("estimated_total_usd", "projected_total_usd", "hourly_usd", "total_cost_usd"):
            try:
                value = float((forecast or {}).get(key))
            except (TypeError, ValueError, AttributeError):
                continue
            if value >= 0:
                return value
        return 0.0

    def models_for(self, data):
        data = self.request_payload(data)
        models = []
        raw = data.get("models")
        if isinstance(raw, list):
            models.extend(str(model).strip() for model in raw if str(model or "").strip())
        for key in ("model", "model_id", "model_slug"):
            value = str(data.get(key) or "").strip()
            if value:
                models.append(value)
        seen = set()
        unique = []
        for model in models:
            if model not in seen:
                unique.append(model)
                seen.add(model)
        return unique

    def project_for(self, data):
        data = self.request_payload(data)
        for key in ("project", "project_id", "workspace", "project_dir"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return ""

    def actor_for(self, actor=None, actor_key="", data=None):
        data = data if isinstance(data, dict) else {}
        actor = actor if isinstance(actor, dict) else data.get("actor") if isinstance(data.get("actor"), dict) else {}
        roles = actor.get("roles") if isinstance(actor.get("roles"), list) else []
        roles = [str(role) for role in roles if str(role or "").strip()] or ["anonymous"]
        return {
            "actor_id": str(actor.get("id") or "anonymous"),
            "actor_source": str(actor.get("source") or "unknown"),
            "actor_roles": roles,
            "actor_key": str(actor_key or actor.get("fingerprint") or actor.get("id") or "anonymous"),
        }

    def units_for(self, path, data=None):
        data = data if isinstance(data, dict) else {}
        action = self.managed_action(path, data) or "unknown"
        return {
            "action": action,
            "requests": 1.0,
            "usd": self.forecast_usd(data),
            "models": self.models_for(data),
            "project": self.project_for(data),
            "route": str(path or ""),
        }

    def window_start(self, name, now=None):
        now = float(self.clock() if now is None else now)
        if name == "monthly":
            tm = time.gmtime(now)
            return float(calendar.timegm((tm.tm_year, tm.tm_mon, 1, 0, 0, 0)))
        return float(int(now // 86400) * 86400)

    def reset_at(self, name, now=None):
        now = float(self.clock() if now is None else now)
        if name == "monthly":
            tm = time.gmtime(now)
            year, month = tm.tm_year, tm.tm_mon + 1
            if month == 13:
                year, month = year + 1, 1
            return int(calendar.timegm((year, month, 1, 0, 0, 0)))
        return int(self.window_start("daily", now) + 86400)

    def read_entries(self):
        if self.quota_file is None:
            return []
        path = self.quota_file()
        if not path.exists():
            return []
        rows = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return rows
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def append_entry(self, record):
        if self.quota_file is None:
            return
        path = self.quota_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def policy_sources(self, actor, units):
        policies = []
        default = self.config.get("default_policy") if isinstance(self.config.get("default_policy"), dict) else {}
        if default:
            policies.append(("default", "default", default))
        roles = self.config.get("roles") if isinstance(self.config.get("roles"), dict) else {}
        for role in actor["actor_roles"]:
            policy = roles.get(role)
            if isinstance(policy, dict):
                policies.append(("role", role, policy))
        actions = self.config.get("actions") if isinstance(self.config.get("actions"), dict) else {}
        policy = actions.get(units["action"])
        if isinstance(policy, dict):
            policies.append(("action", units["action"], policy))
        models = self.config.get("models") if isinstance(self.config.get("models"), dict) else {}
        if isinstance(models.get("*"), dict) and units["models"]:
            policies.append(("model", "*", models["*"]))
        for model in units["models"]:
            if isinstance(models.get(model), dict):
                policies.append(("model", model, models[model]))
        projects = self.config.get("projects") if isinstance(self.config.get("projects"), dict) else {}
        if units["project"] and isinstance(projects.get(units["project"]), dict):
            policies.append(("project", units["project"], projects[units["project"]]))
        return policies

    def entry_matches(self, entry, actor, units, source, name):
        if str(entry.get("actor_key") or "") != actor["actor_key"]:
            return False
        if source == "default":
            return True
        if source == "role":
            return name in (entry.get("actor_roles") or [])
        if source == "action":
            return str(entry.get("action") or "") == units["action"]
        if source == "model":
            return bool(set(entry.get("models") or [entry.get("model") or ""]) & set(units["models"])) if name == "*" else name in (entry.get("models") or [entry.get("model") or ""])
        if source == "project":
            return str(entry.get("project") or "") == units["project"]
        return False

    def usage_for(self, entries, actor, units, source, name, window):
        start = self.window_start(window)
        totals = {"requests": 0.0, "usd": 0.0}
        for entry in entries:
            try:
                ts = float(entry.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            if ts < start or not self.entry_matches(entry, actor, units, source, name):
                continue
            totals["requests"] += float(entry.get("requests") or 0)
            totals["usd"] += float(entry.get("usd") or 0)
        return totals

    def evaluate_policy(self, actor, units, source, name, policy, entries):
        checks = []
        warnings = []
        blocks = []
        for window in ("daily", "monthly"):
            window_policy = policy.get(window)
            if not isinstance(window_policy, dict):
                continue
            used = self.usage_for(entries, actor, units, source, name, window)
            for metric in ("requests", "usd"):
                if metric not in window_policy:
                    continue
                try:
                    limit = float(window_policy.get(metric))
                except (TypeError, ValueError):
                    continue
                if limit <= 0:
                    continue
                requested = float(units.get(metric) or 0)
                projected = used[metric] + requested
                remaining = max(0.0, limit - projected)
                check = {
                    "source": source,
                    "name": name,
                    "window": window,
                    "metric": metric,
                    "limit": limit,
                    "used": round(used[metric], 8),
                    "requested": round(requested, 8),
                    "projected": round(projected, 8),
                    "remaining": round(remaining, 8),
                    "reset_at": self.reset_at(window),
                }
                checks.append(check)
                if projected > limit:
                    blocks.append({"type": "hard_block", **check})
                elif projected >= limit * self.warn_fraction():
                    warnings.append({"type": "soft_warning", **check})
        return checks, warnings, blocks

    def decision(self, path, data=None, actor=None, actor_key="", consume=False):
        data = data if isinstance(data, dict) else {}
        action = self.managed_action(path, data)
        if not self.enabled() or not action:
            decision = {"enabled": self.enabled(), "managed": bool(action), "allowed": True, "warnings": [], "blocks": [], "checks": []}
            decision["policy_decision"] = self.policy_service.quota_decision(decision).to_dict()
            return decision
        actor_info = self.actor_for(actor=actor, actor_key=actor_key, data=data)
        units = self.units_for(path, data)
        entries = self.read_entries()
        checks, warnings, blocks = [], [], []
        for source, name, policy in self.policy_sources(actor_info, units):
            policy_checks, policy_warnings, policy_blocks = self.evaluate_policy(actor_info, units, source, name, policy, entries)
            checks.extend(policy_checks)
            warnings.extend(policy_warnings)
            blocks.extend(policy_blocks)
        status = "blocked" if blocks else "warning" if warnings else "allowed"
        decision = {
            "enabled": True,
            "managed": True,
            "allowed": not blocks,
            "status": status,
            "action": units["action"],
            "route": units["route"],
            "actor": actor_info,
            "models": units["models"],
            "project": units["project"],
            "requests": units["requests"],
            "usd": round(units["usd"], 8),
            "checks": checks,
            "warnings": warnings,
            "blocks": blocks,
        }
        decision["policy_decision"] = self.policy_service.quota_decision(decision).to_dict()
        if consume:
            self.record_decision(decision)
        return decision

    def record_decision(self, decision):
        actor = {
            "id": decision.get("actor", {}).get("actor_id"),
            "roles": decision.get("actor", {}).get("actor_roles") or [],
            "source": decision.get("actor", {}).get("actor_source"),
        }
        outcome = "denied" if not decision.get("allowed") else decision.get("status", "allowed")
        status = 429 if not decision.get("allowed") else 0
        self.append_audit(
            "quota.%s" % decision.get("status", "decision"),
            actor=actor,
            outcome=outcome,
            permission="quota_policy",
            request={
                "action": decision.get("action"),
                "route": decision.get("route"),
                "models": decision.get("models"),
                "project": decision.get("project"),
                "warnings": decision.get("warnings"),
                "blocks": decision.get("blocks"),
            },
            status=status,
        )
        self.append_trace({
            "action": "quota.decision",
            "status": decision.get("status"),
            "http_status": status,
            "requested_model": ",".join(decision.get("models") or []),
            "provider": "local-console",
            "endpoint_mode": "quota",
            "routing_reason": decision.get("action"),
            "actor_id": actor.get("id"),
            "actor_roles": actor.get("roles"),
            "cost_usd": decision.get("usd"),
            "usage": {"requests": decision.get("requests"), "usd": decision.get("usd")},
            "quota": {
                "allowed": decision.get("allowed"),
                "warnings": decision.get("warnings"),
                "blocks": decision.get("blocks"),
                "policy_decision": decision.get("policy_decision"),
            },
        })
        if decision.get("allowed"):
            self.append_entry({
                "ts": self.clock(),
                "actor_key": decision.get("actor", {}).get("actor_key"),
                "actor_id": actor.get("id"),
                "actor_roles": actor.get("roles"),
                "actor_source": actor.get("source"),
                "action": decision.get("action"),
                "route": decision.get("route"),
                "models": decision.get("models"),
                "project": decision.get("project"),
                "requests": decision.get("requests"),
                "usd": decision.get("usd"),
                "status": decision.get("status"),
            })

    def preview(self, path, data=None, actor=None, actor_key=""):
        return self.decision(path, data=data, actor=actor, actor_key=actor_key, consume=False)

    def consume(self, path, data=None, actor=None, actor_key=""):
        return self.decision(path, data=data, actor=actor, actor_key=actor_key, consume=True)

    def payload(self, actor=None, actor_key=""):
        actor_info = self.actor_for(actor=actor, actor_key=actor_key)
        entries = self.read_entries()
        rows = []
        policies = []
        default = self.config.get("default_policy") if isinstance(self.config.get("default_policy"), dict) else {}
        if default:
            policies.append(("default", "default", default))
        roles = self.config.get("roles") if isinstance(self.config.get("roles"), dict) else {}
        for role in actor_info["actor_roles"]:
            if isinstance(roles.get(role), dict):
                policies.append(("role", role, roles[role]))
        for source in ("actions", "models", "projects"):
            configured = self.config.get(source) if isinstance(self.config.get(source), dict) else {}
            for name, policy in configured.items():
                if isinstance(policy, dict):
                    policies.append((source[:-1] if source != "actions" else "action", str(name), policy))
        for source, name, policy in policies:
            for window in ("daily", "monthly"):
                window_policy = policy.get(window) if isinstance(policy, dict) else None
                if not isinstance(window_policy, dict):
                    continue
                units = {"action": name if source == "action" else "", "models": [name] if source == "model" and name != "*" else [], "project": name if source == "project" else "", "route": "", "requests": 0.0, "usd": 0.0}
                used = self.usage_for(entries, actor_info, units, source, name, window)
                for metric in ("requests", "usd"):
                    if metric not in window_policy:
                        continue
                    try:
                        limit = float(window_policy.get(metric))
                    except (TypeError, ValueError):
                        continue
                    rows.append({
                        "source": source,
                        "name": name,
                        "window": window,
                        "metric": metric,
                        "limit": limit,
                        "used": round(used[metric], 8),
                        "remaining": round(max(0.0, limit - used[metric]), 8),
                        "reset_at": self.reset_at(window),
                    })
        return {
            "enabled": self.enabled(),
            "warn_fraction": self.warn_fraction(),
            "actor": actor_info,
            "quotas": rows,
            "recent": list(reversed(entries[-20:])),
            "policy": self.config,
        }
