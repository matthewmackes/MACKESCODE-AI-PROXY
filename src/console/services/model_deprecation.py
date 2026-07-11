"""Model deprecation detection, migration preview, and rollback."""
import copy
import hashlib
import json
import time


class ModelDeprecationService:
    """Guides operators from unavailable or deprecated models to replacements."""

    disruptive_access_states = {"removed", "forbidden", "unauthorized"}
    warning_access_states = {"rate_limited", "probe_failed", "repeated_probe_failed"}
    deprecated_states = {"deprecated", "removed", "forbidden", "unauthorized", "superseded", "high_cost"}

    def __init__(
        self,
        load_model_registry,
        save_model_registry,
        refresh_model_globals,
        proxy_sync_payload,
        model_scorecards_payload,
        list_chats,
        load_chat,
        save_chat,
        list_eval_datasets,
        load_eval_dataset,
        save_eval_dataset,
        list_eval_runs,
        list_comparison_reports,
        load_comparison_report,
        save_comparison_report,
        gateway_policy_file,
        state_file,
        run_store=None,
        append_audit=None,
        clock=None,
    ):
        self.load_model_registry = load_model_registry
        self.save_model_registry = save_model_registry
        self.refresh_model_globals = refresh_model_globals
        self.proxy_sync_payload = proxy_sync_payload
        self.model_scorecards_payload = model_scorecards_payload
        self.list_chats = list_chats
        self.load_chat = load_chat
        self.save_chat = save_chat
        self.list_eval_datasets = list_eval_datasets
        self.load_eval_dataset = load_eval_dataset
        self.save_eval_dataset = save_eval_dataset
        self.list_eval_runs = list_eval_runs
        self.list_comparison_reports = list_comparison_reports
        self.load_comparison_report = load_comparison_report
        self.save_comparison_report = save_comparison_report
        self.gateway_policy_file = gateway_policy_file
        self.state_file = state_file
        self.run_store = run_store
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.clock = clock or time.time

    def models(self):
        return [row for row in (self.load_model_registry(include_disabled=True) or []) if isinstance(row, dict) and row.get("id")]

    def state_path(self):
        path = self.state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def load_state(self):
        path = self.state_path()
        if not path.exists():
            return {"schema_version": 1, "migrations": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema_version": 1, "migrations": []}
        if not isinstance(data, dict):
            return {"schema_version": 1, "migrations": []}
        data.setdefault("schema_version", 1)
        data.setdefault("migrations", [])
        return data

    def save_state(self, state):
        path = self.state_path()
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state

    def model_by_id(self, model_id):
        return next((row for row in self.models() if row.get("id") == model_id), None)

    def deprecation_state(self, model, high_cost_threshold_usd=10.0):
        dep = model.get("deprecation") if isinstance(model.get("deprecation"), dict) else {}
        status = str(dep.get("status") or "").strip().lower()
        access = str(model.get("access_status") or "").strip().lower()
        superseded_by = dep.get("replacement_model") or model.get("replacement_model") or model.get("superseded_by") or ""
        reason = dep.get("reason") or model.get("last_error") or ""
        severity = "medium"
        if status:
            severity = "high" if status in self.deprecated_states else "medium"
        elif access in self.disruptive_access_states:
            status = access
            severity = "high"
            reason = reason or "Provider access audit reports %s." % access
        elif access in self.warning_access_states:
            status = access
            severity = "medium"
            reason = reason or "Provider access audit is unstable."
        elif superseded_by:
            status = "superseded"
            reason = reason or "Model has a configured replacement."
        else:
            pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
            prices = []
            for value in pricing.values():
                try:
                    if float(value or 0) > 0:
                        prices.append(float(value))
                except (TypeError, ValueError):
                    continue
            if prices and max(prices) >= float(high_cost_threshold_usd or 10.0):
                status = "high_cost"
                severity = "medium"
                reason = "Configured price exceeds the high-cost threshold."
        if not status:
            return None
        return {
            "model": model.get("id"),
            "display_name": model.get("display_name") or model.get("id"),
            "type": model.get("type") or "unknown",
            "status": status,
            "severity": severity,
            "reason": reason,
            "replacement_model": superseded_by,
            "access_status": model.get("access_status") or "not_checked",
            "enabled": bool(model.get("enabled")),
            "route_blocked": True,
        }

    def deprecated_models(self, high_cost_threshold_usd=10.0):
        rows = []
        for model in self.models():
            item = self.deprecation_state(model, high_cost_threshold_usd=high_cost_threshold_usd)
            if item:
                rows.append(item)
        rows.sort(key=lambda item: (item["severity"] != "high", item["model"]))
        return rows

    def contains_model(self, payload, model_id):
        if isinstance(payload, dict):
            return any(self.contains_model(key, model_id) or self.contains_model(value, model_id) for key, value in payload.items())
        if isinstance(payload, list):
            return any(self.contains_model(item, model_id) for item in payload)
        return model_id in str(payload or "")

    def replace_model(self, payload, old_model, new_model):
        if isinstance(payload, dict):
            return {
                (key.replace(old_model, new_model) if isinstance(key, str) else key): self.replace_model(value, old_model, new_model)
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self.replace_model(item, old_model, new_model) for item in payload]
        if isinstance(payload, str):
            return payload.replace(old_model, new_model)
        return payload

    def affected_artifacts(self, model_id):
        artifacts = []
        models = self.models()
        if any(row.get("id") == model_id for row in models):
            artifacts.append({"type": "model_registry", "id": model_id, "label": "Model registry entry"})
        path = self.gateway_policy_file()
        if path.exists():
            try:
                policy = json.loads(path.read_text(encoding="utf-8"))
                if self.contains_model(policy, model_id):
                    artifacts.append({"type": "gateway_policy", "id": str(path), "label": "Gateway policy"})
            except (OSError, ValueError):
                pass
        for item in self.list_chats() or []:
            doc = self.load_chat(item.get("id")) if item.get("id") else None
            if doc and self.contains_model(doc, model_id):
                artifacts.append({"type": "saved_chat", "id": doc.get("id"), "label": doc.get("title") or doc.get("id")})
        for item in self.list_eval_datasets() or []:
            try:
                dataset = self.load_eval_dataset(item.get("id"))
            except (ValueError, OSError, TypeError):
                dataset = None
            if dataset and self.contains_model(dataset, model_id):
                artifacts.append({"type": "eval_dataset", "id": dataset.get("id"), "label": dataset.get("name") or dataset.get("id")})
        for run in self.list_eval_runs(limit=50) or []:
            if self.contains_model(run, model_id):
                artifacts.append({"type": "eval_run", "id": run.get("id"), "label": "Eval run %s" % (run.get("id") or "")})
        for item in self.list_comparison_reports() or []:
            report = self.load_comparison_report(item.get("id")) if item.get("id") else None
            if report and self.contains_model(report, model_id):
                artifacts.append({"type": "comparison_report", "id": report.get("id"), "label": report.get("title") or report.get("id")})
        if self.run_store:
            for item in self.run_store.list_prompt_templates():
                if self.contains_model(item, model_id):
                    artifacts.append({"type": "prompt_template", "id": item.get("id"), "label": item.get("name") or item.get("id")})
            for item in self.run_store.list_run_profiles():
                if self.contains_model(item, model_id):
                    artifacts.append({"type": "run_profile", "id": item.get("id"), "label": item.get("name") or item.get("id")})
        return artifacts

    def model_cost(self, model):
        pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
        values = []
        for value in pricing.values():
            try:
                if float(value or 0) > 0:
                    values.append(float(value))
            except (TypeError, ValueError):
                continue
        return max(values) if values else 0.0

    def replacement_recommendations(self, model_id, limit=5):
        source = self.model_by_id(model_id)
        if not source:
            return []
        scorecards = (self.model_scorecards_payload(days=30) or {}).get("by_model") or {}
        source_type = source.get("type") or "text"
        rows = []
        for model in self.models():
            if model.get("id") == model_id or model.get("type") != source_type:
                continue
            if self.deprecation_state(model):
                continue
            if model.get("enabled") is False:
                continue
            if model.get("serverless") and source_type == "text" and model.get("access_status") != "ok":
                continue
            card = scorecards.get(model.get("id")) or {}
            context_ok = int(model.get("context_window") or 0) >= int(source.get("context_window") or 0)
            cost = self.model_cost(model)
            rows.append({
                "model": model.get("id"),
                "display_name": model.get("display_name") or model.get("id"),
                "score": int(card.get("score") or 0),
                "confidence": card.get("confidence") or "unavailable",
                "cost": cost,
                "context_window": int(model.get("context_window") or 0),
                "access_status": model.get("access_status") or "not_checked",
                "rationale": self.recommendation_rationale(source, model, card, context_ok),
            })
        rows.sort(key=lambda item: (-item["score"], item["cost"], item["model"]))
        return rows[:max(1, int(limit or 5))]

    def recommendation_rationale(self, source, model, scorecard, context_ok):
        parts = []
        if scorecard.get("confidence") == "measured":
            parts.append("measured score %s" % scorecard.get("score"))
        elif scorecard.get("confidence"):
            parts.append("%s scorecard" % scorecard.get("confidence"))
        if context_ok:
            parts.append("context window is not smaller")
        if model.get("access_status"):
            parts.append("access %s" % model.get("access_status"))
        if self.model_cost(model) and self.model_cost(source):
            parts.append("max listed price %.3g vs %.3g" % (self.model_cost(model), self.model_cost(source)))
        return "; ".join(parts) or "same model type and currently routeable"

    def payload(self, data=None):
        data = data if isinstance(data, dict) else {}
        threshold = float(data.get("high_cost_threshold_usd") or 10.0)
        rows = self.deprecated_models(high_cost_threshold_usd=threshold)
        for row in rows:
            row["affected_count"] = len(self.affected_artifacts(row["model"]))
            row["recommendations"] = self.replacement_recommendations(row["model"], limit=3)
        return {
            "generated_at": self.clock(),
            "deprecated_models": rows,
            "summary": {"count": len(rows), "high": len([row for row in rows if row["severity"] == "high"])},
            "migrations": [self.migration_summary(row) for row in self.load_state().get("migrations", [])],
        }

    def preview(self, data):
        data = data if isinstance(data, dict) else {}
        model_id = str(data.get("model") or data.get("model_id") or "").strip()
        if not model_id:
            raise ValueError("model_id is required")
        replacement = str(data.get("replacement_model") or "").strip()
        recommendations = self.replacement_recommendations(model_id, limit=5)
        if not replacement and recommendations:
            replacement = recommendations[0]["model"]
        affected = self.affected_artifacts(model_id)
        return {
            "model": model_id,
            "replacement_model": replacement,
            "deprecation": self.deprecation_state(self.model_by_id(model_id) or {}) or {"model": model_id, "status": "manual_review", "severity": "medium"},
            "affected": affected,
            "affected_summary": self.summarize_affected(affected),
            "recommendations": recommendations,
            "changes": self.planned_changes(affected, model_id, replacement),
            "eval_gate": {
                "surface": "model_deprecation",
                "recommended": True,
                "reason": "Run a focused eval comparing the deprecated model's replacement before applying to critical routes.",
            },
            "rollback": {"available_after_apply": True, "state_file": str(self.state_path())},
        }

    def summarize_affected(self, affected):
        summary = {}
        for item in affected:
            summary[item["type"]] = summary.get(item["type"], 0) + 1
        return summary

    def planned_changes(self, affected, old_model, new_model):
        changes = []
        if not new_model:
            changes.append({"type": "operator_input_required", "message": "Select a replacement model before applying migration."})
            return changes
        changes.append({"type": "model_registry", "message": "Disable %s, set deprecation metadata, and point to %s." % (old_model, new_model)})
        for item in affected:
            if item["type"] not in {"model_registry", "eval_run"}:
                changes.append({"type": item["type"], "id": item.get("id"), "message": "Replace %s with %s." % (old_model, new_model)})
        return changes

    def migration_id(self, model_id, replacement):
        raw = "%s:%s:%s" % (model_id, replacement, self.clock())
        return "model-migration-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def backup_artifacts(self, affected):
        backup = {"models": copy.deepcopy(self.models()), "gateway_policy": None, "saved_chats": [], "eval_datasets": [], "comparison_reports": [], "run_profiles": [], "prompt_templates": []}
        path = self.gateway_policy_file()
        if path.exists():
            try:
                backup["gateway_policy"] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                backup["gateway_policy"] = None
        for item in affected:
            if item["type"] == "saved_chat":
                doc = self.load_chat(item.get("id"))
                if doc:
                    backup["saved_chats"].append(doc)
            elif item["type"] == "eval_dataset":
                try:
                    backup["eval_datasets"].append(self.load_eval_dataset(item.get("id")))
                except (ValueError, OSError, TypeError):
                    pass
            elif item["type"] == "comparison_report":
                report = self.load_comparison_report(item.get("id"))
                if report:
                    backup["comparison_reports"].append(report)
            elif item["type"] == "run_profile" and self.run_store:
                profile = next((row for row in self.run_store.list_run_profiles() if row.get("id") == item.get("id")), None)
                if profile:
                    backup["run_profiles"].append(profile)
            elif item["type"] == "prompt_template" and self.run_store:
                template = next((row for row in self.run_store.list_prompt_templates() if row.get("id") == item.get("id")), None)
                if template:
                    backup["prompt_templates"].append(template)
        return backup

    def apply(self, data):
        preview = self.preview(data)
        model_id = preview["model"]
        replacement = preview["replacement_model"]
        if not replacement:
            raise ValueError("replacement_model is required")
        migration = {
            "id": self.migration_id(model_id, replacement),
            "created_at": self.clock(),
            "model": model_id,
            "replacement_model": replacement,
            "status": "applied",
            "affected": preview["affected"],
            "backup": self.backup_artifacts(preview["affected"]),
        }
        self.apply_registry(model_id, replacement)
        self.apply_artifact_replacements(preview["affected"], model_id, replacement)
        state = self.load_state()
        state["migrations"].append(migration)
        self.save_state(state)
        self.append_audit("model_deprecation.apply", actor=data.get("actor") if isinstance(data.get("actor"), dict) else {}, outcome="completed", permission="model_deprecation.migrate", request={"model": model_id, "replacement_model": replacement, "affected": preview["affected_summary"]}, status=200)
        return {**preview, "migration": self.migration_summary(migration), "proxy_sync": self.proxy_sync_payload(force=True)}

    def apply_registry(self, model_id, replacement):
        models = []
        now = self.clock()
        for model in self.models():
            row = dict(model)
            if row.get("id") == model_id:
                row["enabled"] = False
                row["replacement_model"] = replacement
                row["deprecation"] = {
                    "status": "deprecated",
                    "replacement_model": replacement,
                    "migrated_at": now,
                    "reason": "Model deprecation migration applied.",
                }
            models.append(row)
        self.save_model_registry(models)
        self.refresh_model_globals()

    def apply_artifact_replacements(self, affected, old_model, new_model):
        path = self.gateway_policy_file()
        if path.exists() and any(item["type"] == "gateway_policy" for item in affected):
            try:
                policy = json.loads(path.read_text(encoding="utf-8"))
                path.write_text(json.dumps(self.replace_model(policy, old_model, new_model), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            except (OSError, ValueError):
                pass
        for item in affected:
            if item["type"] == "saved_chat":
                doc = self.load_chat(item.get("id"))
                if doc:
                    self.save_chat(self.replace_model(doc, old_model, new_model))
            elif item["type"] == "eval_dataset":
                try:
                    self.save_eval_dataset(self.replace_model(self.load_eval_dataset(item.get("id")), old_model, new_model))
                except (ValueError, OSError, TypeError):
                    pass
            elif item["type"] == "comparison_report":
                report = self.load_comparison_report(item.get("id"))
                if report:
                    self.save_comparison_report(self.replace_model(report, old_model, new_model))
            elif item["type"] == "run_profile" and self.run_store:
                profile = next((row for row in self.run_store.list_run_profiles() if row.get("id") == item.get("id")), None)
                if profile:
                    self.run_store.save_run_profile(self.replace_model(profile, old_model, new_model))
            elif item["type"] == "prompt_template" and self.run_store:
                template = next((row for row in self.run_store.list_prompt_templates() if row.get("id") == item.get("id")), None)
                if template:
                    self.run_store.save_prompt_template(self.replace_model(template, old_model, new_model))

    def migration_summary(self, migration):
        return {
            "id": migration.get("id"),
            "created_at": migration.get("created_at"),
            "model": migration.get("model"),
            "replacement_model": migration.get("replacement_model"),
            "status": migration.get("status"),
            "affected_summary": self.summarize_affected(migration.get("affected") or []),
        }

    def rollback(self, data):
        data = data if isinstance(data, dict) else {}
        migration_id = str(data.get("migration_id") or data.get("id") or "").strip()
        if not migration_id:
            raise ValueError("migration_id is required")
        state = self.load_state()
        migration = next((row for row in state.get("migrations", []) if row.get("id") == migration_id), None)
        if not migration:
            raise ValueError("migration not found")
        backup = migration.get("backup") if isinstance(migration.get("backup"), dict) else {}
        self.save_model_registry(backup.get("models") or [])
        path = self.gateway_policy_file()
        if backup.get("gateway_policy") is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(backup.get("gateway_policy"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for doc in backup.get("saved_chats") or []:
            self.save_chat(doc)
        for dataset in backup.get("eval_datasets") or []:
            self.save_eval_dataset(dataset)
        for report in backup.get("comparison_reports") or []:
            self.save_comparison_report(report)
        if self.run_store:
            for template in backup.get("prompt_templates") or []:
                self.run_store.save_prompt_template(template)
            for profile in backup.get("run_profiles") or []:
                self.run_store.save_run_profile(profile)
        migration["status"] = "rolled_back"
        migration["rolled_back_at"] = self.clock()
        self.save_state(state)
        self.refresh_model_globals()
        self.append_audit("model_deprecation.rollback", actor=data.get("actor") if isinstance(data.get("actor"), dict) else {}, outcome="completed", permission="model_deprecation.rollback", request={"migration_id": migration_id}, status=200)
        return {"rolled_back": self.migration_summary(migration), "proxy_sync": self.proxy_sync_payload(force=True)}
