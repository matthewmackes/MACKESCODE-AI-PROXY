"""Gateway policy decision adapter."""
from src.console.policy.decisions import PolicyDecision


class GatewayPolicy:
    def from_metadata(self, metadata):
        metadata = metadata if isinstance(metadata, dict) else {}
        decision = str(metadata.get("decision") or metadata.get("routing_reason") or "route")
        blocked = decision in {"rate_limited", "circuit_open", "budget_exceeded_rejection", "access_forbidden_rejection", "slo_route_rejected"}
        cls = PolicyDecision.deny if blocked else PolicyDecision.allow
        return cls(
            "gateway",
            decision,
            str(metadata.get("reason") or decision),
            severity="warning" if blocked else "info",
            subject={"model": metadata.get("model") or metadata.get("selected_model") or ""},
            matched_policy=metadata,
            effects={"fallback": bool(metadata.get("fallback") or metadata.get("to"))},
        )
