"""Authentication and authorization domain records."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActorIdentity:
    id: str
    roles: tuple = field(default_factory=tuple)
    permissions: tuple = field(default_factory=tuple)
    source: str = "none"
    session_id: str = ""

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        actor_id = str(data.get("id") or "anonymous").strip()
        if not actor_id:
            raise ValueError("actor id is required")
        roles = tuple(str(item) for item in (data.get("roles") or []) if str(item or "").strip())
        permissions = tuple(str(item) for item in (data.get("permissions") or []) if str(item or "").strip())
        return cls(actor_id, roles, permissions, str(data.get("source") or "none"), str(data.get("session_id") or ""))

    def to_dict(self):
        row = {"id": self.id, "roles": list(self.roles), "permissions": list(self.permissions), "source": self.source}
        if self.session_id:
            row["session_id"] = self.session_id
        return row

    def has_permission(self, permission):
        return "*" in self.permissions or permission in self.permissions


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    permission: str
    action: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, data):
        data = data if isinstance(data, dict) else {}
        permission = str(data.get("permission") or "").strip()
        if not permission:
            raise ValueError("permission is required")
        return cls(bool(data.get("allowed")), permission, str(data.get("action") or ""), str(data.get("reason") or ""))

    def to_dict(self):
        return {"allowed": self.allowed, "permission": self.permission, "action": self.action, "reason": self.reason}
