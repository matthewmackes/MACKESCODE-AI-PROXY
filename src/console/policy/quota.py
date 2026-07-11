"""Quota policy decision adapter."""
from src.console.policy.decisions import PolicyDecision


class QuotaPolicy:
    def from_quota_result(self, result):
        result = result if isinstance(result, dict) else {}
        managed = bool(result.get("managed"))
        allowed = bool(result.get("allowed", True))
        status = str(result.get("status") or ("allowed" if allowed else "blocked"))
        if not managed:
            status = "not_managed"
        cls = PolicyDecision.allow if allowed else PolicyDecision.deny
        return cls(
            "quota",
            status,
            "quota_%s" % status,
            severity="warning" if not allowed or status == "warning" else "info",
            actor=result.get("actor") if isinstance(result.get("actor"), dict) else {},
            subject={
                "action": result.get("action") or "",
                "route": result.get("route") or "",
                "models": result.get("models") or [],
                "project": result.get("project") or "",
            },
            matched_policy={
                "checks": result.get("checks") or [],
                "warnings": result.get("warnings") or [],
                "blocks": result.get("blocks") or [],
            },
            inputs={"requests": result.get("requests", 0), "usd": result.get("usd", 0)},
            effects={"consume_ledger": bool(result.get("allowed") and managed)},
        )
