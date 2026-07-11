"""Dedicated Inference domain records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DedicatedConfig:
    state: str
    model_id: str = "dedicated-inference"
    display_name: str = "Dedicated Inference"
    daily_budget_usd: float = 0.0
    fallback_model: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        state = str(data.get("state") or "").strip()
        if not state:
            raise ValueError("dedicated state is required")
        known = {"state", "model_id", "display_name", "daily_budget_usd", "fallback_model"}
        return cls(state, str(data.get("model_id") or "dedicated-inference"), str(data.get("display_name") or "Dedicated Inference"), float(data.get("daily_budget_usd") or 0.0), str(data.get("fallback_model") or ""), {key: value for key, value in data.items() if key not in known})

    def to_dict(self):
        row = dict(self.extra)
        row.update({"state": self.state, "model_id": self.model_id, "display_name": self.display_name, "daily_budget_usd": self.daily_budget_usd, "fallback_model": self.fallback_model})
        return row


@dataclass(frozen=True)
class LifecycleEvent:
    type: str
    message: str = ""
    severity: str = "info"
    timestamp: float = 0.0
    data: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        event_type = str(data.get("type") or data.get("state") or "").strip()
        if not event_type:
            raise ValueError("lifecycle event type is required")
        return cls(event_type, str(data.get("message") or ""), str(data.get("severity") or "info"), float(data.get("timestamp") or 0.0), data.get("data") if isinstance(data.get("data"), dict) else {})

    def to_dict(self):
        return {"type": self.type, "message": self.message, "severity": self.severity, "timestamp": self.timestamp, "data": self.data}
