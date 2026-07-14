"""v2 capability and policy-decision helpers."""
from __future__ import annotations

from typing import Any

from backend.v2.contracts import ActorIdentity, Capability, PolicyDecision
from src.console.handlers.auth_handler import ROLE_PERMISSIONS


CAPABILITY_DEFINITIONS = {
    "console.view": {
        "label": "View console",
        "permission": "view_console",
        "category": "console",
    },
    "chat.use": {
        "label": "Use model chat",
        "permission": "model_use",
        "category": "chat",
    },
    "speech.synthesize": {
        "label": "Generate speech",
        "permission": "model_use",
        "category": "chat",
    },
    "code.view": {
        "label": "View Code workspace",
        "permission": "view_console",
        "category": "code",
    },
    "code.attachments": {
        "label": "Upload Code screenshots",
        "permission": "model_use",
        "category": "code",
    },
    "research.use": {
        "label": "Use Research workspace",
        "permission": "model_use",
        "category": "research",
    },
    "create.use": {
        "label": "Use Create workspace",
        "permission": "model_use",
        "category": "create",
    },
    "models.view": {
        "label": "View model showcase",
        "permission": "view_console",
        "category": "models",
    },
    "run.view": {
        "label": "View Run workspace",
        "permission": "view_console",
        "category": "run",
    },
    "run.edit": {
        "label": "Edit Run profiles and prompt templates",
        "permission": "model_use",
        "category": "run",
    },
    "models.admin": {
        "label": "Manage model registry",
        "permission": "model_admin",
        "category": "admin",
    },
    "tmux.control": {
        "label": "Control tmux and terminal sessions",
        "permission": "tmux_control",
        "category": "run",
    },
    "tui.view": {
        "label": "View proxy TUI",
        "permission": "view_console",
        "category": "console",
    },
    "tui.control": {
        "label": "Control proxy TUI",
        "permission": "tmux_control",
        "category": "console",
    },
    "startup.view": {
        "label": "View startup services",
        "permission": "view_console",
        "category": "admin",
    },
    "startup.admin": {
        "label": "Manage startup services",
        "permission": "startup_admin",
        "category": "admin",
    },
    "irc.admin": {
        "label": "Manage IRC bridge",
        "permission": "startup_admin",
        "category": "admin",
    },
    "evals.run": {
        "label": "Run evals",
        "permission": "eval_run",
        "category": "automation",
    },
    "operate.review.manage": {
        "label": "Manage review queue",
        "permission": "review_queue",
        "category": "automation",
    },
    "operate.repository.import": {
        "label": "Import repository context",
        "permission": "repository_context_import",
        "category": "automation",
    },
    "operate.rollback.admin": {
        "label": "Manage release and rollback",
        "permission": "rollback_admin",
        "category": "automation",
    },
    "operate.config_drift.admin": {
        "label": "Resolve config drift",
        "permission": "config_drift_admin",
        "category": "govern",
    },
    "operate.automation.admin": {
        "label": "Manage automation dispatch",
        "permission": "automation_admin",
        "category": "automation",
    },
    "budget.admin": {
        "label": "Manage budgets",
        "permission": "budget_admin",
        "category": "govern",
    },
    "cost_control.edit": {
        "label": "Edit cost-control thresholds",
        "permission": "cost_control_edit",
        "category": "govern",
    },
    "cost_control.override": {
        "label": "Override cost-control pause",
        "permission": "cost_control_override",
        "category": "govern",
    },
    "billing.view": {
        "label": "View billing and reporting",
        "permission": "view_billing",
        "category": "report",
    },
    "analyst.view": {
        "label": "View AI performance analyst",
        "permission": "view_console",
        "category": "monitor",
    },
    "analyst.run": {
        "label": "Run AI performance analyst",
        "permission": "model_use",
        "category": "monitor",
    },
    "analyst.ack": {
        "label": "Acknowledge analyst findings",
        "permission": "view_console",
        "category": "monitor",
    },
    "dedicated.admin": {
        "label": "Manage Dedicated Inference",
        "permission": "dedicated_admin",
        "category": "admin",
    },
    "auth.sessions.admin": {
        "label": "Manage auth sessions",
        "permission": "auth_session_admin",
        "category": "admin",
    },
}


class V2CapabilityService:
    """Compute v2 UI/action capabilities from existing console identities."""

    def role_permissions(self) -> dict[str, list[str]]:
        return {role: sorted(perms) for role, perms in ROLE_PERMISSIONS.items()}

    def has_permission(self, identity: ActorIdentity, permission: str) -> bool:
        permissions = set(identity.permissions)
        return "*" in permissions or permission in permissions

    def capability(self, identity: ActorIdentity, key: str, definition: dict[str, str]) -> Capability:
        permission = definition["permission"]
        allowed = self.has_permission(identity, permission)
        return Capability(
            key=key,
            label=definition["label"],
            allowed=allowed,
            required_permission=permission,
            category=definition["category"],
            reason="" if allowed else "missing_permission:%s" % permission,
        )

    def capabilities_for(self, raw_identity: dict[str, Any] | ActorIdentity | None) -> dict[str, Any]:
        identity = raw_identity if isinstance(raw_identity, ActorIdentity) else ActorIdentity.from_dict(raw_identity)
        capabilities = {
            key: self.capability(identity, key, definition).to_dict()
            for key, definition in sorted(CAPABILITY_DEFINITIONS.items())
        }
        allowed = sorted(key for key, payload in capabilities.items() if payload["allowed"])
        return {
            "actor": identity.to_dict(),
            "capabilities": capabilities,
            "allowed": allowed,
            "roles": self.role_permissions(),
        }

    def decide(self, raw_identity: dict[str, Any] | ActorIdentity | None, action: str) -> PolicyDecision:
        identity = raw_identity if isinstance(raw_identity, ActorIdentity) else ActorIdentity.from_dict(raw_identity)
        definition = CAPABILITY_DEFINITIONS.get(action)
        if not definition:
            return PolicyDecision(
                action=action,
                allowed=False,
                reason="unknown_action",
                actor_id=identity.id,
            )
        permission = definition["permission"]
        allowed = self.has_permission(identity, permission)
        return PolicyDecision(
            action=action,
            allowed=allowed,
            required_permission=permission,
            reason="allowed" if allowed else "missing_permission",
            actor_id=identity.id,
            details={"category": definition["category"], "label": definition["label"]},
        )
