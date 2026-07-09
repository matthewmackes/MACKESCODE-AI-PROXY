"""Security audit logging for console actions."""
import json
import time


SENSITIVE_KEYS = {"token", "access_token", "authorization", "api_key", "password", "secret"}


class AuditService:
    """Append compact JSONL audit records for sensitive operator actions."""

    def __init__(self, audit_file, clock=None):
        self.audit_file = audit_file
        self.clock = clock or time.time

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
        path = self.audit_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record
