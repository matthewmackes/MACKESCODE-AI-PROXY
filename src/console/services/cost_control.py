"""Monthly cost burn controls and hard-pause guardrails."""
import datetime
import json
import time


class CostControlService:
    """Build cost-control status and persist monthly threshold/pause state."""

    schema_version = 1
    active_dedicated_states = {"new", "creating", "provisioning", "active", "idle_warning", "draining", "cooldown", "tearing_down"}
    default_payment_items = [
        {"id": "provider_billing_api", "label": "Provider billing API", "status": "open", "detail": "Confirm DigitalOcean billing insights or account prepay data is reachable."},
        {"id": "payment_method", "label": "Payment method", "status": "open", "detail": "Confirm a valid card, prepaid balance, or auto-reload policy is active."},
        {"id": "monthly_thresholds", "label": "Monthly thresholds", "status": "open", "detail": "Confirm workspace, project, model, and provider thresholds match the operating budget."},
        {"id": "pause_override_roles", "label": "Pause override roles", "status": "open", "detail": "Confirm owner, infra_admin, and model_admin override access is intentional."},
    ]

    def __init__(
        self,
        state_file,
        cost_summary_payload,
        local_usage_since,
        load_dedicated_config,
        dedicated_runtime_cost_summary,
        dedicated_teardown=None,
        clock=None,
    ):
        self.state_file = state_file
        self.cost_summary_payload = cost_summary_payload
        self.local_usage_since = local_usage_since
        self.load_dedicated_config = load_dedicated_config
        self.dedicated_runtime_cost_summary = dedicated_runtime_cost_summary
        self.dedicated_teardown = dedicated_teardown
        self.clock = clock or time.time

    def default_state(self):
        return {
            "schema_version": self.schema_version,
            "thresholds": {
                "workspace:default": {
                    "scope_type": "workspace",
                    "scope_id": "default",
                    "monthly_threshold_usd": 0.0,
                    "warning_ratio": 0.80,
                    "hard_ratio": 1.05,
                    "updated_at": 0,
                    "updated_by": "",
                },
                "provider:digitalocean_dedicated": {
                    "scope_type": "provider",
                    "scope_id": "digitalocean_dedicated",
                    "monthly_threshold_usd": 0.0,
                    "warning_ratio": 0.80,
                    "hard_ratio": 1.05,
                    "updated_at": 0,
                    "updated_by": "",
                },
                "provider:llm_service": {
                    "scope_type": "provider",
                    "scope_id": "llm_service",
                    "monthly_threshold_usd": 0.0,
                    "warning_ratio": 0.80,
                    "hard_ratio": 1.05,
                    "updated_at": 0,
                    "updated_by": "",
                },
            },
            "pause": {
                "active": False,
                "reason": "",
                "paused_at": 0,
                "paused_by": "",
                "dedicated_teardown_requested_at": 0,
            },
            "override": {
                "active": False,
                "reason": "",
                "override_by": "",
                "override_at": 0,
                "override_until": 0,
            },
            "payment_review": {
                "updated_at": 0,
                "updated_by": "",
                "items": list(self.default_payment_items),
            },
        }

    def load_state(self):
        state = self.default_state()
        path = self.state_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return state
        if not isinstance(data, dict):
            return state
        state["schema_version"] = self.schema_version
        thresholds = data.get("thresholds") if isinstance(data.get("thresholds"), dict) else {}
        for key, row in thresholds.items():
            if isinstance(row, dict):
                state["thresholds"][str(key)] = {**state["thresholds"].get(str(key), {}), **row}
        for key in ("pause", "override", "payment_review"):
            if isinstance(data.get(key), dict):
                state[key] = {**state[key], **data[key]}
        state["payment_review"]["items"] = self.merge_payment_items(state["payment_review"].get("items"))
        return state

    def save_state(self, state):
        state = state if isinstance(state, dict) else self.default_state()
        state["schema_version"] = self.schema_version
        path = self.state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return state

    def merge_payment_items(self, items):
        by_id = {item["id"]: dict(item) for item in self.default_payment_items}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if not item_id:
                continue
            by_id[item_id] = {**by_id.get(item_id, {"id": item_id, "label": item_id, "detail": ""}), **item}
        return list(by_id.values())

    def safe_float(self, value, default=0.0):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if parsed < 0:
            return default
        return parsed

    def safe_dict(self, value):
        return value if isinstance(value, dict) else {}

    def scope_key(self, scope_type, scope_id):
        return "%s:%s" % (str(scope_type or "workspace").strip() or "workspace", str(scope_id or "default").strip() or "default")

    def threshold_for(self, state, scope_type="workspace", scope_id="default"):
        key = self.scope_key(scope_type, scope_id)
        row = state.get("thresholds", {}).get(key)
        if not isinstance(row, dict):
            row = state.get("thresholds", {}).get("workspace:default", {})
        row = row if isinstance(row, dict) else {}
        return {
            "scope_key": key,
            "scope_type": str(row.get("scope_type") or scope_type or "workspace"),
            "scope_id": str(row.get("scope_id") or scope_id or "default"),
            "monthly_threshold_usd": self.safe_float(row.get("monthly_threshold_usd")),
            "warning_ratio": self.safe_float(row.get("warning_ratio"), 0.80) or 0.80,
            "hard_ratio": self.safe_float(row.get("hard_ratio"), 1.05) or 1.05,
            "updated_at": self.safe_float(row.get("updated_at")),
            "updated_by": str(row.get("updated_by") or ""),
        }

    def local_since(self, since_ts, now):
        try:
            return self.safe_float(self.local_usage_since(since_ts, now))
        except Exception:
            return 0.0

    def dedicated_minute_cost(self, cfg, now):
        cfg = self.safe_dict(cfg)
        if str(cfg.get("state") or "") not in self.active_dedicated_states:
            return 0.0
        hourly = self.safe_float(cfg.get("price_per_hour"))
        if not hourly:
            return 0.0
        start = self.safe_float(cfg.get("run_started_at") or cfg.get("created_at"))
        if not start:
            return 0.0
        seconds = max(0.0, min(now, now) - max(start, now - 60.0))
        return round((seconds / 3600.0) * hourly, 8)

    def cost_windows(self, state):
        now = self.clock()
        month_start = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        cfg = self.safe_dict(self.load_dedicated_config())
        try:
            dedicated_runtime = self.safe_dict(self.dedicated_runtime_cost_summary(cfg, now))
        except Exception:
            dedicated_runtime = {}
        try:
            summary = self.safe_dict(self.cost_summary_payload())
        except Exception as exc:
            summary = {"error": str(exc)}
        dedicated_minute = self.dedicated_minute_cost(cfg, now)
        dedicated_daily = self.safe_float(dedicated_runtime.get("last_24h_cost_usd"))
        dedicated_monthly = self.safe_float(dedicated_runtime.get("month_cost_usd"))
        llm_minute = self.local_since(now - 60.0, now)
        llm_daily_local = self.safe_float(summary.get("local_proxy_last_24h_usd"))
        if not llm_daily_local:
            llm_daily_local = self.local_since(now - 86400.0, now)
        llm_month_local = self.local_since(month_start, now)

        provider_daily_total = summary.get("last_24h_total_usd")
        provider_daily_source = str(summary.get("last_24h_source") or "")
        provider_daily_live = provider_daily_total is not None and provider_daily_source and not provider_daily_source.startswith("local_")
        daily_total = self.safe_float(provider_daily_total) if provider_daily_total is not None else round(llm_daily_local + dedicated_daily, 8)
        llm_daily = max(0.0, round(daily_total - dedicated_daily, 8)) if provider_daily_live else llm_daily_local

        provider_month_total = summary.get("month_to_date_total_usd", summary.get("month_total_usd"))
        provider_month_live = provider_month_total is not None
        monthly_total = self.safe_float(provider_month_total) if provider_month_live else round(llm_month_local + dedicated_monthly, 8)
        llm_monthly = max(0.0, round(monthly_total - dedicated_monthly, 8)) if provider_month_live else llm_month_local

        minute_total = round(llm_minute + dedicated_minute, 8)
        threshold = self.threshold_for(state)
        limit = threshold["monthly_threshold_usd"]
        warning_at = round(limit * threshold["warning_ratio"], 8) if limit else 0.0
        hard_at = round(limit * threshold["hard_ratio"], 8) if limit else 0.0
        percent = round((monthly_total / limit) * 100.0, 2) if limit else 0.0
        hard_percent = round(threshold["hard_ratio"] * 100.0, 2)
        warning_percent = round(threshold["warning_ratio"] * 100.0, 2)
        return {
            "checked_at": now,
            "summary": summary,
            "dedicated_config": cfg,
            "costs": {
                "minute_total_usd": minute_total,
                "daily_total_usd": round(daily_total, 8),
                "monthly_total_usd": round(monthly_total, 8),
                "categories": {
                    "dedicated_instances": {
                        "minute_usd": dedicated_minute,
                        "daily_usd": round(dedicated_daily, 8),
                        "monthly_usd": round(dedicated_monthly, 8),
                        "source": "local_dedicated_runtime_estimate",
                        "estimated": True,
                        "idle_included": True,
                    },
                    "llm_service": {
                        "minute_usd": round(llm_minute, 8),
                        "daily_usd": round(llm_daily, 8),
                        "monthly_usd": round(llm_monthly, 8),
                        "source": "provider_billing_api_minus_dedicated" if (provider_daily_live or provider_month_live) else "local_proxy_usage_estimate",
                        "estimated": not (provider_daily_live or provider_month_live),
                        "idle_included": False,
                    },
                },
                "sources": {
                    "daily": "provider_billing_api" if provider_daily_live else "local_estimate",
                    "monthly": "provider_billing_api" if provider_month_live else "local_estimate",
                    "minute": "local_estimate",
                },
            },
            "threshold": {
                **threshold,
                "warning_at_usd": warning_at,
                "hard_at_usd": hard_at,
                "percent": percent,
                "warning_percent": warning_percent,
                "hard_percent": hard_percent,
                "warning": bool(limit and monthly_total >= warning_at),
                "hard": bool(limit and monthly_total >= hard_at),
            },
        }

    def override_state(self, state, now):
        override = self.safe_dict(state.get("override"))
        until = self.safe_float(override.get("override_until"))
        active = bool(override.get("active") and until and now < until)
        if override.get("active") and not active:
            override["active"] = False
            state["override"] = override
        return {
            "active": active,
            "reason": str(override.get("reason") or ""),
            "override_by": str(override.get("override_by") or ""),
            "override_at": self.safe_float(override.get("override_at")),
            "override_until": until if active else 0,
        }

    def apply_pause_state(self, state, windows, auto_enforce=True):
        now = windows["checked_at"]
        threshold = windows["threshold"]
        pause = self.safe_dict(state.get("pause"))
        override = self.override_state(state, now)
        changed = False
        if threshold["hard"] and not override["active"] and not pause.get("active"):
            pause.update({
                "active": True,
                "reason": "hard_monthly_threshold",
                "paused_at": now,
                "paused_by": "cost-control",
            })
            changed = True
        if not threshold["hard"] and pause.get("reason") == "hard_monthly_threshold":
            pause.update({"active": False, "reason": "", "paused_at": 0, "paused_by": "", "dedicated_teardown_requested_at": 0})
            changed = True
        dedicated_teardown = None
        cfg = windows.get("dedicated_config") if isinstance(windows.get("dedicated_config"), dict) else {}
        if auto_enforce and pause.get("active") and not override["active"] and str(cfg.get("state") or "") in self.active_dedicated_states:
            if not self.safe_float(pause.get("dedicated_teardown_requested_at")) and self.dedicated_teardown is not None:
                pause["dedicated_teardown_requested_at"] = now
                changed = True
                try:
                    status, payload = self.dedicated_teardown({"reason": "monthly_cost_hard_pause"})
                    dedicated_teardown = {"status": int(status), "payload": payload}
                except Exception as exc:
                    dedicated_teardown = {"status": 500, "error": str(exc)}
        state["pause"] = pause
        if changed:
            self.save_state(state)
        return {
            "active": bool(pause.get("active") and not override["active"]),
            "configured_active": bool(pause.get("active")),
            "reason": str(pause.get("reason") or ""),
            "paused_at": self.safe_float(pause.get("paused_at")),
            "paused_by": str(pause.get("paused_by") or ""),
            "hard_state": bool(threshold["hard"]),
            "warning_state": bool(threshold["warning"]),
            "dedicated_teardown_requested_at": self.safe_float(pause.get("dedicated_teardown_requested_at")),
            "dedicated_teardown": dedicated_teardown,
            "override": override,
        }

    def status(self, auto_enforce=True):
        state = self.load_state()
        windows = self.cost_windows(state)
        pause = self.apply_pause_state(state, windows, auto_enforce=auto_enforce)
        payment = self.safe_dict(state.get("payment_review"))
        status = "paused" if pause["active"] else "hard" if pause["hard_state"] else "warning" if pause["warning_state"] else "ready"
        return {
            "schema_version": self.schema_version,
            "checked_at": windows["checked_at"],
            "status": status,
            "costs": windows["costs"],
            "threshold": windows["threshold"],
            "pause": pause,
            "thresholds": state.get("thresholds", {}),
            "payment_review": {
                "updated_at": self.safe_float(payment.get("updated_at")),
                "updated_by": str(payment.get("updated_by") or ""),
                "items": self.merge_payment_items(payment.get("items")),
            },
            "provider": {
                "billing_api_configured": bool(windows["summary"].get("digitalocean_configured")),
                "account_urn_configured": bool(windows["summary"].get("account_urn_configured")),
                "daily_source": windows["costs"]["sources"]["daily"],
                "monthly_source": windows["costs"]["sources"]["monthly"],
                "fallback_estimates_active": "local_estimate" in set(windows["costs"]["sources"].values()),
            },
        }

    def update(self, data, actor=None):
        data = data if isinstance(data, dict) else {}
        actor = actor if isinstance(actor, dict) else {}
        state = self.load_state()
        now = self.clock()
        if any(key in data for key in ("monthly_threshold_usd", "warning_ratio", "hard_ratio", "scope_type", "scope_id")):
            scope_type = data.get("scope_type") or "workspace"
            scope_id = data.get("scope_id") or "default"
            key = self.scope_key(scope_type, scope_id)
            current = dict(state.get("thresholds", {}).get(key, {}))
            current.update({
                "scope_type": str(scope_type),
                "scope_id": str(scope_id),
                "monthly_threshold_usd": self.safe_float(data.get("monthly_threshold_usd")),
                "warning_ratio": self.safe_float(data.get("warning_ratio"), 0.80) or 0.80,
                "hard_ratio": self.safe_float(data.get("hard_ratio"), 1.05) or 1.05,
                "updated_at": now,
                "updated_by": str(actor.get("id") or data.get("updated_by") or "operator"),
            })
            state.setdefault("thresholds", {})[key] = current
        payment_review = data.get("payment_review")
        if isinstance(payment_review, dict):
            payment = self.safe_dict(state.get("payment_review"))
            payment["items"] = self.merge_payment_items(payment_review.get("items"))
            payment["updated_at"] = now
            payment["updated_by"] = str(actor.get("id") or data.get("updated_by") or "operator")
            state["payment_review"] = payment
        self.save_state(state)
        return self.status(auto_enforce=True)

    def override(self, data, actor=None):
        data = data if isinstance(data, dict) else {}
        actor = actor if isinstance(actor, dict) else {}
        state = self.load_state()
        now = self.clock()
        action = str(data.get("action") or "override").strip().lower()
        pause = self.safe_dict(state.get("pause"))
        override = self.safe_dict(state.get("override"))
        if action == "pause":
            pause.update({"active": True, "reason": str(data.get("reason") or "manual_pause"), "paused_at": now, "paused_by": str(actor.get("id") or data.get("operator") or "operator")})
            override.update({"active": False, "override_until": 0})
        else:
            duration_minutes = max(1.0, min(1440.0, self.safe_float(data.get("duration_minutes"), 60.0) or 60.0))
            pause.update({"active": False, "reason": "", "paused_at": 0, "paused_by": "", "dedicated_teardown_requested_at": 0})
            override.update({
                "active": True,
                "reason": str(data.get("reason") or "operator_override"),
                "override_by": str(actor.get("id") or data.get("operator") or "operator"),
                "override_at": now,
                "override_until": now + duration_minutes * 60.0,
            })
        state["pause"] = pause
        state["override"] = override
        self.save_state(state)
        return self.status(auto_enforce=True)

    def guard(self, action, category="llm_service", actor=None):
        payload = self.status(auto_enforce=True)
        if payload["pause"]["active"]:
            return False, {
                "type": "cost_control_paused",
                "message": "Cost control hard pause is active. Review monthly threshold, payment status, or use an authorized override before starting more cost-generating work.",
                "action": action,
                "category": category,
                "cost_control": payload,
                "actor": actor if isinstance(actor, dict) else {},
            }
        return True, {"cost_control": payload, "action": action, "category": category}
