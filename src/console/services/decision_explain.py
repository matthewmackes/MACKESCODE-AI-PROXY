"""Explain automated routing, quota, eval, and lifecycle decisions."""
import hashlib
import re
import time


class DecisionExplanationService:
    """Normalize existing decision metadata into operator-readable records."""

    sensitive_re = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|dop_v1_[A-Za-z0-9_\-]+|gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|Bearer\s+[A-Za-z0-9._\-]+|token=[^&\s]+)", re.I)
    sensitive_keys = {"prompt", "content", "message", "messages", "response", "output", "raw", "token", "secret", "authorization", "api_key", "access_key"}

    def __init__(self, read_traces=None, policy_files=None, clock=None):
        self.read_traces = read_traces or (lambda **kwargs: [])
        self.policy_files = policy_files or (lambda: {})
        self.clock = clock or time.time

    def payload(self, request=None):
        request = request if isinstance(request, dict) else {}
        record = self.source_record(request)
        explanation = self.explain(record, requested_type=str(request.get("type") or ""))
        explanation["generated_at"] = float(self.clock())
        explanation["privacy"] = "Prompts, responses, raw output, tokens, and secret-like values are redacted before display."
        return explanation

    def source_record(self, request):
        if isinstance(request.get("record"), dict):
            return request["record"]
        trace_id = str(request.get("trace_id") or "").strip()
        if trace_id:
            for trace in self.read_traces(limit=500) or []:
                if str(trace.get("trace_id") or "") == trace_id:
                    return trace
            raise ValueError("decision trace not found")
        return request

    def explain(self, record, requested_type=""):
        record = record if isinstance(record, dict) else {}
        kind = requested_type or self.kind(record)
        clean = self.redact(record)
        selected = self.selected_action(kind, clean)
        inputs = self.inputs(kind, clean)
        matched_policy = self.matched_policy(kind, clean)
        candidates = self.candidates(kind, clean)
        rejected = self.rejected(kind, clean, candidates)
        evidence = self.evidence_links(kind, clean)
        deterministic = kind in {"gateway_routing", "quota", "budget", "eval_gate", "dedicated_lifecycle", "model_access", "authorization"}
        return {
            "id": self.explanation_id(kind, clean),
            "type": kind,
            "title": self.title(kind, selected),
            "deterministic": deterministic,
            "confidence": "high" if deterministic else "medium",
            "selected_action": selected,
            "reason": self.reason(kind, clean, selected),
            "inputs": inputs,
            "matched_policy": matched_policy,
            "candidates": candidates,
            "rejected_alternatives": rejected,
            "evidence_links": evidence,
            "raw": clean,
        }

    def kind(self, record):
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        domain = str(policy_decision.get("domain") or "").strip()
        if domain == "gateway":
            return "gateway_routing"
        if domain == "quota":
            return "quota"
        if domain == "dedicated":
            return "dedicated_lifecycle"
        if domain == "rbac":
            return "authorization"
        if isinstance(record.get("eval_gate"), dict) or {"surface", "recommended_datasets", "evidence", "override"} & set(record):
            return "eval_gate"
        if isinstance(record.get("quota"), dict) or any(key in record for key in ("blocks", "warnings", "checks")) and record.get("action"):
            return "quota"
        if isinstance(record.get("budget_state"), dict) or isinstance(record.get("budget_impact"), dict):
            return "budget"
        if isinstance(record.get("dedicated_lifecycle"), dict) or isinstance(record.get("dedicated"), dict) or str(record.get("endpoint_mode") or "") == "dedicated":
            return "dedicated_lifecycle"
        if isinstance(record.get("gateway_policy"), dict) or isinstance((record.get("routing") or {}).get("policy_decision"), dict) or record.get("routing_reason"):
            return "gateway_routing"
        if record.get("access_status") or record.get("deprecation"):
            return "model_access"
        return "generic"

    def selected_action(self, kind, record):
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        if policy_decision.get("action"):
            return policy_decision.get("action")
        gateway = record.get("gateway_policy") if isinstance(record.get("gateway_policy"), dict) else {}
        routing = record.get("routing") if isinstance(record.get("routing"), dict) else {}
        policy = routing.get("policy_decision") if isinstance(routing.get("policy_decision"), dict) else {}
        if kind == "gateway_routing":
            return gateway.get("decision") or policy.get("decision") or routing.get("reason") or record.get("routing_reason") or "route"
        if kind == "quota":
            return "blocked" if record.get("blocks") or (record.get("quota") or {}).get("allowed") is False else record.get("status") or "allowed"
        if kind == "budget":
            state = record.get("budget_state") if isinstance(record.get("budget_state"), dict) else {}
            return "blocked" if state.get("critical") else "warn" if state.get("warning") else "allow"
        if kind == "eval_gate":
            return record.get("decision") or (record.get("eval_gate") or {}).get("decision") or "not_required"
        if kind == "dedicated_lifecycle":
            lifecycle = record.get("dedicated_lifecycle") if isinstance(record.get("dedicated_lifecycle"), dict) else record.get("dedicated") if isinstance(record.get("dedicated"), dict) else {}
            return lifecycle.get("decision") or lifecycle.get("state") or record.get("routing_reason") or "dedicated_policy"
        if kind == "model_access":
            return record.get("access_status") or (record.get("deprecation") or {}).get("status") or "model_available"
        if kind == "authorization":
            return policy_decision.get("action") or "authorize"
        return record.get("decision") or record.get("status") or "decision"

    def reason(self, kind, record, selected):
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        if policy_decision.get("reason"):
            return policy_decision.get("reason")
        if kind == "gateway_routing":
            return "Gateway selected this route from routing metadata and policy decision fields."
        if kind == "quota":
            return "Quota policy compared requested units against matched daily/monthly limits."
        if kind == "budget":
            return "Budget guard evaluated projected spend against configured limits."
        if kind == "eval_gate":
            return "Eval gate compared changed surface metadata with recent passing evidence and override policy."
        if kind == "dedicated_lifecycle":
            return "Dedicated lifecycle policy evaluated endpoint state, budget, idle, and health signals."
        if kind == "model_access":
            return "Model registry and access-audit metadata determined model availability."
        if kind == "authorization":
            return "RBAC policy compared the actor identity with the required route permission."
        return "Explanation inferred from available metadata."

    def inputs(self, kind, record):
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        if policy_decision.get("inputs"):
            return policy_decision.get("inputs")
        keys = {
            "gateway_routing": ("requested_model", "routed_model", "endpoint_mode", "routing_reason", "provider", "status"),
            "quota": ("action", "route", "actor", "models", "project", "requests", "usd", "status"),
            "budget": ("budget_state", "budget_impact", "cost", "cost_usd"),
            "eval_gate": ("surface", "required", "change", "recommended_datasets", "evidence", "override"),
            "dedicated_lifecycle": ("dedicated_lifecycle", "dedicated", "budget_state", "routing_reason"),
            "model_access": ("id", "model", "access_status", "enabled", "deprecation", "policy_decision"),
            "authorization": ("actor", "permission", "path", "method", "policy_decision"),
        }.get(kind, tuple(record.keys()))
        return {key: record.get(key) for key in keys if key in record}

    def matched_policy(self, kind, record):
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        if policy_decision.get("matched_policy"):
            return policy_decision.get("matched_policy")
        if kind == "gateway_routing":
            return record.get("gateway_policy") or (record.get("routing") or {}).get("policy_decision") or {}
        if kind == "quota":
            return {"checks": record.get("checks") or (record.get("quota") or {}).get("checks") or [], "blocks": record.get("blocks") or (record.get("quota") or {}).get("blocks") or [], "warnings": record.get("warnings") or (record.get("quota") or {}).get("warnings") or []}
        if kind == "budget":
            return record.get("budget_state") or record.get("budget_impact") or {}
        if kind == "eval_gate":
            gate = record.get("eval_gate") if isinstance(record.get("eval_gate"), dict) else record
            return {"policy": gate.get("policy"), "override": gate.get("override"), "required": gate.get("required")}
        if kind == "dedicated_lifecycle":
            lifecycle = record.get("dedicated_lifecycle") if isinstance(record.get("dedicated_lifecycle"), dict) else record.get("dedicated") or {}
            return {key: lifecycle.get(key) for key in ("state", "budget_state", "idle_policy", "unhealthy_policy", "policy_decision") if key in lifecycle}
        if kind == "model_access":
            return record.get("policy_decision") or record.get("deprecation") or {}
        return {}

    def candidates(self, kind, record):
        policy_decision = record.get("policy_decision") if isinstance(record.get("policy_decision"), dict) else {}
        subject = policy_decision.get("subject") if isinstance(policy_decision.get("subject"), dict) else {}
        if subject:
            return [subject]
        gateway = record.get("gateway_policy") if isinstance(record.get("gateway_policy"), dict) else {}
        if kind == "gateway_routing":
            slo = gateway.get("slo_routing") if isinstance(gateway.get("slo_routing"), dict) else {}
            return slo.get("candidates") or [item for item in (record.get("requested_model"), record.get("routed_model")) if item]
        if kind == "quota":
            return record.get("checks") or (record.get("quota") or {}).get("checks") or []
        if kind == "eval_gate":
            return record.get("recommended_datasets") or (record.get("eval_gate") or {}).get("recommended_datasets") or []
        if kind == "dedicated_lifecycle":
            return [record.get("routed_model"), (record.get("dedicated") or {}).get("fallback_model") if isinstance(record.get("dedicated"), dict) else None]
        return []

    def rejected(self, kind, record, candidates):
        if kind == "quota":
            return record.get("blocks") or (record.get("quota") or {}).get("blocks") or []
        gateway = record.get("gateway_policy") if isinstance(record.get("gateway_policy"), dict) else {}
        if kind == "gateway_routing":
            slo = gateway.get("slo_routing") if isinstance(gateway.get("slo_routing"), dict) else {}
            return slo.get("rejected") or []
        if kind == "eval_gate":
            return [] if (record.get("allowed") or (record.get("eval_gate") or {}).get("allowed")) else record.get("recommended_datasets") or []
        return []

    def evidence_links(self, kind, record):
        links = []
        if record.get("trace_id"):
            links.append({"type": "trace", "id": record.get("trace_id")})
        for name, path in (self.policy_files() or {}).items():
            links.append({"type": "policy_file", "label": name, "path": str(path)})
        if record.get("audit_id"):
            links.append({"type": "audit", "id": record.get("audit_id")})
        return links

    def title(self, kind, selected):
        return "%s: %s" % (kind.replace("_", " ").title(), selected)

    def explanation_id(self, kind, record):
        basis = "%s:%s:%s:%s" % (kind, record.get("trace_id") or "", record.get("decision") or "", record.get("routing_reason") or "")
        return "decision:%s" % hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    def redact(self, value):
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                if str(key).lower() in self.sensitive_keys or any(part in str(key).lower() for part in self.sensitive_keys):
                    clean[key] = "[redacted]"
                else:
                    clean[key] = self.redact(item)
            return clean
        if isinstance(value, list):
            return [self.redact(item) for item in value[:50]]
        if isinstance(value, str):
            text = self.sensitive_re.sub("[redacted]", value)
            return text[:2000] + ("...[truncated]" if len(text) > 2000 else "")
        return value
