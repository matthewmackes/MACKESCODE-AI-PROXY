"""RBAC policy adapter."""
from src.console.domain.auth import ActorIdentity
from src.console.policy.decisions import PolicyDecision


class RbacPolicy:
    def __init__(self, get_permissions=None, post_permissions=None):
        self.get_permissions = get_permissions or {}
        self.post_permissions = post_permissions or {}

    def permission_for(self, method, path):
        method = str(method or "").upper()
        if method == "GET":
            return self.get_permissions.get(path)
        if method == "POST":
            return self.post_permissions.get(path)
        return None

    def authorize(self, identity, permission, action=""):
        actor = ActorIdentity.from_dict(identity).to_dict()
        allowed = ActorIdentity.from_dict(actor).has_permission(permission)
        cls = PolicyDecision.allow if allowed else PolicyDecision.deny
        return cls(
            "rbac",
            action or permission,
            "permission_granted" if allowed else "missing_permission",
            actor=actor,
            subject={"permission": permission},
            matched_policy={"permission": permission, "action": action or permission},
            inputs={"roles": actor.get("roles", []), "permissions": actor.get("permissions", [])},
        )

    def request_decision(self, method, path, identity):
        permission_action = self.permission_for(method, path)
        if not permission_action:
            return PolicyDecision.allow(
                "rbac",
                "route.access",
                "route_unrestricted",
                actor=ActorIdentity.from_dict(identity).to_dict(),
                subject={"route": path, "method": str(method or "").upper()},
            )
        permission, action = permission_action
        decision = self.authorize(identity, permission, action)
        return PolicyDecision(
            domain=decision.domain,
            action=decision.action,
            allowed=decision.allowed,
            reason=decision.reason,
            severity=decision.severity,
            actor=decision.actor,
            subject={**decision.subject, "route": path, "method": str(method or "").upper()},
            matched_policy=decision.matched_policy,
            inputs=decision.inputs,
            effects={"audit_action": action, "permission": permission},
            overrides=decision.overrides,
        )
