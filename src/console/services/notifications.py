"""Persistent notification center built from operational evidence."""
import hashlib
import json
import time
import uuid
from pathlib import Path


class NotificationCenterService:
    """Derive redacted notifications and persist operator state changes."""

    STATUSES = {"new", "acknowledged", "resolved"}
    SEVERITIES = {"low", "medium", "high", "critical"}
    SENSITIVE_PARTS = ("token", "secret", "password", "authorization", "api_key", "access_key", "messages", "prompt", "screen", "raw", "output")

    def __init__(
        self,
        state_file,
        review_queue_payload=None,
        provider_health_payload=None,
        release_candidate_payload=None,
        automation_payload=None,
        list_eval_runs=None,
        dedicated_events=None,
        cost_summary_payload=None,
        cost_anomaly_payload=None,
        quota_planner_payload=None,
        audit_rows=None,
        failure_taxonomy=None,
        append_audit=None,
        clock=None,
        uuid_factory=None,
        retention_days=30,
    ):
        self.state_file = state_file
        self.review_queue_payload = review_queue_payload or (lambda **kwargs: {"reviews": []})
        self.provider_health_payload = provider_health_payload or (lambda: {"findings": []})
        self.release_candidate_payload = release_candidate_payload or (lambda: {"checks": []})
        self.automation_payload = automation_payload or (lambda: {"executions": []})
        self.list_eval_runs = list_eval_runs or (lambda **kwargs: [])
        self.dedicated_events = dedicated_events or (lambda limit=80: [])
        self.cost_summary_payload = cost_summary_payload or (lambda: {})
        self.cost_anomaly_payload = cost_anomaly_payload or (lambda: {"anomalies": []})
        self.quota_planner_payload = quota_planner_payload or (lambda: {"quotas": []})
        self.audit_rows = audit_rows or (lambda limit=200: [])
        self.failure_taxonomy = failure_taxonomy
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4
        self.retention_days = int(retention_days or 30)

    def path(self):
        path = Path(self.state_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def default_state(self):
        return {"schema_version": 1, "states": {}, "manual": []}

    def load_state(self):
        path = self.path()
        if not path.exists():
            return self.default_state()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.default_state()
        return {
            "schema_version": 1,
            "states": data.get("states") if isinstance(data.get("states"), dict) else {},
            "manual": data.get("manual") if isinstance(data.get("manual"), list) else [],
        }

    def save_state(self, state):
        self.path().write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state

    def redact(self, value):
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(part in lowered for part in self.SENSITIVE_PARTS):
                    clean[key] = "[redacted]"
                else:
                    clean[key] = self.redact(item)
            return clean
        if isinstance(value, list):
            return [self.redact(item) for item in value[:80]]
        if isinstance(value, str) and len(value) > 500:
            return value[:500] + "...[truncated]"
        return value

    def stable_id(self, prefix, *parts):
        text = "|".join(str(part or "") for part in parts)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return "%s_%s" % (prefix, digest)

    def notification(self, notification_id, title, body, severity, category, source, created_at=None, evidence=None, links=None):
        severity = str(severity or "medium").lower()
        if severity not in self.SEVERITIES:
            severity = "medium"
        return {
            "id": str(notification_id),
            "schema_version": 1,
            "title": str(title or "Notification"),
            "body": str(body or ""),
            "severity": severity,
            "category": str(category or "operations"),
            "source": self.redact(source if isinstance(source, dict) else {}),
            "status": "new",
            "created_at": float(created_at or self.clock()),
            "acknowledged_at": None,
            "resolved_at": None,
            "actor": {},
            "evidence": self.redact(evidence if isinstance(evidence, dict) else {}),
            "links": self.redact(links if isinstance(links, list) else []),
        }

    def apply_state(self, notifications, state):
        overrides = state.get("states") if isinstance(state.get("states"), dict) else {}
        for item in notifications:
            override = overrides.get(item.get("id"))
            if not isinstance(override, dict):
                continue
            item["status"] = override.get("status") or item.get("status")
            item["acknowledged_at"] = override.get("acknowledged_at")
            item["resolved_at"] = override.get("resolved_at")
            item["actor"] = self.redact(override.get("actor") if isinstance(override.get("actor"), dict) else {})
            item["notes"] = str(override.get("notes") or "")
        return notifications

    def derived_notifications(self):
        rows = []
        rows.extend(self.review_notifications())
        rows.extend(self.provider_notifications())
        rows.extend(self.release_notifications())
        rows.extend(self.eval_notifications())
        rows.extend(self.automation_notifications())
        rows.extend(self.dedicated_notifications())
        rows.extend(self.budget_notifications())
        rows.extend(self.cost_anomaly_notifications())
        rows.extend(self.quota_notifications())
        rows.extend(self.audit_notifications())
        return rows

    def review_notifications(self):
        rows = []
        payload = self.safe_call(lambda: self.review_queue_payload(status="open"), {"reviews": []})
        for review in payload.get("reviews") or []:
            rows.append(self.notification(
                "review_%s" % review.get("id"),
                review.get("title") or "Open review item",
                "%s · %s" % (review.get("reason") or "review", review.get("status") or "open"),
                review.get("severity") or "medium",
                "review",
                {"type": "review", "id": review.get("id")},
                created_at=review.get("created_at") or review.get("updated_at"),
                evidence={"source": review.get("source"), "evidence": review.get("evidence")},
                links=[{"label": "Review Queue", "target": "console:reviews", "id": review.get("id")}],
            ))
        return rows

    def provider_notifications(self):
        rows = []
        payload = self.safe_call(self.provider_health_payload, {"findings": []})
        for finding in payload.get("findings") or []:
            failure_categories = finding.get("failure_categories") if isinstance(finding.get("failure_categories"), dict) else {}
            failure_hint = self.failure_hint(finding, failure_categories)
            rows.append(self.notification(
                self.stable_id("provider", finding.get("type"), finding.get("title"), finding.get("detail")),
                finding.get("title") or "Provider health finding",
                failure_hint or finding.get("detail") or finding.get("type") or "",
                finding.get("severity") or "medium",
                "provider",
                {"type": "provider_health", "finding_type": finding.get("type")},
                created_at=payload.get("generated_at"),
                evidence=dict(finding, failure_categories=failure_categories),
                links=[{"label": "Provider Health", "target": "console:provider-health"}],
            ))
        return rows

    def failure_hint(self, finding, failure_categories):
        category = ""
        if failure_categories:
            category = sorted(failure_categories.items(), key=lambda item: (-int(item[1] or 0), item[0]))[0][0]
        if not category:
            category = finding.get("type")
        if self.failure_taxonomy is None or not category:
            return ""
        failure = self.failure_taxonomy.classify({"category": category, "message": finding.get("detail") or ""})
        return "%s · %s" % (failure.get("title") or category, failure.get("suggested_fix") or "")

    def release_notifications(self):
        rows = []
        payload = self.safe_call(self.release_candidate_payload, {"checks": []})
        for check in payload.get("checks") or []:
            if check.get("status") == "passed":
                continue
            severity = "critical" if check.get("blocking") else "medium"
            rows.append(self.notification(
                "release_%s" % check.get("id"),
                check.get("title") or "Release check failed",
                check.get("action") or check.get("category") or "",
                severity,
                "release",
                {"type": "release_check", "id": check.get("id")},
                created_at=payload.get("generated_at"),
                evidence=check.get("evidence") if isinstance(check.get("evidence"), dict) else check,
                links=[{"label": "Release Candidate", "target": "console:release-candidate"}],
            ))
        return rows

    def eval_notifications(self):
        rows = []
        for run in self.safe_call(lambda: self.list_eval_runs(limit=25), []) or []:
            for summary in run.get("summary") or []:
                failures = int(summary.get("failures") or 0)
                if failures <= 0:
                    continue
                rows.append(self.notification(
                    self.stable_id("eval", run.get("id"), summary.get("model"), run.get("dataset")),
                    "Eval failures for %s" % (summary.get("model") or "model"),
                    "%s failures in %s" % (failures, run.get("dataset") or "dataset"),
                    "high",
                    "quality",
                    {"type": "eval_run", "id": run.get("id"), "model": summary.get("model")},
                    created_at=run.get("created_at") or run.get("started_at") or run.get("ts"),
                    evidence={"run_id": run.get("id"), "dataset": run.get("dataset"), "summary": summary},
                    links=[{"label": "Evals", "target": "console:evals", "id": run.get("id")}],
                ))
        return rows

    def automation_notifications(self):
        rows = []
        payload = self.safe_call(self.automation_payload, {"executions": []})
        for execution in payload.get("executions") or []:
            matched = int(execution.get("matched_count") or 0)
            failed = []
            for rule in execution.get("matched_rules") or []:
                failed.extend([action for action in rule.get("actions") or [] if action.get("ok") is False])
            if matched <= 0 and not failed:
                continue
            severity = "high" if failed else "medium"
            rows.append(self.notification(
                "automation_%s" % execution.get("id"),
                "Automation %s matched %s rule%s" % ("test" if execution.get("dry_run") else "run", matched, "" if matched == 1 else "s"),
                "Event %s" % ((execution.get("event") or {}).get("event") or (execution.get("event") or {}).get("type") or "unknown"),
                severity,
                "automation",
                {"type": "automation_execution", "id": execution.get("id")},
                created_at=execution.get("created_at"),
                evidence={"execution": execution},
                links=[{"label": "Automation Rules", "target": "console:automation", "id": execution.get("id")}],
            ))
        return rows

    def dedicated_notifications(self):
        rows = []
        for event in self.safe_call(lambda: self.dedicated_events(limit=80), []) or []:
            severity = str(event.get("severity") or "info").lower()
            if severity not in {"warning", "error", "critical", "high"} and event.get("state") not in {"budget_blocked", "unhealthy", "failed", "teardown"}:
                continue
            rows.append(self.notification(
                self.stable_id("dedicated", event.get("ts") or event.get("created_at"), event.get("state"), event.get("message")),
                "Dedicated %s" % (event.get("state") or "event"),
                event.get("message") or "",
                "critical" if severity in {"critical", "error"} else "medium",
                "dedicated",
                {"type": "dedicated_event", "state": event.get("state")},
                created_at=event.get("ts") or event.get("created_at"),
                evidence=event,
                links=[{"label": "Dedicated", "target": "console:dedicated"}],
            ))
        return rows

    def budget_notifications(self):
        rows = []
        payload = self.safe_call(self.cost_summary_payload, {})
        dedicated = payload.get("dedicated_runtime") if isinstance(payload.get("dedicated_runtime"), dict) else {}
        budget_state = dedicated.get("budget_state") if isinstance(dedicated.get("budget_state"), dict) else {}
        if budget_state.get("critical") or budget_state.get("warning"):
            severity = "critical" if budget_state.get("critical") else "medium"
            rows.append(self.notification(
                self.stable_id("budget", "dedicated", budget_state.get("percent")),
                "Dedicated budget threshold",
                "Dedicated daily budget is at %.2f%%" % float(budget_state.get("percent") or 0.0),
                severity,
                "cost",
                {"type": "budget", "scope": "dedicated"},
                created_at=payload.get("checked_at"),
                evidence={"budget_state": budget_state, "cost_summary": payload},
                links=[{"label": "Costs", "target": "console:costs"}],
            ))
        return rows

    def cost_anomaly_notifications(self):
        rows = []
        payload = self.safe_call(self.cost_anomaly_payload, {"anomalies": []})
        for anomaly in payload.get("anomalies") or []:
            if anomaly.get("status") in {"suppressed", "resolved"}:
                continue
            rows.append(self.notification(
                "notification_%s" % anomaly.get("id"),
                anomaly.get("title") or "Cost anomaly",
                "%s is %.4f %s vs %.4f baseline" % (
                    anomaly.get("metric") or "usage",
                    float(anomaly.get("current") or 0.0),
                    anomaly.get("unit") or "units",
                    float(anomaly.get("baseline") or 0.0),
                ),
                anomaly.get("severity") or "high",
                "cost",
                {"type": "cost_anomaly", "id": anomaly.get("id")},
                created_at=anomaly.get("created_at") or payload.get("generated_at"),
                evidence=anomaly,
                links=[{"label": "Cost Anomalies", "target": "console:cost-anomalies", "id": anomaly.get("id")}],
            ))
        return rows

    def quota_notifications(self):
        rows = []
        payload = self.safe_call(self.quota_planner_payload, {"quotas": []})
        for quota in payload.get("quotas") or []:
            limit = float(quota.get("limit") or 0.0)
            used = float(quota.get("used") or 0.0)
            if not limit or used < limit:
                continue
            rows.append(self.notification(
                self.stable_id("quota", quota.get("source"), quota.get("name"), quota.get("window"), quota.get("metric")),
                "Quota threshold reached",
                "%s %s %s used %.4f of %.4f" % (quota.get("window"), quota.get("name"), quota.get("metric"), used, limit),
                "high",
                "cost",
                {"type": "quota", "source": quota.get("source"), "name": quota.get("name")},
                created_at=quota.get("reset_at") or self.clock(),
                evidence=quota,
                links=[{"label": "Quota Planner", "target": "console:quotas"}],
            ))
        return rows

    def audit_notifications(self):
        rows = []
        for audit in self.safe_call(lambda: self.audit_rows(limit=200), []) or []:
            action = str(audit.get("action") or "")
            status = int(audit.get("status") or 0)
            outcome = str(audit.get("outcome") or "")
            if status < 400 and outcome not in {"denied", "failed"} and not action.startswith("auth."):
                continue
            rows.append(self.notification(
                self.stable_id("audit", audit.get("ts"), action, status, outcome),
                "Security or audit event",
                "%s · %s" % (action or "audit", outcome or status),
                "high" if status >= 400 or outcome in {"denied", "failed"} else "medium",
                "security",
                {"type": "audit", "action": action},
                created_at=audit.get("ts"),
                evidence=audit,
                links=[{"label": "Audit", "target": "console:audit"}],
            ))
        return rows

    def payload(self, filters=None):
        filters = filters if isinstance(filters, dict) else {}
        state = self.compact_state(self.load_state())
        rows = self.apply_state((state.get("manual") or []) + self.derived_notifications(), state)
        rows = self.filter_rows(rows, filters)
        rows = sorted(rows, key=lambda item: (item.get("status") == "resolved", -float(item.get("created_at") or 0)))
        summary = self.summary(rows)
        self.save_state(state)
        return {"notifications": rows, "summary": summary, "filters": filters, "retention_days": self.retention_days}

    def update(self, payload, actor=None):
        payload = payload if isinstance(payload, dict) else {}
        ids = payload.get("ids") if isinstance(payload.get("ids"), list) else [payload.get("id") or payload.get("notification_id")]
        ids = [str(item) for item in ids if item]
        status = str(payload.get("status") or "").strip().lower()
        if status not in self.STATUSES:
            raise ValueError("notification status must be new, acknowledged, or resolved")
        if not ids:
            raise ValueError("notification id is required")
        now = float(self.clock())
        state = self.compact_state(self.load_state())
        states = state.setdefault("states", {})
        for item_id in ids:
            current = states.get(item_id) if isinstance(states.get(item_id), dict) else {}
            current["status"] = status
            current["actor"] = self.redact(actor if isinstance(actor, dict) else payload.get("actor") if isinstance(payload.get("actor"), dict) else {})
            current["notes"] = str(payload.get("notes") or current.get("notes") or "")
            if status == "acknowledged":
                current["acknowledged_at"] = now
                current.setdefault("resolved_at", None)
            elif status == "resolved":
                current["resolved_at"] = now
                current.setdefault("acknowledged_at", now)
            elif status == "new":
                current["acknowledged_at"] = None
                current["resolved_at"] = None
            states[item_id] = current
        self.save_state(state)
        self.append_audit("notification.update", actor=actor or {}, outcome="completed", permission="notification.update", request={"ids": ids, "status": status}, status=200)
        return self.payload()

    def filter_rows(self, rows, filters):
        severity = str(filters.get("severity") or "").strip().lower()
        category = str(filters.get("category") or "").strip().lower()
        status = str(filters.get("status") or "").strip().lower()
        if severity:
            rows = [row for row in rows if row.get("severity") == severity]
        if category:
            rows = [row for row in rows if row.get("category") == category]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def summary(self, rows):
        summary = {"total": len(rows), "new": 0, "acknowledged": 0, "resolved": 0, "critical": 0, "high": 0, "categories": {}}
        for row in rows:
            status = row.get("status") or "new"
            severity = row.get("severity") or "medium"
            category = row.get("category") or "operations"
            summary[status] = summary.get(status, 0) + 1
            if severity in {"critical", "high"}:
                summary[severity] = summary.get(severity, 0) + 1
            summary["categories"][category] = summary["categories"].get(category, 0) + 1
        return summary

    def compact_state(self, state):
        cutoff = float(self.clock()) - self.retention_days * 86400
        manual = []
        for item in state.get("manual") or []:
            if float(item.get("created_at") or 0) >= cutoff or item.get("status") != "resolved":
                manual.append(item)
        state["manual"] = manual
        states = {}
        for item_id, item in (state.get("states") or {}).items():
            ts = float(item.get("resolved_at") or item.get("acknowledged_at") or self.clock())
            if item.get("status") != "resolved" or ts >= cutoff:
                states[item_id] = item
        state["states"] = states
        return state

    def safe_call(self, fn, fallback):
        try:
            return fn()
        except Exception as exc:
            return fallback if not isinstance(fallback, dict) else {**fallback, "error": str(exc)}
