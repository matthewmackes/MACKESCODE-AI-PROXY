"""Dedicated lifecycle policy adapter."""
from src.console.policy.decisions import PolicyDecision


class DedicatedPolicy:
    def build_budget(self, budget_state, cfg=None):
        cfg = cfg if isinstance(cfg, dict) else {}
        state = budget_state if isinstance(budget_state, dict) else {}
        critical = bool(state.get("critical"))
        warning = bool(state.get("warning"))
        if critical:
            return PolicyDecision.deny(
                "dedicated",
                "build.block",
                "daily_budget_critical",
                severity="error",
                subject={"model_id": cfg.get("model_id") or "dedicated-inference"},
                matched_policy=state,
            )
        return PolicyDecision.allow(
            "dedicated",
            "build.warn" if warning else "build.allow",
            "daily_budget_warning" if warning else "within_budget",
            severity="warning" if warning else "info",
            subject={"model_id": cfg.get("model_id") or "dedicated-inference"},
            matched_policy=state,
        )

    def lifecycle(self, cfg, idle_policy, unhealthy_policy):
        cfg = cfg if isinstance(cfg, dict) else {}
        idle = idle_policy if isinstance(idle_policy, dict) else {}
        unhealthy = unhealthy_policy if isinstance(unhealthy_policy, dict) else {}
        subject = {"model_id": cfg.get("model_id") or "dedicated-inference", "state": cfg.get("state") or "not_configured"}
        matched = {"idle_policy": idle, "unhealthy_policy": unhealthy}
        if cfg.get("state") != "active":
            return PolicyDecision.allow("dedicated", "lifecycle.none", "not_active", subject=subject, matched_policy=matched)
        if unhealthy.get("teardown_due"):
            return PolicyDecision.deny("dedicated", "teardown", "unhealthy_timeout", severity="error", subject=subject, matched_policy=matched, effects={"teardown": True})
        if idle.get("teardown_due"):
            reason = "keep_alive_extension_expired" if idle.get("extension_expired_unused") else "idle_timeout"
            return PolicyDecision.deny("dedicated", "teardown", reason, severity="warning", subject=subject, matched_policy=matched, effects={"teardown": True})
        if idle.get("warning"):
            return PolicyDecision.allow("dedicated", "warning", "idle_warning", severity="warning", subject=subject, matched_policy=matched)
        return PolicyDecision.allow("dedicated", "lifecycle.none", "within_policy", subject=subject, matched_policy=matched)

    def keep_alive(self, cfg, seconds, allowed_seconds):
        cfg = cfg if isinstance(cfg, dict) else {}
        subject = {"model_id": cfg.get("model_id") or "dedicated-inference", "state": cfg.get("state") or "not_configured"}
        inputs = {"seconds": seconds, "allowed_seconds": list(allowed_seconds)}
        if seconds not in allowed_seconds:
            return PolicyDecision.deny("dedicated", "keep_alive.deny", "invalid_duration", subject=subject, inputs=inputs)
        if cfg.get("state") != "active":
            return PolicyDecision.deny("dedicated", "keep_alive.deny", "not_active", subject=subject, inputs=inputs)
        return PolicyDecision.allow("dedicated", "keep_alive.allow", "active_duration_allowed", subject=subject, inputs=inputs)
