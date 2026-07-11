"""Search and export local console audit records."""
import csv
import io
import json
from collections import deque
from pathlib import Path

from src.console.services.audit import SENSITIVE_KEYS


class AuditExplorerService:
    """Bounded audit-log filtering over runtime JSONL records."""

    def __init__(self, audit_file, clock=None):
        self.audit_file = audit_file
        self.clock = clock

    def path(self):
        return Path(self.audit_file())

    def redact(self, value):
        if isinstance(value, dict):
            return {
                key: ("[redacted]" if any(part in str(key).lower() for part in SENSITIVE_KEYS) else self.redact(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value[:80]]
        if isinstance(value, str):
            return value[:500]
        return value

    def recent_records(self, scan_limit):
        path = self.path()
        if not path.exists():
            return [], 0
        rows = deque(maxlen=max(1, int(scan_limit or 1000)))
        invalid = 0
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        rows.append(json.loads(text))
                    except ValueError:
                        invalid += 1
        except OSError:
            return [], invalid
        return list(rows), invalid

    def text_match(self, record, needle):
        if not needle:
            return True
        return needle.lower() in json.dumps(record, sort_keys=True).lower()

    def actor_matches(self, actor, value):
        if not value:
            return True
        actor = actor if isinstance(actor, dict) else {}
        return value.lower() in str(actor.get("id") or "").lower()

    def role_matches(self, actor, value):
        if not value:
            return True
        actor = actor if isinstance(actor, dict) else {}
        roles = [str(role).lower() for role in actor.get("roles") or []]
        return value.lower() in roles

    def request_value(self, request, *keys):
        if not isinstance(request, dict):
            return ""
        stack = [request]
        while stack:
            item = stack.pop()
            if not isinstance(item, dict):
                continue
            for key in keys:
                if item.get(key):
                    return str(item.get(key))
            stack.extend(value for value in item.values() if isinstance(value, dict))
        return ""

    def related_links(self, record):
        request = record.get("request") if isinstance(record.get("request"), dict) else {}
        action = str(record.get("action") or "")
        links = []
        trace_id = self.request_value(request, "trace_id")
        session_id = self.request_value(request, "session_id", "session", "name")
        review_id = self.request_value(request, "review_id")
        path = request.get("path") if isinstance(request.get("path"), str) else ""
        if trace_id:
            links.append({"label": "Trace", "target": "console:traces", "id": trace_id})
        if session_id:
            links.append({"label": "Session", "target": "console:sessions", "id": session_id})
        if review_id or action.startswith("review."):
            links.append({"label": "Review Queue", "target": "console:reviews", "id": review_id})
        if action.startswith("config_drift") or "config-drift" in path:
            links.append({"label": "Config Drift", "target": "console:config-drift"})
        if action.startswith("rollback") or "rollback" in path:
            links.append({"label": "Rollback", "target": "console:rollback"})
        if action.startswith("cost_anomaly") or "cost-anomalies" in path:
            links.append({"label": "Cost Anomalies", "target": "console:cost-anomalies"})
        if path:
            links.append({"label": "Request Path", "target": path})
        return links

    def normalize(self, record):
        record = self.redact(record if isinstance(record, dict) else {})
        actor = record.get("actor") if isinstance(record.get("actor"), dict) else {}
        request = record.get("request") if isinstance(record.get("request"), dict) else {}
        record["actor_id"] = actor.get("id") or "unknown"
        record["actor_roles"] = actor.get("roles") or []
        record["request_path"] = request.get("path") or ""
        record["related_links"] = self.related_links(record)
        return record

    def matches(self, record, filters):
        actor = record.get("actor") if isinstance(record.get("actor"), dict) else {}
        request = record.get("request") if isinstance(record.get("request"), dict) else {}
        checks = {
            "action": str(record.get("action") or ""),
            "permission": str(record.get("permission") or ""),
            "outcome": str(record.get("outcome") or ""),
            "source": str(actor.get("source") or ""),
            "request_path": str(request.get("path") or ""),
            "status": str(record.get("status") or ""),
        }
        for key, value in checks.items():
            wanted = str(filters.get(key) or "").strip().lower()
            if wanted and wanted not in value.lower():
                return False
        if not self.actor_matches(actor, str(filters.get("actor") or "").strip()):
            return False
        if not self.role_matches(actor, str(filters.get("role") or "").strip()):
            return False
        for key in ("session", "model", "trace_id", "review_id"):
            wanted = str(filters.get(key) or "").strip()
            if wanted and wanted.lower() not in self.request_value(request, key, key + "_id", "id").lower():
                return False
        try:
            start = float(filters.get("start_ts") or 0)
            end = float(filters.get("end_ts") or 0)
            ts = float(record.get("ts") or 0)
        except (TypeError, ValueError):
            start = end = ts = 0
        if start and ts < start:
            return False
        if end and ts > end:
            return False
        return self.text_match(record, str(filters.get("q") or "").strip())

    def payload(self, filters=None):
        filters = filters if isinstance(filters, dict) else {}
        limit = min(max(1, int(filters.get("limit") or 100)), 1000)
        scan_limit = min(max(limit, int(filters.get("scan_limit") or 1000)), 10000)
        rows, invalid = self.recent_records(scan_limit)
        rows = [self.normalize(row) for row in rows if self.matches(row, filters)]
        rows = sorted(rows, key=lambda item: float(item.get("ts") or 0), reverse=True)[:limit]
        return {
            "records": rows,
            "summary": {"returned": len(rows), "scan_limit": scan_limit, "invalid_records": invalid, "has_more": len(rows) == limit},
            "filters": filters,
            "path": str(self.path()),
        }

    def export(self, filters=None, fmt="json"):
        payload = self.payload(filters)
        rows = payload.get("records") or []
        if str(fmt or "json").lower() == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["ts", "actor_id", "action", "permission", "outcome", "status", "request_path", "related_links"])
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "ts": row.get("ts"),
                    "actor_id": row.get("actor_id"),
                    "action": row.get("action"),
                    "permission": row.get("permission"),
                    "outcome": row.get("outcome"),
                    "status": row.get("status"),
                    "request_path": row.get("request_path"),
                    "related_links": json.dumps(row.get("related_links") or [], sort_keys=True),
                })
            return {"format": "csv", "content_type": "text/csv", "content": output.getvalue(), "summary": payload.get("summary")}
        return {"format": "json", "content_type": "application/json", "content": json.dumps(payload, indent=2, sort_keys=True), "summary": payload.get("summary")}
