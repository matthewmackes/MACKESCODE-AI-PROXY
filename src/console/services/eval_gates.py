"""Eval-on-change gate helpers."""
import hashlib
import json
import time


class EvalGateService:
    """Detect risky changes and evaluate linked eval evidence."""

    DEFAULT_POLICY = {
        "require_pass": False,
        "min_pass_rate": 0.8,
        "max_failure_rate": 0.2,
        "max_age_seconds": 7 * 24 * 60 * 60,
        "max_datasets": 3,
    }

    SURFACE_KEYWORDS = {
        "model_registry": ["model", "registry", "routing", "serverless", "dedicated", "smoke"],
        "gateway_policy": ["gateway", "routing", "failover", "slo", "policy", "smoke"],
        "prompt_template": ["prompt", "template", "regression", "smoke"],
        "run_profile": ["profile", "prompt", "model", "regression", "smoke"],
        "eval_baseline": ["eval", "baseline", "regression", "smoke"],
    }

    def __init__(self, list_datasets=None, list_runs=None, append_audit=None, clock=None):
        self.list_datasets = list_datasets or (lambda: [])
        self.list_runs = list_runs or (lambda limit=50: [])
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.clock = clock or time.time

    def preview(self, surface, before=None, after=None, policy=None, eval_gate=None):
        return self.evaluate(surface, before, after, policy=policy, eval_gate=eval_gate, enforce=False)

    def evaluate(self, surface, before=None, after=None, policy=None, eval_gate=None, enforce=True):
        eval_gate = eval_gate if isinstance(eval_gate, dict) else {}
        merged_policy = self.policy(policy, eval_gate.get("policy"))
        change = self.detect_change(surface, before, after)
        datasets = self.recommend_datasets(surface, change)
        runs = self._list_runs()
        evidence = self.evidence(surface, change, datasets, runs, eval_gate.get("evidence_run_ids"))
        override = self.override(eval_gate)
        required = bool(merged_policy.get("require_pass")) and bool(change.get("changed"))
        passing = self.evidence_passes(evidence, merged_policy)
        decision = "not_required"
        allowed = True
        if required:
            decision = "passed" if passing else "blocked"
            allowed = passing
            if not allowed and override.get("accepted"):
                decision = "override"
                allowed = True
        result = {
            "surface": str(surface or ""),
            "decision": decision,
            "allowed": allowed if enforce else True,
            "would_allow": allowed,
            "required": required,
            "change": change,
            "recommended_datasets": datasets,
            "evidence": evidence,
            "policy": merged_policy,
            "override": override,
            "created_at": self.clock(),
        }
        result["status"] = "allowed" if result["allowed"] else "blocked"
        return result

    def enforce(self, surface, before=None, after=None, policy=None, eval_gate=None, actor=None):
        result = self.evaluate(surface, before, after, policy=policy, eval_gate=eval_gate, enforce=True)
        request = {
            "surface": result["surface"],
            "decision": result["decision"],
            "required": result["required"],
            "change_hash": result["change"]["hash"],
            "recommended_datasets": [row["id"] for row in result["recommended_datasets"]],
            "evidence_run_ids": [row["id"] for row in result["evidence"]],
        }
        self.append_audit(
            "eval_gate.%s" % result["surface"],
            actor=actor,
            outcome="completed" if result["allowed"] else "denied",
            permission="eval.gate",
            request=request,
            status=200 if result["allowed"] else 409,
        )
        if not result["allowed"]:
            missing = ", ".join(row["id"] for row in result["recommended_datasets"]) or "recommended eval dataset"
            raise EvalGateBlocked("Eval gate requires passing evidence for %s." % missing, result)
        return result

    def policy(self, *policies):
        merged = dict(self.DEFAULT_POLICY)
        for policy in policies:
            if not isinstance(policy, dict):
                continue
            for key in ("require_pass", "min_pass_rate", "max_failure_rate", "max_age_seconds", "max_datasets"):
                if key in policy:
                    merged[key] = policy[key]
        merged["require_pass"] = bool(merged.get("require_pass"))
        merged["min_pass_rate"] = float(merged.get("min_pass_rate") or 0)
        merged["max_failure_rate"] = float(merged.get("max_failure_rate") or 1)
        merged["max_age_seconds"] = int(merged.get("max_age_seconds") or 0)
        merged["max_datasets"] = max(1, int(merged.get("max_datasets") or 3))
        return merged

    def detect_change(self, surface, before=None, after=None):
        before_norm = self._canonical(before)
        after_norm = self._canonical(after)
        before_hash = self._hash(before_norm)
        after_hash = self._hash(after_norm)
        fields = self.changed_fields(before_norm, after_norm)
        return {
            "surface": str(surface or ""),
            "changed": before_hash != after_hash,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "hash": after_hash,
            "fields": fields,
            "summary": self.summary(surface, fields),
        }

    def changed_fields(self, before, after):
        if not isinstance(before, dict) or not isinstance(after, dict):
            return [] if before == after else ["value"]
        keys = sorted(set(before) | set(after))
        return [key for key in keys if before.get(key) != after.get(key)]

    def recommend_datasets(self, surface, change):
        datasets = self._list_datasets()
        keywords = set(self.SURFACE_KEYWORDS.get(str(surface or ""), []))
        keywords.update(str(field).lower() for field in change.get("fields") or [])
        ranked = []
        for dataset in datasets:
            if not dataset.get("valid", True):
                continue
            haystack = self.dataset_haystack(dataset)
            score = sum(1 for keyword in keywords if keyword and keyword in haystack)
            if str(dataset.get("id") or "").lower() == "smoke":
                score += 1
            if score > 0:
                ranked.append((score, str(dataset.get("id") or ""), dataset))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = [self.dataset_summary(item[2]) for item in ranked[: self.DEFAULT_POLICY["max_datasets"]]]
        if not selected and datasets:
            selected = [self.dataset_summary(row) for row in datasets[:1] if row.get("valid", True)]
        return selected

    def evidence(self, surface, change, datasets, runs, requested_ids=None):
        requested = {str(item) for item in (requested_ids or []) if str(item or "").strip()}
        dataset_ids = {str(row.get("id") or row.get("name") or "") for row in datasets}
        rows = []
        for run in runs:
            run_id = str(run.get("id") or "")
            dataset = run.get("dataset")
            dataset_id = str((dataset or {}).get("id") if isinstance(dataset, dict) else dataset or "")
            gate = run.get("change_gate") if isinstance(run.get("change_gate"), dict) else {}
            matches_requested = run_id in requested
            matches_dataset = dataset_id in dataset_ids or str(dataset or "") in dataset_ids
            matches_gate = gate.get("surface") == surface and gate.get("change_hash") in {change.get("hash"), change.get("after_hash")}
            if not (matches_requested or matches_dataset or matches_gate):
                continue
            rows.append(self.run_evidence(run, dataset_id))
        rows.sort(key=lambda row: row.get("created_at") or 0, reverse=True)
        return rows

    def evidence_passes(self, rows, policy):
        if not rows:
            return False
        now = self.clock()
        for row in rows:
            age_ok = not policy.get("max_age_seconds") or not row.get("created_at") or (now - float(row.get("created_at") or 0)) <= policy["max_age_seconds"]
            if row.get("pass_rate") is not None:
                score_ok = float(row["pass_rate"]) >= policy["min_pass_rate"]
            else:
                score_ok = float(row.get("failure_rate") or 0) <= policy["max_failure_rate"]
            if age_ok and score_ok and row.get("requests", 0) > 0:
                return True
        return False

    def run_evidence(self, run, dataset_id):
        summaries = run.get("summary") if isinstance(run.get("summary"), list) else []
        requests = sum(int(row.get("requests") or 0) for row in summaries if isinstance(row, dict))
        failures = sum(int(row.get("failures") or 0) for row in summaries if isinstance(row, dict))
        pass_rates = [float(row.get("pass_rate")) for row in summaries if isinstance(row, dict) and row.get("pass_rate") is not None]
        failure_rate = round(failures / requests, 4) if requests else None
        pass_rate = round(sum(pass_rates) / len(pass_rates), 4) if pass_rates else None
        return {
            "id": run.get("id") or "",
            "dataset_id": dataset_id,
            "created_at": float(run.get("created_at") or 0),
            "models": run.get("models") or [],
            "requests": requests,
            "failures": failures,
            "failure_rate": failure_rate,
            "pass_rate": pass_rate,
            "status": "passing" if requests and (pass_rate is None or pass_rate >= self.DEFAULT_POLICY["min_pass_rate"]) and (failure_rate is None or failure_rate <= self.DEFAULT_POLICY["max_failure_rate"]) else "failing",
        }

    def override(self, eval_gate):
        override = eval_gate.get("override") if isinstance(eval_gate.get("override"), dict) else {}
        actor = override.get("actor") if isinstance(override.get("actor"), dict) else {}
        reason = str(override.get("reason") or "").strip()
        accepted = bool(reason and (actor.get("id") or eval_gate.get("actor_id")))
        return {"accepted": accepted, "reason": reason, "actor": actor}

    def summary(self, surface, fields):
        if not fields:
            return "No meaningful %s change detected." % surface
        return "%s changed: %s" % (str(surface or "item").replace("_", " "), ", ".join(fields[:8]))

    def dataset_haystack(self, dataset):
        metadata = dataset.get("metadata") if isinstance(dataset.get("metadata"), dict) else {}
        parts = [dataset.get("id"), dataset.get("name"), dataset.get("description")]
        parts.extend(metadata.keys())
        parts.extend(str(value) for value in metadata.values())
        return " ".join(str(part or "").lower() for part in parts)

    def dataset_summary(self, dataset):
        metadata = dataset.get("metadata") if isinstance(dataset.get("metadata"), dict) else {}
        return {
            "id": str(dataset.get("id") or dataset.get("name") or ""),
            "name": str(dataset.get("name") or dataset.get("id") or ""),
            "description": str(dataset.get("description") or ""),
            "example_count": int(dataset.get("example_count") or 0),
            "reason": metadata.get("gate_reason") or "matches changed surface",
        }

    def _list_datasets(self):
        try:
            return list(self.list_datasets() or [])
        except Exception:
            return []

    def _list_runs(self):
        try:
            return list(self.list_runs(limit=100) or [])
        except TypeError:
            return list(self.list_runs() or [])
        except Exception:
            return []

    def _canonical(self, value):
        if isinstance(value, dict):
            return {str(key): self._canonical(val) for key, val in sorted(value.items()) if key not in {"eval_gate", "actor", "csrf"}}
        if isinstance(value, list):
            return [self._canonical(item) for item in value]
        return value

    def _hash(self, value):
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EvalGateBlocked(ValueError):
    """Raised when a protected change lacks passing eval evidence."""

    def __init__(self, message, gate):
        super().__init__(message)
        self.gate = gate
