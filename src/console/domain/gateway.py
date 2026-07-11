"""Gateway policy decision domain records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GatewayDecision:
    decision: str
    selected_model: str = ""
    reason: str = ""
    candidates: tuple = field(default_factory=tuple)
    policy: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        decision = str(data.get("decision") or "").strip()
        if not decision:
            raise ValueError("gateway decision is required")
        return cls(decision, str(data.get("selected_model") or data.get("model") or ""), str(data.get("reason") or ""), tuple(data.get("candidates") or []), data.get("policy") if isinstance(data.get("policy"), dict) else {})

    def to_dict(self):
        return {"decision": self.decision, "selected_model": self.selected_model, "reason": self.reason, "candidates": list(self.candidates), "policy": self.policy}
