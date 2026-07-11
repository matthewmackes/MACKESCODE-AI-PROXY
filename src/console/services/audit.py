"""Security audit logging for console actions."""
import time

from src.console.store import AuditRepository


SENSITIVE_KEYS = {"token", "access_token", "authorization", "api_key", "password", "secret"}


class AuditService:
    """Append compact JSONL audit records for sensitive operator actions."""

    def __init__(self, audit_file, clock=None, event_bus=None, repository=None):
        self.audit_file = audit_file
        self.clock = clock or time.time
        self.event_bus = event_bus
        self.repository = repository or AuditRepository(audit_file, clock=self.clock)

    def redact(self, value):
        if isinstance(value, dict):
            return {
                key: ("[redacted]" if any(part in str(key).lower() for part in SENSITIVE_KEYS) else self.redact(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value[:20]]
        text = str(value)
        return text[:240]

    def append(self, action, actor=None, outcome="allowed", permission="", request=None, status=None):
        actor = actor if isinstance(actor, dict) else {}
        record = {
            "ts": self.clock(),
            "action": str(action or "unknown"),
            "outcome": str(outcome or "allowed"),
            "permission": str(permission or ""),
            "status": int(status or 0),
            "actor": {
                "id": actor.get("id") or "unknown",
                "roles": list(actor.get("roles") or []),
                "source": actor.get("source") or "unknown",
            },
            "request": self.redact(request or {}),
        }
        self.repository.append(record)
        if self.event_bus is not None:
            try:
                self.event_bus.publish(
                    "audit.recorded",
                    severity="warning" if record.get("outcome") == "denied" else "info",
                    actor=record.get("actor"),
                    subject={"type": "audit", "id": record.get("action")},
                    correlation={"trace_id": record.get("request", {}).get("trace_id", "") if isinstance(record.get("request"), dict) else ""},
                    payload=record,
                )
            except Exception:
                pass
        return record

    def metadata(self):
        return self.repository.metadata()
