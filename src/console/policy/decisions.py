"""Serializable policy decision records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PolicyDecision:
    domain: str
    action: str
    allowed: bool
    reason: str
    severity: str = "info"
    actor: dict = field(default_factory=dict)
    subject: dict = field(default_factory=dict)
    matched_policy: dict = field(default_factory=dict)
    inputs: dict = field(default_factory=dict)
    effects: dict = field(default_factory=dict)
    overrides: dict = field(default_factory=dict)

    @classmethod
    def allow(cls, domain, action, reason="allowed", **kwargs):
        return cls(str(domain), str(action), True, str(reason), **kwargs)

    @classmethod
    def deny(cls, domain, action, reason="denied", severity="warning", **kwargs):
        return cls(str(domain), str(action), False, str(reason), severity=severity, **kwargs)

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        domain = str(data.get("domain") or "").strip()
        action = str(data.get("action") or data.get("decision") or "").strip()
        reason = str(data.get("reason") or "").strip()
        if not domain:
            raise ValueError("policy decision domain is required")
        if not action:
            raise ValueError("policy decision action is required")
        if not reason:
            reason = "allowed" if data.get("allowed", True) else "denied"
        return cls(
            domain=domain,
            action=action,
            allowed=bool(data.get("allowed", True)),
            reason=reason,
            severity=str(data.get("severity") or "info"),
            actor=data.get("actor") if isinstance(data.get("actor"), dict) else {},
            subject=data.get("subject") if isinstance(data.get("subject"), dict) else {},
            matched_policy=data.get("matched_policy") if isinstance(data.get("matched_policy"), dict) else {},
            inputs=data.get("inputs") if isinstance(data.get("inputs"), dict) else {},
            effects=data.get("effects") if isinstance(data.get("effects"), dict) else {},
            overrides=data.get("overrides") if isinstance(data.get("overrides"), dict) else {},
        )

    def to_dict(self):
        return {
            "domain": self.domain,
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "severity": self.severity,
            "actor": self.actor,
            "subject": self.subject,
            "matched_policy": self.matched_policy,
            "inputs": self.inputs,
            "effects": self.effects,
            "overrides": self.overrides,
        }
