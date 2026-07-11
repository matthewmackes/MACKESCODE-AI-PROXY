"""Adapters for legacy console operational state used by the v2 React shell."""
from __future__ import annotations

import importlib.util
import time
from http import HTTPStatus
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


PROJECT_DIR = Path(__file__).resolve().parents[3]
LEGACY_CONSOLE = PROJECT_DIR / "image-studio.py"
TMUX_ALLOWED_KEYS = [
    "Enter",
    "Escape",
    "Up",
    "Down",
    "Left",
    "Right",
    "Tab",
    "BTab",
    "C-c",
    "C-d",
    "C-u",
    "C-l",
    "PageUp",
    "PageDown",
    "Home",
    "End",
]


class LegacyConsoleAdapter:
    """Load the existing console module lazily and expose stable v2 payloads."""

    def __init__(self, module_loader: Callable[[], ModuleType] | None = None, clock: Callable[[], float] | None = None) -> None:
        self.module_loader = module_loader or self._load_module
        self.clock = clock or time.time
        self._module: ModuleType | None = None

    def _load_module(self) -> ModuleType:
        spec = importlib.util.spec_from_file_location("matts_legacy_console_v2", LEGACY_CONSOLE)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load legacy console module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def module(self) -> ModuleType:
        if self._module is None:
            self._module = self.module_loader()
        return self._module

    def tmux_sessions(self) -> tuple[list[dict[str, Any]], str]:
        try:
            rows = self.module().tmux_session_items()
            return rows if isinstance(rows, list) else [], ""
        except Exception as exc:
            return [], str(exc)

    def _split_tmux_sessions(self, sessions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        current: list[dict[str, Any]] = []
        previous: list[dict[str, Any]] = []
        for row in sessions:
            item = dict(row)
            if item.get("live"):
                current.append(item)
                continue
            item["live"] = False
            item["attached"] = False
            item["read_only"] = True
            item.setdefault("process_status", "stopped")
            item.setdefault("status", "previous")
            previous.append(item)
        return current, previous

    def agentboard(self) -> tuple[dict[str, Any], str]:
        try:
            payload = self.module().agentboard_payload()
            return payload if isinstance(payload, dict) else {}, ""
        except Exception as exc:
            return {}, str(exc)

    def overview(self) -> dict[str, Any]:
        sessions, session_error = self.tmux_sessions()
        agentboard, agentboard_error = self.agentboard()
        errors = {}
        if session_error:
            errors["sessions"] = session_error
        if agentboard_error:
            errors["agentboard"] = agentboard_error
        counts = agentboard.get("counts") if isinstance(agentboard.get("counts"), dict) else {}
        evals = agentboard.get("evals") if isinstance(agentboard.get("evals"), dict) else {}
        return {
            "generated_at": self.clock(),
            "sessions": sessions,
            "agentboard": agentboard,
            "counts": counts,
            "tasks": agentboard.get("tasks") if isinstance(agentboard.get("tasks"), list) else [],
            "leaderboard": agentboard.get("leaderboard") if isinstance(agentboard.get("leaderboard"), list) else [],
            "usage": agentboard.get("usage") if isinstance(agentboard.get("usage"), dict) else {},
            "evals": evals,
            "summary": {
                "sessions_total": len(sessions),
                "sessions_live": len([row for row in sessions if row.get("live")]),
                "agent_sessions": len(agentboard.get("sessions") or []) if isinstance(agentboard.get("sessions"), list) else 0,
                "requests_ok": int(evals.get("requests_ok") or 0),
                "requests_error": int(evals.get("requests_error") or 0),
                "spend_usd": float(evals.get("spend_usd") or 0),
            },
            "errors": errors,
        }

    def _safe_call(self, name: str, fallback: Any, *args: Any, **kwargs: Any) -> Any:
        module = self.module()
        try:
            func = getattr(module, name)
        except AttributeError:
            return fallback
        try:
            result = func(*args, **kwargs)
            return self.json_safe(result if result is not None else fallback)
        except Exception as exc:
            return {"error": str(exc)} if isinstance(fallback, dict) else fallback

    def operate_payload(self) -> dict[str, Any]:
        reviews = self._safe_call("review_queue_payload", {"reviews": [], "summary": {}}, "", "", "")
        release_candidate = self._safe_call("release_candidate_payload", {"checks": [], "summary": {}})
        rollback = self._safe_call("rollback_targets_payload", {"targets": [], "summary": {}})
        config_drift = self._safe_call("config_drift_payload", {"items": [], "summary": {}})
        automation = self._safe_call("automation_payload", {"rules": [], "executions": [], "summary": {}})
        quotas = self._safe_call("quota_planner_payload", {"budgets": [], "summary": {}})
        synthetic_load = self._safe_call("synthetic_load_payload", {"runs": [], "summary": {}})
        ci_triage = self._safe_call("ci_triage_payload", {"checks": [], "summary": {}})
        offline_mode = self._safe_call("offline_mode_payload", {"enabled": False, "summary": {}})
        model_deprecations = self._safe_call("model_deprecation_payload", {"items": [], "summary": {}})
        eval_gates = self._safe_call("eval_gate_payload", {"recommended_datasets": [], "evidence": [], "decision": "unknown"}, {"surface": "gateway_policy"})

        def rows(payload: Any, *keys: str) -> list[Any]:
            payload = payload if isinstance(payload, dict) else {}
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            return []

        return {
            "generated_at": self.clock(),
            "eval_gates": eval_gates,
            "reviews": reviews,
            "release_candidate": release_candidate,
            "rollback": rollback,
            "config_drift": config_drift,
            "automation": automation,
            "quotas": quotas,
            "synthetic_load": synthetic_load,
            "ci_triage": ci_triage,
            "offline_mode": offline_mode,
            "model_deprecations": model_deprecations,
            "summary": {
                "open_reviews": len(rows(reviews, "reviews", "items")),
                "release_checks": len(rows(release_candidate, "checks")),
                "rollback_targets": len(rows(rollback, "targets", "archives")),
                "config_drift_items": len(rows(config_drift, "drift", "drifts")),
                "automation_rules": len(rows(automation, "rules")) or len(rows(automation.get("config") if isinstance(automation, dict) else {}, "rules")),
                "ci_findings": len(rows(ci_triage, "findings", "checks")),
                "model_deprecations": len(rows(model_deprecations, "items", "models", "deprecations")),
            },
        }

    def preview_ci_triage(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("preview_ci_triage", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def preview_repository_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("preview_repository_context", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def import_repository_context(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("import_repository_context", {}, payload or {})
        data = result if isinstance(result, dict) else {"result": result}
        actor = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
        self._safe_call(
            "append_audit",
            None,
            "repository_context.import",
            actor=actor,
            outcome="completed",
            permission="repository_context_import",
            request={
                "reference": payload.get("reference") or payload.get("url") or payload.get("target"),
                "degraded": ((data.get("preview") or {}).get("degraded") if isinstance(data.get("preview"), dict) else None),
            },
            status=200,
        )
        return data

    def launch_ci_triage(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload or {}
        result = self._safe_call("launch_ci_triage", {}, payload)
        data = result if isinstance(result, dict) else {"result": result}
        actor = payload.get("actor") if isinstance(payload.get("actor"), dict) else {}
        self._safe_call(
            "append_audit",
            None,
            "ci_triage.launch",
            actor=actor,
            outcome="completed",
            permission="repository_context_import",
            request={
                "reference": payload.get("reference") or payload.get("url") or payload.get("target"),
                "failure_count": data.get("failure_count"),
                "degraded": data.get("degraded"),
            },
            status=200,
        )
        return data

    def write_release_candidate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("write_release_candidate_report", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def mark_config_drift_baseline(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "mark_config_drift_baseline"):
            raise ValueError("legacy config drift baseline action unavailable")
        result = module.mark_config_drift_baseline(payload or {})
        return self.json_safe(result if isinstance(result, dict) else {"result": result})

    def acknowledge_config_drift(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "acknowledge_config_drift"):
            raise ValueError("legacy config drift acknowledgement action unavailable")
        result = module.acknowledge_config_drift(payload or {})
        return self.json_safe(result if isinstance(result, dict) else {"result": result})

    def preview_rollback(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("rollback_preview_payload", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def apply_rollback(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("rollback_apply_payload", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def update_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("update_review_item", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def promote_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("promote_review_item", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def save_eval_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("save_eval_dataset", {}, payload or {})
        return {"dataset": result}

    def build_eval_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("build_eval_dataset", {}, payload or {})
        return {"dataset": result}

    def run_eval(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("run_eval", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def save_automation_rules(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("save_automation_rules", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def test_automation_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("test_automation_event", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def run_automation_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("run_automation_event", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def run_due_automation_schedules(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("run_due_automation_schedules", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def preview_model_deprecation(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("preview_model_deprecation", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def apply_model_deprecation(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("apply_model_deprecation", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def rollback_model_deprecation(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._safe_call("rollback_model_deprecation", {}, payload or {})
        return result if isinstance(result, dict) else {"result": result}

    def code_session_defaults(self) -> dict[str, Any]:
        module = self.module()
        text_models = list(getattr(module, "TEXT_MODELS", []) or [])
        default_model = module.default_text_model() if hasattr(module, "default_text_model") else (text_models[0] if text_models else "")
        script_dir = module.script_dir() if hasattr(module, "script_dir") else PROJECT_DIR
        return {
            "default_name": "matts-claude",
            "default_project_dir": str(script_dir),
            "default_model": default_model,
            "text_models": text_models,
            "profiles": [
                {"key": "builder", "label": "Builder", "permission_mode": "acceptEdits", "run_mode": "interactive"},
                {"key": "careful", "label": "Careful", "permission_mode": "plan", "run_mode": "interactive"},
                {"key": "fullauto", "label": "Full Auto", "permission_mode": "bypassPermissions", "run_mode": "interactive"},
                {"key": "review", "label": "Review Only", "permission_mode": "manual", "run_mode": "interactive"},
                {"key": "background", "label": "Background Agent", "permission_mode": "acceptEdits", "run_mode": "background"},
            ],
        }

    def _service_result(self, status: Any, payload: Any) -> tuple[int, dict[str, Any]]:
        code = int(status.value if isinstance(status, HTTPStatus) else status)
        data = payload if isinstance(payload, dict) else {"result": payload}
        return code, data

    def tmux_workspace(self) -> dict[str, Any]:
        sessions, session_error = self.tmux_sessions()
        live_sessions, previous_sessions = self._split_tmux_sessions(sessions)
        read_only_sessions = [row for row in live_sessions if row.get("read_only")]
        attached_sessions = [row for row in live_sessions if row.get("attached")]
        errors = {"sessions": session_error} if session_error else {}
        return {
            "generated_at": self.clock(),
            "sessions": live_sessions,
            "previous_sessions": previous_sessions,
            "allowed_keys": list(TMUX_ALLOWED_KEYS),
            "terminal": {
                "path": "/#code",
                "query_param": "session",
                "websocket_path": "/ws/tmux",
                "default_legacy_port": 18182,
            },
            "summary": {
                "sessions_total": len(live_sessions),
                "sessions_live": len(live_sessions),
                "sessions_read_only": len(read_only_sessions),
                "sessions_previous": len(previous_sessions),
                "sessions_attached": len(attached_sessions),
                "estimated_cost_usd": round(sum(float(row.get("estimated_cost_usd") or 0) for row in live_sessions), 8),
                "estimated_tokens": sum(int(row.get("estimated_tokens") or 0) for row in live_sessions),
            },
            "errors": errors,
        }

    def start_code_session(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return self._service_result(*self.module().tmux_start(payload))

    def preview_code_session_permissions(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if hasattr(module, "permission_simulation"):
            result = module.permission_simulation(payload)
            return result if isinstance(result, dict) else {"result": result}
        return {"risk_level": "unknown", "warnings": [{"code": "permission_simulator_missing", "severity": "medium", "message": "Legacy permission simulator is unavailable."}], "override_allowed": False}

    def command_palette(self, query: str = "", actor: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        module = self.module()
        command_payload = getattr(module, "command_palette_payload", None) or getattr(module, "commands_payload", None)
        if command_payload is not None:
            payload = command_payload(query=query, actor=actor or {}, context=context or {})
            return payload if isinstance(payload, dict) else {"commands": [], "summary": {"commands": 0}}
        return {"commands": [], "summary": {"commands": 0, "available": 0}, "error": "legacy command palette unavailable"}

    def dispatch_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "dispatch_command"):
            raise ValueError("legacy command palette unavailable")
        result = module.dispatch_command(payload)
        return result if isinstance(result, dict) else {"result": result}

    def json_safe(self, value: Any, seen: set[int] | None = None) -> Any:
        seen = seen or set()
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        value_id = id(value)
        if value_id in seen:
            return "[circular]"
        seen.add(value_id)
        try:
            if isinstance(value, dict):
                return {str(key): self.json_safe(child, seen) for key, child in value.items()}
            if isinstance(value, (list, tuple, set)):
                return [self.json_safe(child, seen) for child in value]
            return str(value)
        finally:
            seen.discard(value_id)

    def replay_records(self, limit: int = 50) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "replay_records_payload"):
            return {"replays": [], "error": "legacy replay records unavailable"}
        payload = module.replay_records_payload(limit=limit)
        return payload if isinstance(payload, dict) else {"replays": []}

    def replay_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "replay_snapshot_payload"):
            raise ValueError("legacy replay snapshot unavailable")
        result = module.replay_snapshot_payload(payload)
        return result if isinstance(result, dict) else {"snapshot": result}

    def run_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "replay_payload"):
            raise ValueError("legacy replay unavailable")
        result = module.replay_payload(payload)
        return result if isinstance(result, dict) else {"replay": result}

    def workspace_bundles(self) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "workspace_bundle_payload"):
            return {"bundles": [], "error": "legacy workspace bundle service unavailable"}
        payload = module.workspace_bundle_payload()
        return payload if isinstance(payload, dict) else {"bundles": []}

    def export_workspace_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "export_workspace_bundle"):
            raise ValueError("legacy workspace bundle export unavailable")
        result = module.export_workspace_bundle(payload)
        return result if isinstance(result, dict) else {"result": result}

    def preview_workspace_bundle_import(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "preview_workspace_bundle_import"):
            raise ValueError("legacy workspace bundle import preview unavailable")
        result = module.preview_workspace_bundle_import(payload)
        return result if isinstance(result, dict) else {"result": result}

    def import_workspace_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "import_workspace_bundle"):
            raise ValueError("legacy workspace bundle import unavailable")
        result = module.import_workspace_bundle(payload)
        return result if isinstance(result, dict) else {"result": result}

    def context_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "context_window_payload"):
            raise ValueError("legacy context window inspector unavailable")
        result = module.context_window_payload(payload)
        return result if isinstance(result, dict) else {"result": result}

    def chat_completion(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        module = self.module()
        if not hasattr(module, "chat_completion"):
            raise ValueError("legacy chat route unavailable")
        return self._service_result(*module.chat_completion(payload))

    def observe_payload(self, days: int = 7, trace_limit: int = 50, audit_limit: int = 50) -> dict[str, Any]:
        module = self.module()

        def call(name: str, fallback: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                func = getattr(module, name)
            except AttributeError:
                return fallback
            try:
                result = func(*args, **kwargs)
                return self.json_safe(result if result is not None else fallback)
            except Exception as exc:
                return {"error": str(exc)} if isinstance(fallback, dict) else fallback

        return {
            "console": call("console_status", {}),
            "cost": call("cost_summary_payload", {}),
            "analytics": call("analytics_payload", {}, days=days),
            "provider_health": call("provider_health_payload", {}),
            "traces": call("read_traces", [], limit=trace_limit),
            "audit": call("audit_explorer_payload", {"records": [], "summary": {}}, {"limit": audit_limit}),
            "evals": self.eval_payload(),
            "telemetry": self.telemetry_payload(),
            "reporting_export": call("reporting_export_status", {}),
            "reporting_integrations": call("reporting_integration_payload", {}),
        }

    def eval_payload(self) -> dict[str, Any]:
        module = self.module()
        try:
            datasets = module.list_eval_datasets() if hasattr(module, "list_eval_datasets") else []
            runs = module.list_eval_runs() if hasattr(module, "list_eval_runs") else []
        except Exception as exc:
            return {"datasets": [], "runs": [], "summary": {"datasets": 0, "runs": 0}, "error": str(exc)}
        datasets = self.json_safe(datasets)
        runs = self.json_safe(runs)
        dataset_rows = datasets if isinstance(datasets, list) else []
        run_rows = runs if isinstance(runs, list) else []
        summary = {
            "datasets": len(dataset_rows),
            "runs": len(run_rows),
            "examples": sum(int(row.get("example_count") or 0) for row in dataset_rows if isinstance(row, dict)),
            "requests": 0,
            "failures": 0,
            "total_cost_usd": 0.0,
        }
        for run in run_rows:
            if not isinstance(run, dict):
                continue
            for item in run.get("summary") or []:
                if not isinstance(item, dict):
                    continue
                summary["requests"] += int(item.get("requests") or 0)
                summary["failures"] += int(item.get("failures") or 0)
                summary["total_cost_usd"] += float(item.get("total_cost_usd") or 0.0)
        summary["total_cost_usd"] = round(float(summary["total_cost_usd"]), 8)
        return {"datasets": dataset_rows, "runs": run_rows, "summary": summary}

    def telemetry_payload(self) -> dict[str, Any]:
        module = self.module()
        try:
            integrations = module.reporting_integration_payload() if hasattr(module, "reporting_integration_payload") else {}
        except Exception as exc:
            integrations = {"error": str(exc)}
        try:
            metrics_text = module.console_metrics_text() if hasattr(module, "console_metrics_text") else ""
        except Exception:
            metrics_text = ""
        integrations = self.json_safe(integrations)
        integrations = integrations if isinstance(integrations, dict) else {}
        metric_families: set[str] = set()
        label_keys: set[str] = set()
        for line in str(metrics_text or "").splitlines():
            if not line or line.startswith("#"):
                continue
            name = line.split("{", 1)[0].split(" ", 1)[0].strip()
            if name:
                metric_families.add(name)
            if "{" not in line or "}" not in line:
                continue
            labels = line.split("{", 1)[1].split("}", 1)[0]
            for label in labels.split(","):
                key = label.split("=", 1)[0].strip()
                if key:
                    label_keys.add(key)
        sensitive_excluded = ["authorization", "token", "api_key", "secret", "password", "prompt", "response", "messages", "raw", "text"]
        high_cardinality_excluded = ["trace_id", "session_id", "chat_id", "request_id", "user_id", "email", "path_with_query"]
        observed_sensitive_labels = sorted(key for key in label_keys if key.lower() in sensitive_excluded or key.lower() in high_cardinality_excluded)
        return {
            "metrics": integrations.get("metrics") if isinstance(integrations.get("metrics"), dict) else {},
            "exporter": integrations.get("exporter") if isinstance(integrations.get("exporter"), dict) else {"enabled": False, "kind": "opentelemetry", "last_error": ""},
            "privacy": integrations.get("privacy") if isinstance(integrations.get("privacy"), dict) else {"bounded_labels": True, "excluded": sensitive_excluded},
            "metric_families": sorted(metric_families),
            "label_keys": sorted(label_keys),
            "policy": {
                "bounded_labels": True,
                "sensitive_fields_excluded": sensitive_excluded,
                "high_cardinality_fields_excluded": high_cardinality_excluded,
                "observed_sensitive_label_keys": observed_sensitive_labels,
                "status": "pass" if not observed_sensitive_labels else "review",
            },
        }

    def export_reporting(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "export_reporting_database"):
            raise ValueError("legacy reporting export unavailable")
        result = module.export_reporting_database(payload or {})
        result = self.json_safe(result)
        return result if isinstance(result, dict) else {"result": result}

    def observe_traces(self, limit: int = 100, model: str = "", status: str = "", session: str = "") -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "read_traces"):
            return {"traces": []}
        return {"traces": self.json_safe(module.read_traces(limit=limit, model=model or None, status=status or None, session=session or None))}

    def observe_audit(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "audit_explorer_payload"):
            return {"records": [], "summary": {}}
        result = module.audit_explorer_payload(payload or {})
        result = self.json_safe(result)
        return result if isinstance(result, dict) else {"records": []}

    def explain_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        module = self.module()
        if not hasattr(module, "explain_decision_payload"):
            raise ValueError("legacy decision explanation unavailable")
        result = module.explain_decision_payload(payload)
        result = self.json_safe(result)
        return result if isinstance(result, dict) else {"result": result}

    def capture_code_session(self, name: str) -> tuple[int, dict[str, Any]]:
        return self._service_result(*self.module().tmux_capture(name))

    def send_code_session(self, name: str, text: str, enter: bool = True) -> tuple[int, dict[str, Any]]:
        return self._service_result(*self.module().tmux_send_text(name, text, enter=enter))

    def stop_code_session(self, name: str) -> tuple[int, dict[str, Any]]:
        return self._service_result(*self.module().tmux_stop(name))

    def start_tmux_session(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return self.start_code_session(payload)

    def capture_tmux_session(self, name: str) -> tuple[int, dict[str, Any]]:
        return self.capture_code_session(name)

    def send_tmux_text(self, name: str, text: str, enter: bool = True) -> tuple[int, dict[str, Any]]:
        return self.send_code_session(name, text, enter=enter)

    def send_tmux_key(self, name: str, key: str) -> tuple[int, dict[str, Any]]:
        module = self.module()
        if not hasattr(module, "tmux_send_key"):
            return HTTPStatus.NOT_IMPLEMENTED, {"error": "legacy tmux key send unavailable"}
        return self._service_result(*module.tmux_send_key(name, key))

    def rename_tmux_session(self, old_name: str, new_name: str, display_name: str | None = None) -> tuple[int, dict[str, Any]]:
        module = self.module()
        if not hasattr(module, "tmux_rename_session"):
            return HTTPStatus.NOT_IMPLEMENTED, {"error": "legacy tmux rename unavailable"}
        return self._service_result(*module.tmux_rename_session(old_name, new_name, display_name))

    def stop_tmux_session(self, name: str) -> tuple[int, dict[str, Any]]:
        return self.stop_code_session(name)
