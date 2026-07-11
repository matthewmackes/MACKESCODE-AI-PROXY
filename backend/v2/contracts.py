"""Dataclass contracts for v2 API payloads.

The v2 FastAPI app can later wrap these with Pydantic models for schema
generation, but these dataclasses keep core contract shaping testable without
requiring optional runtime dependencies.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActorIdentity:
    id: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    source: str = "unknown"
    session_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ActorIdentity":
        data = data if isinstance(data, dict) else {}
        return cls(
            id=str(data.get("id") or "anonymous"),
            roles=tuple(str(role) for role in (data.get("roles") or []) if role),
            permissions=tuple(str(permission) for permission in (data.get("permissions") or []) if permission),
            source=str(data.get("source") or "unknown"),
            session_id=str(data.get("session_id") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "roles": list(self.roles),
            "permissions": list(self.permissions),
            "source": self.source,
        }
        if self.session_id:
            payload["session_id"] = self.session_id
        return payload


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    allowed: bool
    required_permission: str = ""
    category: str = "general"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "allowed": self.allowed,
            "required_permission": self.required_permission,
            "category": self.category,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    allowed: bool
    required_permission: str = ""
    reason: str = ""
    actor_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "allowed": self.allowed,
            "required_permission": self.required_permission,
            "reason": self.reason,
            "actor_id": self.actor_id,
            "details": self.details,
        }


@dataclass(frozen=True)
class ErrorEnvelope:
    message: str
    code: str = "error"
    category: str = "server"
    status: int = 500
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.message,
            "message": self.message,
            "code": self.code,
            "category": self.category,
            "status": int(self.status),
            "details": self.details,
        }


@dataclass(frozen=True)
class EventEnvelope:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    severity: str = "info"
    actor: dict[str, Any] = field(default_factory=dict)
    subject: str = ""
    correlation_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: float = field(default_factory=time.time)
    redaction: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "ts": self.ts,
            "kind": self.kind,
            "severity": self.severity,
            "actor": self.actor,
            "subject": self.subject,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "redaction": self.redaction,
        }


@dataclass(frozen=True)
class AuditEvent:
    action: str
    actor_id: str
    outcome: str
    target: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "action": self.action,
            "actor_id": self.actor_id,
            "outcome": self.outcome,
            "target": self.target,
            "details": self.details,
        }


@dataclass(frozen=True)
class TraceSummary:
    trace_id: str
    action: str
    status: str
    model: str = ""
    session_id: str = ""
    cost_usd: float = 0.0
    latency_ms: int = 0
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "ts": self.ts,
            "action": self.action,
            "status": self.status,
            "model": self.model,
            "session_id": self.session_id,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
        }


@dataclass(frozen=True)
class NotificationEnvelope:
    notification_id: str
    title: str
    body: str
    severity: str = "info"
    read: bool = False
    action_url: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "ts": self.ts,
            "title": self.title,
            "body": self.body,
            "severity": self.severity,
            "read": self.read,
            "action_url": self.action_url,
        }


@dataclass(frozen=True)
class ReportExportEnvelope:
    export_id: str
    schema_version: int
    format: str
    path: str
    tables: tuple[str, ...] = ()
    source_fingerprints: dict[str, Any] = field(default_factory=dict)
    redaction_mode: str = "strict"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "export_id": self.export_id,
            "schema_version": int(self.schema_version),
            "format": self.format,
            "path": self.path,
            "tables": list(self.tables),
            "source_fingerprints": self.source_fingerprints,
            "redaction_mode": self.redaction_mode,
            "created_at": self.created_at,
        }
