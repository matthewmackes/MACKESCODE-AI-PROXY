"""Provider-level health aggregation."""
import time


class ProviderHealthService:
    """Combine public status, local telemetry, registry, and lifecycle health."""

    def __init__(self, digitalocean_health_snapshot, read_traces, dedicated_status_payload, models_payload, proxy_sync_payload, active_model_access_key_info, failure_taxonomy=None, clock=None):
        self.digitalocean_health_snapshot = digitalocean_health_snapshot
        self.read_traces = read_traces
        self.dedicated_status_payload = dedicated_status_payload
        self.models_payload = models_payload
        self.proxy_sync_payload = proxy_sync_payload
        self.active_model_access_key_info = active_model_access_key_info
        self.failure_taxonomy = failure_taxonomy
        self.clock = clock or time.time

    def payload(self):
        now = float(self.clock())
        do_health = self.safe_call(self.digitalocean_health_snapshot, {})
        traces = self.safe_call(lambda: self.read_traces(limit=1000), [])
        dedicated = self.safe_call(lambda: self.dedicated_status_payload(poll=False), {})
        models = self.safe_call(lambda: self.models_payload(refresh_catalog=False), {})
        proxy = self.safe_call(lambda: self.proxy_sync_payload(force=False), {})
        key_info = self.safe_call(self.active_model_access_key_info, {})
        provider = self.provider_status(do_health, proxy, key_info)
        model_rows = self.model_health(traces, models)
        failure_categories = self.failure_summary(traces)
        findings = self.findings(provider, model_rows, do_health, dedicated, proxy, key_info, models)
        return {
            "generated_at": now,
            "providers": [provider],
            "models": model_rows,
            "failure_categories": failure_categories,
            "dedicated": self.dedicated_health(dedicated),
            "account": do_health.get("account") if isinstance(do_health, dict) else None,
            "billing": do_health.get("prepay") if isinstance(do_health, dict) else None,
            "findings": findings,
            "actions": self.actions(findings),
            "limits": "Provider status is public; account, model access, and telemetry details require Console auth.",
        }

    def provider_status(self, health, proxy, key_info):
        platform = health.get("platform") if isinstance(health, dict) else {}
        account = health.get("account") if isinstance(health, dict) else None
        prepay = health.get("prepay") if isinstance(health, dict) else None
        configured = bool(health.get("configured")) if isinstance(health, dict) else False
        indicator = (platform or {}).get("indicator") or "unknown"
        status = "healthy"
        issue_type = ""
        if indicator not in {"none", "unknown"}:
            status = "degraded"
            issue_type = "provider_outage"
        if not configured or not key_info.get("configured", configured):
            status = "degraded"
            issue_type = "auth_account_issue"
        if account and account.get("status") not in {"active", "ok"}:
            status = "degraded"
            issue_type = "auth_account_issue"
        if prepay and prepay.get("status") == "payment_due":
            status = "degraded"
            issue_type = "billing_issue"
        if proxy and not proxy.get("listening"):
            status = "degraded"
            issue_type = "local_proxy_issue"
        return {
            "id": "digitalocean",
            "name": "DigitalOcean",
            "status": status,
            "issue_type": issue_type or "none",
            "platform": platform or {},
            "configured": configured,
            "proxy_in_sync": bool(proxy.get("in_sync")) if isinstance(proxy, dict) else False,
            "model_access_key": key_info,
        }

    def model_health(self, traces, models_payload):
        options = {}
        for key in ("text_model_options", "image_model_options"):
            for item in models_payload.get(key) or []:
                if isinstance(item, dict):
                    options[item.get("id")] = item
        stats = {model_id: self.empty_model(model_id, item) for model_id, item in options.items() if model_id}
        for trace in traces or []:
            model = trace.get("routed_model") or trace.get("requested_model")
            if not model:
                continue
            row = stats.setdefault(model, self.empty_model(model, {}))
            row["requests"] += 1
            row["last_seen_at"] = max(row["last_seen_at"], float(trace.get("timestamp") or 0))
            if str(trace.get("status") or "").lower() in {"ok", "success", "200"} or int(trace.get("status_code") or 0) < 400 and trace.get("status_code") is not None:
                row["last_success_at"] = max(row["last_success_at"], float(trace.get("timestamp") or 0))
            else:
                row["errors"] += 1
                failure = self.classify_failure(trace)
                category = failure.get("category") or "unknown"
                row["failure_categories"][category] = row["failure_categories"].get(category, 0) + 1
            if str(trace.get("routing_reason") or "").lower() == "rate_limit_exceeded" or (trace.get("gateway_policy") or {}).get("decision") == "rate_limited":
                row["rate_limits"] += 1
            if trace.get("latency_ms") is not None:
                row["latencies"].append(int(trace.get("latency_ms") or 0))
        for row in stats.values():
            requests = max(1, row["requests"])
            row["failure_rate"] = round(row["errors"] / requests, 4)
            row["avg_latency_ms"] = int(sum(row["latencies"]) / len(row["latencies"])) if row["latencies"] else 0
            row.pop("latencies", None)
            if row.get("access_status") in {"forbidden", "unauthorized"}:
                row["status"] = "access_issue"
                row["issue_type"] = "model_access_issue"
            elif row["rate_limits"]:
                row["status"] = "degraded"
                row["issue_type"] = "rate_limit"
            elif row["failure_rate"] >= 0.2 and row["requests"] >= 3:
                row["status"] = "degraded"
                top_failure = self.top_failure_category(row.get("failure_categories"))
                row["issue_type"] = top_failure or "model_failure"
            else:
                row["status"] = "healthy" if not row.get("disabled") else "disabled"
                row["issue_type"] = "none"
        return sorted(stats.values(), key=lambda row: (row["status"] == "healthy", row["id"]))

    def dedicated_health(self, payload):
        dedicated = payload.get("dedicated") if isinstance(payload, dict) else {}
        if not isinstance(dedicated, dict):
            dedicated = {}
        state = dedicated.get("state") or "not_configured"
        ready = bool(dedicated.get("ready") or dedicated.get("endpoint_ready") or state == "active")
        issue_type = "none"
        status = "healthy" if ready else "not_ready"
        if dedicated.get("token_configured") is False:
            issue_type = "auth_account_issue"
        elif state in {"failed", "error", "unhealthy"}:
            issue_type = "dedicated_endpoint_issue"
        elif state in {"not_configured", "deleted"}:
            issue_type = "not_configured"
        return {"status": status, "issue_type": issue_type, "state": state, "ready": ready, "payload": dedicated}

    def findings(self, provider, models, do_health, dedicated, proxy, key_info, models_payload=None):
        findings = []
        if provider["issue_type"] != "none":
            findings.append({"severity": "high", "type": provider["issue_type"], "title": "DigitalOcean provider health needs attention", "detail": provider["status"]})
        for incident in ((do_health.get("platform") or {}).get("unresolved_incidents") or [])[:3]:
            findings.append({"severity": "high" if incident.get("impact") in {"major", "critical"} else "medium", "type": "provider_outage", "title": incident.get("name") or "DigitalOcean incident", "detail": incident.get("shortlink") or ""})
        if not proxy.get("in_sync"):
            findings.append({"severity": "medium", "type": "local_proxy_issue", "title": "Proxy registry is not synced", "detail": (proxy.get("details") or {}).get("reason") or ""})
        for row in models:
            if row["issue_type"] != "none":
                findings.append({"severity": "medium", "type": row["issue_type"], "title": "%s health issue" % row["id"], "detail": "failure %.1f%%, rate limits %s" % (row["failure_rate"] * 100, row["rate_limits"]), "failure_categories": row.get("failure_categories") or {}})
        drift = (models_payload or {}).get("model_access_drift") if isinstance(models_payload, dict) else {}
        for event in (drift or {}).get("events") or []:
            findings.append({
                "severity": event.get("severity") or "medium",
                "type": "model_access_drift",
                "title": event.get("title") or "%s access drift" % (event.get("model_id") or "Model"),
                "detail": "%s: %s -> %s" % (event.get("model_id") or "model", event.get("previous_status") or "unknown", event.get("access_status") or "unknown"),
                "event": event,
            })
        dedicated_health = self.dedicated_health(dedicated)
        if dedicated_health["issue_type"] not in {"none", "not_configured"}:
            findings.append({"severity": "medium", "type": dedicated_health["issue_type"], "title": "Dedicated endpoint needs attention", "detail": dedicated_health["state"]})
        if not key_info.get("configured", True):
            findings.append({"severity": "high", "type": "auth_account_issue", "title": "Model access key is not configured", "detail": ""})
        return findings

    def actions(self, findings):
        mapping = {
            "provider_outage": {"label": "Inspect incident", "action": "open_status"},
            "auth_account_issue": {"label": "Retry key audit", "action": "audit_model_access_key"},
            "billing_issue": {"label": "Open billing report", "action": "billing_report"},
            "local_proxy_issue": {"label": "Sync registry", "action": "sync_proxy"},
            "model_access_issue": {"label": "Retry access audit", "action": "audit_model_access_key"},
            "model_access_drift": {"label": "Acknowledge access drift", "action": "acknowledge_model_access_drift"},
            "rate_limit": {"label": "Use fallback route", "action": "fallback_route"},
            "dedicated_endpoint_issue": {"label": "Open Dedicated lifecycle", "action": "dedicated_lifecycle"},
            "budget": {"label": "Open quota planner", "action": "quota_planner"},
            "context_overflow": {"label": "Inspect context", "action": "context_inspector"},
            "malformed_tool_call": {"label": "Replay trace", "action": "replay_trace"},
            "registry_drift": {"label": "Sync registry", "action": "sync_proxy"},
            "dedicated_not_ready": {"label": "Open Dedicated lifecycle", "action": "dedicated_lifecycle"},
            "local_proxy": {"label": "Sync registry", "action": "sync_proxy"},
        }
        seen = set()
        actions = []
        for finding in findings:
            action = mapping.get(finding.get("type"))
            if action and action["action"] not in seen:
                seen.add(action["action"])
                actions.append(action)
        return actions

    def empty_model(self, model_id, item):
        return {
            "id": model_id,
            "display_name": item.get("display_name") or item.get("label") or model_id,
            "provider": item.get("provider") or "DigitalOcean",
            "disabled": bool(item.get("disabled")),
            "access_status": item.get("access_status") or "",
            "requests": 0,
            "errors": 0,
            "rate_limits": 0,
            "failure_categories": {},
            "failure_rate": 0.0,
            "avg_latency_ms": 0,
            "last_seen_at": 0,
            "last_success_at": 0,
            "latencies": [],
        }

    def safe_call(self, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            return {"error": str(exc)} if isinstance(fallback, dict) else fallback

    def classify_failure(self, trace):
        if self.failure_taxonomy is not None:
            return self.failure_taxonomy.classify(trace, status=trace.get("http_status") or trace.get("status_code"))
        failure = trace.get("failure") if isinstance(trace.get("failure"), dict) else {}
        return {"category": failure.get("category") or trace.get("error_category") or "unknown", "title": failure.get("title") or "unknown", "suggested_fix": failure.get("suggested_fix") or ""}

    def failure_summary(self, traces):
        rows = []
        for trace in traces or []:
            if str(trace.get("status") or "").lower() not in {"error", "failed", "denied"}:
                continue
            rows.append(trace)
        if self.failure_taxonomy is not None:
            return self.failure_taxonomy.summarize(rows)
        counts = {}
        for trace in rows:
            category = self.classify_failure(trace).get("category") or "unknown"
            counts[category] = counts.get(category, 0) + 1
        return [{"category": key, "count": value, "title": key, "suggested_fix": ""} for key, value in sorted(counts.items())]

    def top_failure_category(self, categories):
        categories = categories if isinstance(categories, dict) else {}
        if not categories:
            return ""
        return sorted(categories.items(), key=lambda item: (-int(item[1] or 0), item[0]))[0][0]
