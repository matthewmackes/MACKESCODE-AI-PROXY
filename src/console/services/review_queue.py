"""Human review queue persistence and promotion helpers."""
import json
import time
import uuid


class ReviewQueueService:
    """Persist review items for operator triage without storing raw secrets."""

    SENSITIVE_KEYS = {"authorization", "token", "api_key", "access_key", "secret", "password", "messages", "prompt", "input", "output", "screen", "raw"}
    STATUSES = {"open", "approved", "rejected", "closed"}

    def __init__(self, review_file, save_eval_dataset=None, worklist_file=None, append_audit=None, failure_taxonomy=None, clock=None, uuid_factory=None):
        self.review_file = review_file
        self.save_eval_dataset = save_eval_dataset or (lambda payload: payload)
        self.worklist_file = worklist_file
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.failure_taxonomy = failure_taxonomy
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def path(self):
        path = self.review_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def list_items(self, status="", severity="", reason=""):
        items = self._read_all()
        if status:
            items = [item for item in items if item.get("status") == status]
        if severity:
            items = [item for item in items if item.get("severity") == severity]
        if reason:
            needle = str(reason).lower()
            items = [item for item in items if needle in str(item.get("reason") or "").lower()]
        return sorted(items, key=lambda item: (item.get("status") != "open", -float(item.get("updated_at") or item.get("created_at") or 0)))

    def create(self, payload, actor=None, automatic=False):
        payload = payload if isinstance(payload, dict) else {}
        now = float(self.clock())
        item = {
            "id": str(payload.get("id") or "review_%d_%s" % (now, self.uuid_factory().hex[:8])),
            "schema_version": 1,
            "created_at": now,
            "updated_at": now,
            "status": "open",
            "severity": self._severity(payload.get("severity")),
            "reason": str(payload.get("reason") or ("automatic_review" if automatic else "manual_flag")).strip(),
            "title": str(payload.get("title") or payload.get("reason") or "Review item").strip(),
            "source": self.redact(payload.get("source") if isinstance(payload.get("source"), dict) else {}),
            "evidence": self.redact(payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}),
            "actor": self.redact(actor if isinstance(actor, dict) else payload.get("actor") if isinstance(payload.get("actor"), dict) else {}),
            "assignee": str(payload.get("assignee") or ""),
            "notes": str(payload.get("notes") or ""),
            "automatic": bool(automatic),
            "promotions": [],
        }
        self._append(item)
        self._audit("review.create", item, actor, status=201)
        return item

    def update(self, item_id, payload, actor=None):
        payload = payload if isinstance(payload, dict) else {}
        items = self._read_all()
        now = float(self.clock())
        found = None
        for item in items:
            if item.get("id") != item_id:
                continue
            found = item
            if payload.get("status") is not None:
                status = str(payload.get("status") or "").strip().lower()
                if status not in self.STATUSES:
                    raise ValueError("review status must be open, approved, rejected, or closed")
                item["status"] = status
            if payload.get("severity") is not None:
                item["severity"] = self._severity(payload.get("severity"))
            if payload.get("assignee") is not None:
                item["assignee"] = str(payload.get("assignee") or "")
            if payload.get("notes") is not None:
                item["notes"] = str(payload.get("notes") or "")
            if payload.get("decision") is not None:
                item["decision"] = str(payload.get("decision") or "")
            item["updated_at"] = now
            item["updated_by"] = self.redact(actor if isinstance(actor, dict) else payload.get("actor") if isinstance(payload.get("actor"), dict) else {})
            break
        if not found:
            raise ValueError("review item not found")
        self._write_all(items)
        self._audit("review.update", found, actor, status=200)
        return found

    def auto_from_eval_gate(self, gate, actor=None):
        if not isinstance(gate, dict) or gate.get("allowed"):
            return None
        return self.create({
            "severity": "high" if gate.get("required") else "medium",
            "reason": "eval_gate_blocked",
            "title": "Eval gate blocked %s" % gate.get("surface", "change"),
            "source": {
                "type": "eval_gate",
                "surface": gate.get("surface"),
                "change_hash": (gate.get("change") or {}).get("hash"),
                "target_id": gate.get("target_id"),
                "target_version": gate.get("target_version"),
            },
            "evidence": {
                "decision": gate.get("decision"),
                "required": gate.get("required"),
                "recommended_datasets": gate.get("recommended_datasets") or [],
                "evidence": gate.get("evidence") or [],
            },
        }, actor=actor, automatic=True)

    def auto_from_trace(self, trace, actor=None, high_cost_usd=1.0):
        trace = trace if isinstance(trace, dict) else {}
        reasons = []
        severity = "medium"
        failure = self.classify_failure(trace)
        if str(trace.get("status") or "").lower() in {"error", "failed", "denied"}:
            reasons.append("trace_failure:%s" % (failure.get("category") or "unknown"))
            severity = "high"
        if float(trace.get("cost_usd") or 0.0) >= float(high_cost_usd):
            reasons.append("high_cost_run")
        gateway = trace.get("gateway_policy") if isinstance(trace.get("gateway_policy"), dict) else {}
        if gateway.get("decision") in {"slo_route_rejected", "rate_limited", "circuit_open"}:
            reasons.append("routing_uncertainty")
        if not reasons:
            return None
        evidence = dict(trace)
        evidence["failure"] = failure
        return self.create({
            "severity": severity,
            "reason": ",".join(reasons),
            "title": "%s: trace %s" % (failure.get("title") or "Review trace", trace.get("trace_id") or "unknown"),
            "source": {"type": "trace", "trace_id": trace.get("trace_id"), "session": trace.get("session")},
            "evidence": evidence,
        }, actor=actor, automatic=True)

    def classify_failure(self, trace):
        if self.failure_taxonomy is not None:
            return self.failure_taxonomy.classify(trace, status=trace.get("http_status") or trace.get("status_code"))
        failure = trace.get("failure") if isinstance(trace.get("failure"), dict) else {}
        return {
            "category": failure.get("category") or trace.get("error_category") or "unknown",
            "title": failure.get("title") or "Review trace",
            "likely_cause": failure.get("likely_cause") or "",
            "suggested_fix": failure.get("suggested_fix") or "",
        }

    def promote_to_eval(self, item_id, payload, actor=None):
        item = self.get(item_id)
        if not item:
            raise ValueError("review item not found")
        payload = payload if isinstance(payload, dict) else {}
        dataset_id = str(payload.get("dataset_id") or "review-queue").strip()
        example = {
            "id": str(payload.get("example_id") or item_id),
            "input": str(payload.get("input") or item.get("evidence", {}).get("prompt_preview") or item.get("title") or item_id),
            "expected": str(payload.get("expected") or ""),
            "tags": ["review", item.get("reason", "manual")],
            "notes": str(payload.get("notes") or item.get("notes") or ""),
            "metadata": {"review_item_id": item_id, "source": item.get("source") or {}},
        }
        dataset = self.save_eval_dataset({
            "id": dataset_id,
            "name": payload.get("name") or "Review Queue",
            "description": "Examples promoted from human review queue.",
            "examples": [example],
        })
        return self._record_promotion(item_id, {"type": "eval_example", "dataset_id": dataset_id, "dataset": dataset}, actor)

    def promote_to_worklist(self, item_id, payload, actor=None):
        item = self.get(item_id)
        if not item:
            raise ValueError("review item not found")
        payload = payload if isinstance(payload, dict) else {}
        title = str(payload.get("title") or item.get("title") or item_id).strip()
        body = "\n\n### Review Follow-Up: %s\n- Source review: `%s`\n- Reason: %s\n- Severity: %s\n- Notes: %s\n" % (title, item_id, item.get("reason") or "", item.get("severity") or "", payload.get("notes") or item.get("notes") or "")
        worklist = self.worklist_file() if callable(self.worklist_file) else self.worklist_file
        if not worklist:
            raise ValueError("worklist file is not configured")
        with worklist.open("a", encoding="utf-8") as handle:
            handle.write(body)
        return self._record_promotion(item_id, {"type": "worklist_followup", "title": title, "worklist": str(worklist)}, actor)

    def get(self, item_id):
        return next((item for item in self._read_all() if item.get("id") == item_id), None)

    def redact(self, value):
        if isinstance(value, dict):
            clean = {}
            for key, val in value.items():
                lowered = str(key).lower()
                if lowered in self.SENSITIVE_KEYS or any(token in lowered for token in ("token", "secret", "password", "authorization")):
                    clean[key] = "[redacted]"
                else:
                    clean[key] = self.redact(val)
            return clean
        if isinstance(value, list):
            return [self.redact(item) for item in value[:50]]
        text = str(value) if isinstance(value, str) else value
        if isinstance(text, str) and len(text) > 500:
            return text[:500] + "...[truncated]"
        return text

    def _record_promotion(self, item_id, promotion, actor=None):
        item = self.get(item_id)
        if not item:
            raise ValueError("review item not found")
        promotion = {**promotion, "created_at": float(self.clock()), "actor": self.redact(actor or {})}
        promotions = list(item.get("promotions") or [])
        promotions.append(promotion)
        updated = self.update(item_id, {"notes": item.get("notes") or "", "actor": actor or {}}, actor=actor)
        updated["promotions"] = promotions
        items = self._read_all()
        for index, row in enumerate(items):
            if row.get("id") == item_id:
                items[index] = updated
                break
        self._write_all(items)
        self._audit("review.promote", updated, actor, status=200)
        return {"review": updated, "promotion": promotion}

    def _severity(self, value):
        value = str(value or "medium").strip().lower()
        return value if value in {"low", "medium", "high", "critical"} else "medium"

    def _read_all(self):
        path = self.path()
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("id"):
                rows.append(item)
        return rows

    def _append(self, item):
        with self.path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")

    def _write_all(self, items):
        self.path().write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in items), encoding="utf-8")

    def _audit(self, action, item, actor, status):
        self.append_audit(
            action,
            actor=actor,
            outcome="completed" if status < 400 else "failed",
            permission="review.queue",
            request={"review_id": item.get("id"), "status": item.get("status"), "reason": item.get("reason")},
            status=status,
        )
