"""Unified event envelope."""
import time
import uuid
from dataclasses import dataclass, field


SENSITIVE_KEYS = {"authorization", "token", "api_key", "access_key", "secret", "password", "messages", "prompt", "input", "output", "screen", "raw", "response", "text", "answer"}


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    ts: float
    kind: str
    severity: str = "info"
    actor: dict = field(default_factory=dict)
    subject: dict = field(default_factory=dict)
    correlation: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    redaction: dict = field(default_factory=dict)

    @classmethod
    def create(cls, kind, severity="info", actor=None, subject=None, correlation=None, payload=None, clock=None, uuid_factory=None):
        kind = str(kind or "").strip()
        if not kind:
            raise ValueError("event kind is required")
        now = (clock or time.time)()
        event_id = "evt_%s" % (uuid_factory or uuid.uuid4)().hex
        payload = payload if isinstance(payload, dict) else {}
        redacted = cls.redact(payload)
        return cls(
            event_id=event_id,
            ts=float(now),
            kind=kind,
            severity=str(severity or "info"),
            actor=actor if isinstance(actor, dict) else {},
            subject=subject if isinstance(subject, dict) else {},
            correlation=correlation if isinstance(correlation, dict) else {},
            payload=redacted,
            redaction={"profile": "default", "contains_sensitive": redacted != payload},
        )

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        event_id = str(data.get("event_id") or "").strip()
        kind = str(data.get("kind") or "").strip()
        if not event_id:
            raise ValueError("event_id is required")
        if not kind:
            raise ValueError("event kind is required")
        return cls(
            event_id=event_id,
            ts=float(data.get("ts") or 0.0),
            kind=kind,
            severity=str(data.get("severity") or "info"),
            actor=data.get("actor") if isinstance(data.get("actor"), dict) else {},
            subject=data.get("subject") if isinstance(data.get("subject"), dict) else {},
            correlation=data.get("correlation") if isinstance(data.get("correlation"), dict) else {},
            payload=cls.redact(data.get("payload") if isinstance(data.get("payload"), dict) else {}),
            redaction=data.get("redaction") if isinstance(data.get("redaction"), dict) else {"profile": "default"},
        )

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "ts": self.ts,
            "kind": self.kind,
            "severity": self.severity,
            "actor": self.actor,
            "subject": self.subject,
            "correlation": self.correlation,
            "payload": self.payload,
            "redaction": self.redaction,
        }

    @classmethod
    def redact(cls, value):
        if isinstance(value, dict):
            return {str(key): ("[redacted]" if str(key).lower() in SENSITIVE_KEYS else cls.redact(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [cls.redact(item) for item in value[:50]]
        return value
