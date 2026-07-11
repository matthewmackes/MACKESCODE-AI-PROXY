"""Trace domain records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MessageSummary:
    message_count: int = 0
    last_user_preview: str = ""
    last_user_chars: int = 0

    @classmethod
    def from_messages(cls, messages, limit=160):
        rows = messages if isinstance(messages, list) else []
        last_user = ""
        for msg in rows:
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user = str(msg.get("content") or "")
        return cls(len(rows), " ".join(last_user.split())[:limit], len(last_user))

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        return cls(int(data.get("message_count") or 0), str(data.get("last_user_preview") or ""), int(data.get("last_user_chars") or 0))

    def to_dict(self):
        return {"message_count": self.message_count, "last_user_preview": self.last_user_preview, "last_user_chars": self.last_user_chars}


@dataclass(frozen=True)
class TraceRecord:
    trace_id: str
    timestamp: float
    status: str = "unknown"
    action: str = ""
    requested_model: str = ""
    routed_model: str = ""
    provider: str = ""
    endpoint_mode: str = ""
    routing_reason: str = ""
    error_category: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    message_summary: MessageSummary = field(default_factory=MessageSummary)
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        trace_id = str(data.get("trace_id") or "").strip()
        if not trace_id:
            raise ValueError("trace_id is required")
        if data.get("timestamp") in (None, ""):
            raise ValueError("trace timestamp is required")
        summary = MessageSummary.from_dict(data.get("message_summary") if isinstance(data.get("message_summary"), dict) else {})
        known = {"trace_id", "timestamp", "status", "action", "requested_model", "routed_model", "provider", "endpoint_mode", "routing_reason", "error_category", "latency_ms", "cost_usd", "message_summary"}
        latency = int(max(0, float(data.get("latency_ms") or 0)))
        return cls(
            trace_id=trace_id,
            timestamp=float(data.get("timestamp")),
            status=str(data.get("status") or "unknown"),
            action=str(data.get("action") or ""),
            requested_model=str(data.get("requested_model") or ""),
            routed_model=str(data.get("routed_model") or ""),
            provider=str(data.get("provider") or ""),
            endpoint_mode=str(data.get("endpoint_mode") or ""),
            routing_reason=str(data.get("routing_reason") or ""),
            error_category=str(data.get("error_category") or ""),
            latency_ms=latency,
            cost_usd=float(data.get("cost_usd") or 0.0),
            message_summary=summary,
            extra={key: value for key, value in data.items() if key not in known},
        )

    def to_dict(self):
        row = dict(self.extra)
        row.update({
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "action": self.action,
            "requested_model": self.requested_model,
            "routed_model": self.routed_model,
            "provider": self.provider,
            "endpoint_mode": self.endpoint_mode,
            "routing_reason": self.routing_reason,
            "error_category": self.error_category,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
        })
        if self.message_summary.message_count or self.message_summary.last_user_preview:
            row["message_summary"] = self.message_summary.to_dict()
        return {key: value for key, value in row.items() if value not in (None, "")}
