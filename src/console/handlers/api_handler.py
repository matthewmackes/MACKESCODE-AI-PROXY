"""JSON API route dispatcher for the console HTTP handler."""
from urllib.parse import unquote

from src.console.utils.errors import error_payload, normalize_error_payload


KNOWN_GET_PATHS = {
    "/api/agentboard",
    "/api/analytics",
    "/api/audit",
    "/api/audit/export",
    "/api/auth/sessions",
    "/api/automation",
    "/api/chat/branches",
    "/api/chat/history",
    "/api/chat/load",
    "/api/ci-triage",
    "/api/commands",
    "/api/comparison-reports",
    "/api/comparison-reports/export",
    "/api/comparison-reports/load",
    "/api/config-drift",
    "/api/cost-anomalies",
    "/api/cost-summary",
    "/api/dedicated/events",
    "/api/dedicated/gpu-model-config",
    "/api/dedicated/sizes",
    "/api/dedicated/status",
    "/api/eval-gates",
    "/api/evals",
    "/api/history",
    "/api/model-access-key",
    "/api/model-deprecations",
    "/api/model-info",
    "/api/model-scorecards",
    "/api/models",
    "/api/models/serverless-catalog",
    "/api/notifications",
    "/api/offline-mode",
    "/api/onboarding",
    "/api/plugins",
    "/api/policies",
    "/api/provider-health",
    "/api/proxy/status",
    "/api/quotas",
    "/api/rag",
    "/api/release-candidate",
    "/api/replays",
    "/api/reporting-export",
    "/api/reporting-integrations",
    "/api/repository-context",
    "/api/reviews",
    "/api/rollback",
    "/api/status",
    "/api/synthetic-load",
    "/api/tmux/sessions",
    "/api/traces",
    "/api/wallpaper",
    "/api/workspace-bundles",
}

KNOWN_POST_PATHS = {
    "/api/automation/rules",
    "/api/automation/run",
    "/api/automation/test",
    "/api/budget",
    "/api/chat",
    "/api/chat/compare",
    "/api/chat/delete",
    "/api/chat/fork",
    "/api/chat/save",
    "/api/ci-triage/launch",
    "/api/ci-triage/preview",
    "/api/commands/dispatch",
    "/api/comparison-reports",
    "/api/config-drift/acknowledge",
    "/api/config-drift/baseline",
    "/api/context-window",
    "/api/cost-anomalies/update",
    "/api/cost-forecast",
    "/api/dedicated/build",
    "/api/dedicated/capacity-plan",
    "/api/dedicated/keep-alive",
    "/api/dedicated/policy",
    "/api/dedicated/preflight",
    "/api/dedicated/resume",
    "/api/dedicated/teardown",
    "/api/delete",
    "/api/eval-gates",
    "/api/evals/datasets",
    "/api/evals/datasets/build",
    "/api/evals/run",
    "/api/explain-decision",
    "/api/generate",
    "/api/model-access-audit",
    "/api/model-access-drift/acknowledge",
    "/api/model-deprecations/apply",
    "/api/model-deprecations/preview",
    "/api/model-deprecations/rollback",
    "/api/models",
    "/api/notifications/update",
    "/api/onboarding/complete",
    "/api/patch-review",
    "/api/policies/apply",
    "/api/policies/preview",
    "/api/policies/rollback",
    "/api/proxy/sync",
    "/api/quota-planner",
    "/api/rag/config",
    "/api/rag/index",
    "/api/rag/search",
    "/api/release-candidate/report",
    "/api/replay",
    "/api/replay/snapshot",
    "/api/reporting",
    "/api/reporting-export",
    "/api/repository-context/import",
    "/api/repository-context/preview",
    "/api/reviews",
    "/api/reviews/promote",
    "/api/reviews/update",
    "/api/rollback/apply",
    "/api/rollback/preview",
    "/api/session-snapshots",
    "/api/synthetic-load/preview",
    "/api/synthetic-load/run",
    "/api/terminal/read",
    "/api/terminal/start",
    "/api/terminal/stop",
    "/api/terminal/write",
    "/api/test-models",
    "/api/tmux/capture",
    "/api/tmux/key",
    "/api/tmux/permissions",
    "/api/tmux/rename",
    "/api/tmux/send",
    "/api/tmux/start",
    "/api/tmux/stop",
    "/api/workspace-bundles/export",
    "/api/workspace-bundles/import",
    "/api/workspace-bundles/preview",
}


class ConsoleApiHandler:
    """Dispatch JSON API paths to injected application services."""

    def __init__(self, **deps):
        self.deps = deps

    def call(self, name, *args, **kwargs):
        return self.deps[name](*args, **kwargs)

    def known_paths(self, method):
        return KNOWN_POST_PATHS if str(method or "").upper() == "POST" else KNOWN_GET_PATHS

    def failure_payload(self, payload, status=None, trace_id=None):
        if "failure_taxonomy_payload" not in self.deps:
            return payload
        try:
            return self.call("failure_taxonomy_payload", payload, status=status, trace_id=trace_id)
        except TypeError:
            return self.call("failure_taxonomy_payload", payload, status=status)
        except Exception:
            return payload

    def error(self, status, message, code=None, category=None, details=None):
        payload = error_payload(message, status, code=code, category=category, details=details)
        if int(status) >= 400:
            payload = self.failure_payload(payload, status=status)
        return True, int(status), payload

    def result(self, status, payload, code=None, category=None, default_message="request failed"):
        status = int(status)
        if status >= 400:
            payload = normalize_error_payload(payload, status, code=code, category=category, default_message=default_message)
            payload = self.failure_payload(payload, status=status)
        return True, status, payload

    def trace_action(self, action, status, payload=None, request=None):
        """Attach an operator-action trace without making tracing a hard dependency."""
        if "append_trace" not in self.deps:
            return payload
        status = int(status)
        if not isinstance(payload, dict):
            payload = {"result": payload}
        request = request if isinstance(request, dict) else {}
        actor = request.get("actor") if isinstance(request.get("actor"), dict) else {}
        routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
        cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
        if status >= 400 and not failure:
            payload = self.failure_payload(payload, status=status)
            failure = payload.get("failure") if isinstance(payload.get("failure"), dict) else {}
        record = {
            "action": action,
            "status": "success" if status < 400 else "error",
            "http_status": status,
            "requested_model": request.get("model") or request.get("model_id") or payload.get("model") or routing.get("requested"),
            "routed_model": routing.get("used") or payload.get("model"),
            "provider": request.get("provider") or payload.get("provider") or "local-console",
            "endpoint_mode": routing.get("backend") or action.split(".")[0],
            "routing_reason": routing.get("reason") or "",
            "session_id": request.get("session_id") or request.get("id") or request.get("name") or payload.get("session_id"),
            "actor_id": actor.get("id") or request.get("operator") or request.get("session_id") or "",
            "actor_roles": actor.get("roles") or [],
            "cost": cost,
            "usage": usage,
            "cost_usd": cost.get("total_cost_usd") if isinstance(cost, dict) else None,
            "human_message": payload.get("message") or payload.get("error") or "",
            "error_category": failure.get("category") or payload.get("category") or payload.get("code") or ("http_%s" % status if status >= 400 else ""),
            "failure": failure,
            "imported_context": request.get("imported_context") if isinstance(request.get("imported_context"), dict) else {},
        }
        try:
            trace = self.call("append_trace", record)
        except Exception as exc:
            payload.setdefault("trace_error", str(exc))
            return payload
        if isinstance(trace, dict):
            payload.setdefault("trace_id", trace.get("trace_id"))
            payload.setdefault("trace", {"trace_id": trace.get("trace_id"), "status": trace.get("status")})
            if isinstance(payload.get("failure"), dict):
                payload["failure"].setdefault("trace_id", trace.get("trace_id"))
        return payload

    def forecast_actual(self, request, actual_usd):
        forecast = request.get("forecast") if isinstance(request, dict) else None
        if not isinstance(forecast, dict) or "compare_forecast_actual" not in self.deps:
            return {}
        try:
            return self.call("compare_forecast_actual", forecast, actual_usd)
        except Exception as exc:
            return {"error": str(exc)}

    def with_retrieval(self, data, action):
        data = data if isinstance(data, dict) else {}
        retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
        if not retrieval.get("enabled") or "augment_with_retrieval" not in self.deps:
            return data, {"enabled": False, "matches": []}
        augmented = self.call("augment_with_retrieval", data, action)
        return augmented.get("data") or data, augmented.get("retrieval") or {"enabled": False, "matches": []}

    def get(self, path, query=None):
        query = query or {}
        if path == "/api/history":
            return True, 200, self.call("read_history")
        if path == "/api/chat/history":
            return True, 200, self.call("list_chats")
        if path == "/api/chat/load":
            chat_id = (query.get("id") or [""])[0]
            if not chat_id:
                return self.error(400, "id query parameter is required", code="missing_chat_id")
            doc = self.call("load_chat", chat_id)
            if doc is None:
                return self.error(404, "chat not found", code="chat_not_found", details={"id": chat_id})
            return True, 200, doc
        if path == "/api/chat/branches":
            chat_id = (query.get("id") or [""])[0]
            if not chat_id:
                return self.error(400, "id query parameter is required", code="missing_chat_id")
            return True, 200, self.call("branch_comparison", chat_id)
        if path == "/api/comparison-reports":
            return True, 200, {"reports": self.call("list_comparison_reports")}
        if path == "/api/comparison-reports/load":
            report_id = (query.get("id") or [""])[0]
            if not report_id:
                return self.error(400, "id query parameter is required", code="missing_report_id")
            report = self.call("load_comparison_report", report_id)
            if report is None:
                return self.error(404, "comparison report not found", code="comparison_report_not_found", details={"id": report_id})
            return True, 200, {"report": report}
        if path == "/api/comparison-reports/export":
            report_id = (query.get("id") or [""])[0]
            fmt = (query.get("format") or ["json"])[0]
            if not report_id:
                return self.error(400, "id query parameter is required", code="missing_report_id")
            try:
                return True, 200, self.call("export_comparison_report", report_id, fmt)
            except ValueError as exc:
                return self.error(400, str(exc), code="comparison_report_export_invalid")
        if path == "/api/tmux/sessions":
            items = self.call("tmux_session_items")
            return True, 200, {"sessions": [item["name"] for item in items if item.get("live")], "items": items}
        if path == "/api/agentboard":
            return True, 200, self.call("agentboard_payload")
        if path == "/api/plugins":
            return True, 200, self.call("plugins_payload")
        if path == "/api/analytics":
            try:
                days = int((query.get("days") or ["7"])[0] or 7)
            except (TypeError, ValueError):
                days = 7
            return True, 200, self.call("analytics_payload", days=days)
        if path == "/api/reporting-integrations":
            return True, 200, self.call("reporting_integration_payload")
        if path == "/api/reporting-export":
            return True, 200, self.call("reporting_export_status")
        if path == "/api/model-scorecards":
            try:
                days = int((query.get("days") or ["30"])[0] or 30)
            except (TypeError, ValueError):
                days = 30
            return True, 200, self.call("model_scorecards_payload", days=days)
        if path == "/api/model-deprecations":
            return True, 200, self.call("model_deprecation_payload")
        if path == "/api/provider-health":
            return True, 200, self.call("provider_health_payload")
        if path == "/api/quotas":
            return True, 200, self.call("quota_planner_payload")
        if path == "/api/synthetic-load":
            return True, 200, self.call("synthetic_load_payload")
        if path == "/api/config-drift":
            return True, 200, self.call("config_drift_payload")
        if path == "/api/rollback":
            return True, 200, self.call("rollback_targets_payload")
        if path == "/api/release-candidate":
            return True, 200, self.call("release_candidate_payload")
        if path == "/api/automation":
            return True, 200, self.call("automation_payload")
        if path == "/api/cost-anomalies":
            return True, 200, self.call("cost_anomaly_payload")
        if path == "/api/notifications":
            return True, 200, self.call(
                "notification_payload",
                status=(query.get("status") or [""])[0],
                severity=(query.get("severity") or [""])[0],
                category=(query.get("category") or [""])[0],
            )
        if path == "/api/offline-mode":
            return True, 200, self.call("offline_mode_payload")
        if path == "/api/workspace-bundles":
            return True, 200, self.call("workspace_bundle_payload")
        if path == "/api/rag":
            return True, 200, self.call("rag_payload")
        if path == "/api/eval-gates":
            return True, 200, self.call("eval_gate_payload", {"surface": (query.get("surface") or ["gateway_policy"])[0]})
        if path == "/api/reviews":
            return True, 200, self.call(
                "review_queue_payload",
                status=(query.get("status") or [""])[0],
                severity=(query.get("severity") or [""])[0],
                reason=(query.get("reason") or [""])[0],
            )
        if path == "/api/replays":
            try:
                limit = int((query.get("limit") or ["50"])[0] or 50)
            except (TypeError, ValueError):
                limit = 50
            return True, 200, self.call("replay_records_payload", limit=limit)
        if path == "/api/repository-context":
            return True, 200, self.call("repository_context_payload")
        if path == "/api/ci-triage":
            return True, 200, self.call("ci_triage_payload")
        if path == "/api/onboarding":
            return True, 200, self.call("onboarding_payload")
        if path == "/api/commands":
            context = {key: (query.get(key) or [""])[0] for key in ("session", "model", "trace_id", "view") if (query.get(key) or [""])[0]}
            return True, 200, self.call("command_palette_payload", (query.get("q") or [""])[0], context=context)
        if path == "/api/models":
            return True, 200, self.call("models_payload")
        if path == "/api/auth/sessions":
            return True, 200, self.call("active_auth_sessions")
        if path == "/api/audit":
            filters = {key: (value or [""])[0] for key, value in (query or {}).items()}
            return True, 200, self.call("audit_explorer_payload", filters)
        if path == "/api/audit/export":
            filters = {key: (value or [""])[0] for key, value in (query or {}).items()}
            return True, 200, self.call("audit_explorer_export", filters)
        if path == "/api/policies":
            return True, 200, self.call("policy_payload")
        if path == "/api/model-info":
            model_id = (query.get("model") or [""])[0] or None
            status, payload = self.call("model_info_payload", model_id)
            return True, status, payload
        if path.startswith("/api/models/") and path.endswith("/info"):
            model_id = unquote(path[len("/api/models/"):-len("/info")])
            status, payload = self.call("model_info_payload", model_id)
            return True, status, payload
        if path == "/api/models/serverless-catalog":
            result = self.call("sync_serverless_model_catalog", force=True, validate_access=True)
            payload = self.call("models_payload", refresh_catalog=False)
            payload["serverless_catalog"] = result
            payload["proxy_sync"] = self.call("proxy_sync_payload", force=True)
            status = 200 if result.get("ok") else 502
            payload = self.trace_action("model_catalog.refresh", status, payload, {"provider": "digitalocean-serverless"})
            return True, status, payload
        if path == "/api/model-access-key":
            return True, 200, {"key": self.call("active_model_access_key_info")}
        if path == "/api/proxy/status":
            return True, 200, self.call("proxy_sync_payload", force=False)
        if path == "/api/cost-summary":
            return True, 200, self.call("cost_summary_payload")
        if path == "/api/traces":
            try:
                limit = int((query.get("limit") or ["200"])[0] or 200)
            except (TypeError, ValueError):
                limit = 200
            return True, 200, {
                "traces": self.call(
                    "read_traces",
                    limit=limit,
                    model=(query.get("model") or [""])[0] or None,
                    status=(query.get("status") or [""])[0] or None,
                    session=(query.get("session") or [""])[0] or None,
                    min_cost=(query.get("min_cost") or [""])[0] or None,
                )
            }
        if path == "/api/evals":
            return True, 200, {"datasets": self.call("list_eval_datasets"), "runs": self.call("list_eval_runs")}
        if path == "/api/wallpaper":
            return True, 200, self.call("wallpaper_payload", randomize=(query.get("random") or ["0"])[0] == "1")
        if path == "/api/dedicated/status":
            return True, 200, self.call("dedicated_status_payload", poll=True)
        if path == "/api/dedicated/events":
            return True, 200, {"events": self.call("dedicated_events")}
        if path == "/api/dedicated/sizes":
            status, payload = self.call("dedicated_discovery", "/v2/dedicated-inferences/sizes")
            return self.result(status, payload, default_message="Dedicated Inference size discovery failed")
        if path == "/api/dedicated/gpu-model-config":
            status, payload = self.call("dedicated_discovery", "/v2/dedicated-inferences/gpu-model-config")
            return self.result(status, payload, default_message="Dedicated Inference GPU/model discovery failed")
        if path == "/api/status":
            proxy_sync = self.call("proxy_sync_payload", force=False)
            models_status, models = self.call("proxy_get", "/v1/models")
            costs_status, costs = self.call("proxy_get", "/v1/claude-do/costs")
            budget_status, budget = self.call("proxy_get", "/v1/claude-do/budget")
            return True, 200, {
                "proxy_listening": self.call("port_open", self.call("proxy_host"), self.call("proxy_port")),
                "proxy": "http://%s:%d" % (self.call("proxy_host"), self.call("proxy_port")),
                "proxy_sync": proxy_sync,
                "token_file": str(self.call("token_file")),
                "models": models if models_status < 400 else {"error": models},
                "costs": costs if costs_status < 400 else {"error": costs},
                "budget": budget if budget_status < 400 else {"error": budget},
                "logs": self.call("tail_jsonl", self.call("log_file")),
                "tmux_sessions": self.call("tmux_sessions"),
                "launcher": self.call("launcher_health"),
                "model_registry": self.call("models_payload"),
                "dedicated_inference": self.call("dedicated_status_payload", poll=False),
            }
        return False, 404, {}

    def post(self, path, data):
        if path == "/api/cost-forecast":
            try:
                return True, 200, self.call("cost_forecast_payload", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="cost_forecast_invalid")
        if path == "/api/quota-planner":
            target_path = data.get("path") or ""
            return True, 200, self.call("quota_planner_preview", target_path, data)
        if path == "/api/synthetic-load/preview":
            return True, 200, self.call("preview_synthetic_load", data)
        if path == "/api/synthetic-load/run":
            try:
                return True, 200, self.call("run_synthetic_load", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="synthetic_load_blocked")
        if path == "/api/config-drift/baseline":
            return True, 200, self.call("mark_config_drift_baseline", data)
        if path == "/api/config-drift/acknowledge":
            try:
                return True, 200, self.call("acknowledge_config_drift", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="config_drift_ack_invalid")
        if path == "/api/rollback/preview":
            try:
                return True, 200, self.call("rollback_preview_payload", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="rollback_preview_invalid")
        if path == "/api/rollback/apply":
            try:
                return True, 200, self.call("rollback_apply_payload", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="rollback_apply_invalid")
        if path == "/api/release-candidate/report":
            return True, 200, self.call("write_release_candidate_report", data)
        if path == "/api/automation/rules":
            try:
                return True, 200, self.call("save_automation_rules", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="automation_rules_invalid")
        if path == "/api/automation/test":
            return True, 200, self.call("test_automation_event", data)
        if path == "/api/automation/run":
            return True, 200, self.call("run_automation_event", data)
        if path == "/api/policies/preview":
            return True, 200, self.call("preview_policy", data)
        if path == "/api/policies/apply":
            try:
                return True, 200, self.call("apply_policy", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="policy_apply_invalid")
        if path == "/api/policies/rollback":
            try:
                return True, 200, self.call("rollback_policy", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="policy_rollback_invalid")
        if path == "/api/cost-anomalies/update":
            try:
                return True, 200, self.call("update_cost_anomaly", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="cost_anomaly_update_invalid")
        if path == "/api/notifications/update":
            try:
                return True, 200, self.call("update_notification", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="notification_update_invalid")
        if path == "/api/workspace-bundles/export":
            try:
                return True, 200, self.call("export_workspace_bundle", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="workspace_bundle_export_invalid")
        if path == "/api/workspace-bundles/preview":
            try:
                return True, 200, self.call("preview_workspace_bundle_import", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="workspace_bundle_preview_invalid")
        if path == "/api/workspace-bundles/import":
            try:
                return True, 200, self.call("import_workspace_bundle", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="workspace_bundle_import_invalid")
        if path == "/api/context-window":
            if isinstance(data, dict):
                payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
                if isinstance(payload, dict) and isinstance(payload.get("retrieval"), dict) and payload["retrieval"].get("enabled"):
                    action = str(data.get("action") or "chat")
                    augmented, retrieval = self.with_retrieval(payload, action)
                    data = dict(data)
                    data["payload"] = augmented
                    data["retrieval"] = retrieval
            return True, 200, self.call("context_window_payload", data)
        if path == "/api/eval-gates":
            return True, 200, self.call("eval_gate_payload", data)
        if path == "/api/rag/config":
            return True, 200, {"config": self.call("save_rag_config", data)}
        if path == "/api/rag/index":
            return True, 200, self.call("index_rag", data)
        if path == "/api/rag/search":
            return True, 200, self.call("search_rag", data)
        if path == "/api/reviews":
            try:
                return True, 200, self.call("create_review_item", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="review_invalid")
        if path == "/api/reviews/update":
            try:
                return True, 200, self.call("update_review_item", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="review_update_invalid")
        if path == "/api/reviews/promote":
            try:
                return True, 200, self.call("promote_review_item", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="review_promote_invalid")
        if path == "/api/replay/snapshot":
            try:
                return True, 200, self.call("replay_snapshot_payload", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="replay_snapshot_invalid")
        if path == "/api/replay":
            try:
                return True, 200, self.call("replay_payload", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="replay_invalid")
        if path == "/api/repository-context/preview":
            try:
                return True, 200, self.call("preview_repository_context", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="repository_context_invalid")
        if path == "/api/repository-context/import":
            try:
                return True, 200, self.call("import_repository_context", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="repository_context_invalid")
        if path == "/api/ci-triage/preview":
            try:
                return True, 200, self.call("preview_ci_triage", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="ci_triage_invalid")
        if path == "/api/ci-triage/launch":
            try:
                return True, 200, self.call("launch_ci_triage", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="ci_triage_invalid")
        if path == "/api/session-snapshots":
            try:
                return True, 200, self.call("create_session_snapshot", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="session_snapshot_invalid")
        if path == "/api/patch-review":
            try:
                return True, 200, self.call("patch_review_payload", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="patch_review_invalid")
        if path == "/api/onboarding/complete":
            try:
                return True, 200, self.call("complete_onboarding_item", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="onboarding_invalid")
        if path == "/api/explain-decision":
            try:
                return True, 200, self.call("explain_decision_payload", data)
            except ValueError as exc:
                return self.error(404, str(exc), code="decision_explain_not_found")
        if path == "/api/commands/dispatch":
            try:
                return True, 200, self.call("dispatch_command", data)
            except PermissionError as exc:
                return self.error(403, str(exc), code="command_permission_denied")
            except ValueError as exc:
                code = "command_context_unavailable" if "context" in str(exc) else "command_not_found"
                return self.error(400 if code == "command_context_unavailable" else 404, str(exc), code=code)
        if path == "/api/generate":
            status, payload = self.call("generate_images", data)
            if isinstance(payload, dict):
                actual = sum(float(item.get("cost_usd") or 0.0) for item in (payload.get("images") or []) if isinstance(item, dict))
                forecast_actual = self.forecast_actual(data, actual)
                if forecast_actual:
                    payload["forecast_actual"] = forecast_actual
            payload = self.trace_action("image.generate", status, payload, data)
            return self.result(status, payload, default_message="image generation failed")
        if path == "/api/chat":
            data, retrieval = self.with_retrieval(data, "chat")
            status, payload = self.call("chat_completion", data)
            if isinstance(payload, dict) and retrieval.get("enabled"):
                payload["retrieval"] = retrieval
            return self.result(status, payload, default_message="chat request failed")
        if path == "/api/chat/compare":
            models = data.get("models") if isinstance(data.get("models"), list) else []
            models = [str(model) for model in models if str(model or "").strip()]
            if not models or len(models) > 5:
                return self.error(400, "Select between one and five models for comparison.", code="invalid_comparison_models")
            active = set(self.call("text_models"))
            unavailable = [model for model in models if model not in active]
            if unavailable:
                return self.error(400, "Unavailable comparison models: " + ", ".join(unavailable), code="unavailable_comparison_model", details={"models": unavailable})
            data, retrieval = self.with_retrieval(data, "comparison")
            messages = data.get("messages") if isinstance(data.get("messages"), list) else []
            prompt = str(data.get("prompt") or "").strip()
            if prompt:
                messages = messages + [{"role": "user", "content": prompt}]
            if not messages:
                return self.error(400, "comparison prompt is required", code="missing_comparison_prompt")
            results = []
            total_cost = 0.0
            saved_messages = list(messages)
            for model in models:
                status, payload = self.call("chat_completion", {
                    "model": model,
                    "messages": messages,
                    "max_tokens": data.get("max_tokens"),
                    "temperature": data.get("temperature"),
                })
                cost = payload.get("cost") if isinstance(payload, dict) and isinstance(payload.get("cost"), dict) else {}
                total_cost += float(cost.get("total_cost_usd") or 0.0)
                result = {
                    "model": model,
                    "status": int(status),
                    "ok": int(status) < 400,
                    "text": payload.get("text") if isinstance(payload, dict) else "",
                    "routing": payload.get("routing") if isinstance(payload, dict) else {},
                    "usage": payload.get("usage") if isinstance(payload, dict) else {},
                    "cost": cost,
                    "streaming_metrics": payload.get("streaming_metrics") if isinstance(payload, dict) else {},
                    "trace_id": payload.get("trace_id") if isinstance(payload, dict) else "",
                    "error": (payload.get("message") or payload.get("error") or "") if isinstance(payload, dict) and int(status) >= 400 else "",
                }
                results.append(result)
                saved_messages.append({"role": "assistant", "content": result["text"] or result["error"], "model": (result.get("routing") or {}).get("used") or model, "meta": {"comparison": True, "requested_model": model, "routing": result.get("routing"), "usage": result.get("usage"), "cost": result.get("cost"), "trace": {"trace_id": result.get("trace_id")}}})
            chat = self.call("save_chat", {"model": "comparison", "title": "Comparison: " + str(messages[-1].get("content") or "")[:48], "messages": saved_messages})
            response = {"models": models, "results": results, "total_cost_usd": round(total_cost, 8), "chat": {"id": chat.get("id"), "title": chat.get("title"), "message_count": len(chat.get("messages") or [])}}
            if retrieval.get("enabled"):
                response["retrieval"] = retrieval
            forecast_actual = self.forecast_actual(data, total_cost)
            if forecast_actual:
                response["forecast_actual"] = forecast_actual
            return True, 200, response
        if path == "/api/evals/run":
            try:
                payload = self.call("run_eval", data)
                if isinstance(payload, dict):
                    actual = sum(float(item.get("total_cost_usd") or 0.0) for item in (payload.get("summary") or []) if isinstance(item, dict))
                    forecast_actual = self.forecast_actual(data, actual)
                    if forecast_actual:
                        payload["forecast_actual"] = forecast_actual
                return True, 200, payload
            except ValueError as exc:
                return self.error(400, str(exc), code="eval_run_invalid")
        if path == "/api/evals/datasets":
            try:
                return True, 200, {"dataset": self.call("save_eval_dataset", data)}
            except ValueError as exc:
                return self.error(400, str(exc), code="eval_dataset_invalid")
        if path == "/api/evals/datasets/build":
            try:
                return True, 200, {"dataset": self.call("build_eval_dataset", data)}
            except ValueError as exc:
                return self.error(400, str(exc), code="eval_dataset_builder_invalid")
        if path == "/api/chat/save":
            return True, 200, self.call("save_chat", data)
        if path == "/api/chat/fork":
            try:
                return True, 200, {"branch": self.call("fork_chat", data)}
            except ValueError as exc:
                return self.error(400, str(exc), code="chat_fork_invalid")
        if path == "/api/comparison-reports":
            try:
                return True, 200, {"report": self.call("save_comparison_report", data)}
            except ValueError as exc:
                return self.error(400, str(exc), code="comparison_report_invalid")
        if path == "/api/chat/delete":
            return True, 200, {"deleted": self.call("delete_chat", data.get("id"))}
        if path == "/api/delete":
            return True, 200, {"deleted": self.call("delete_history_item", data.get("id"))}
        if path == "/api/models":
            status, payload = self.call("save_models_payload", data)
            return self.result(status, payload, default_message="model registry update failed")
        if path == "/api/proxy/sync":
            return True, 200, self.call("proxy_sync_payload", force=True)
        if path == "/api/model-access-audit":
            payload = self.call("audit_model_access_key")
            return True, 200, self.trace_action("model_access.audit", 200, payload, data)
        if path == "/api/model-access-drift/acknowledge":
            return True, 200, self.call("acknowledge_model_access_drift", data)
        if path == "/api/model-deprecations/preview":
            try:
                return True, 200, self.call("preview_model_deprecation", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="model_deprecation_invalid")
        if path == "/api/model-deprecations/apply":
            try:
                return True, 200, self.call("apply_model_deprecation", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="model_deprecation_invalid")
        if path == "/api/model-deprecations/rollback":
            try:
                return True, 200, self.call("rollback_model_deprecation", data)
            except ValueError as exc:
                return self.error(400, str(exc), code="model_deprecation_invalid")
        if path == "/api/dedicated/preflight":
            preflight = self.call("dedicated_preflight", data)
            payload = self.call("dedicated_status_payload", poll=False)
            payload["preflight"] = preflight
            payload["dedicated"] = preflight.get("config") or payload.get("dedicated")
            if preflight.get("errors"):
                self.call("append_dedicated_event", "preflight", "Dedicated preflight needs attention", "warning", {"errors": preflight.get("errors"), "warnings": preflight.get("warnings")})
            else:
                self.call("append_dedicated_event", "preflight", "Dedicated preflight passed", "success", {"warnings": preflight.get("warnings")})
            payload["events"] = self.call("dedicated_events")
            return True, 200, payload
        if path == "/api/dedicated/capacity-plan":
            return True, 200, self.call("dedicated_capacity_plan", data)
        if path == "/api/dedicated/build":
            status, payload = self.call("dedicated_build", data)
            if isinstance(payload, dict):
                dedicated = payload.get("dedicated") if isinstance(payload.get("dedicated"), dict) else payload
                hourly = dedicated.get("price_per_hour") if isinstance(dedicated, dict) else None
                forecast_actual = self.forecast_actual(data, hourly)
                if forecast_actual:
                    forecast_actual["actual_basis"] = "accepted_hourly_rate_usd"
                    payload["forecast_actual"] = forecast_actual
            payload = self.trace_action("dedicated.build", status, payload, data)
            return self.result(status, payload, default_message="Dedicated Inference build failed")
        if path == "/api/dedicated/teardown":
            status, payload = self.call("dedicated_teardown", data)
            payload = self.trace_action("dedicated.teardown", status, payload, data)
            return self.result(status, payload, default_message="Dedicated Inference teardown failed")
        if path == "/api/dedicated/resume":
            status, payload = self.call("dedicated_build", data)
            return self.result(status, payload, default_message="Dedicated Inference resume failed")
        if path == "/api/dedicated/policy":
            status, payload = self.call("dedicated_policy", data)
            return self.result(status, payload, default_message="Dedicated Inference policy update failed")
        if path == "/api/dedicated/keep-alive":
            status, payload = self.call("dedicated_keep_alive", data)
            return self.result(status, payload, default_message="Dedicated Inference keep-alive failed")
        if path == "/api/budget":
            return True, 200, {"budgets": self.call("save_budget", data)}
        if path == "/api/reporting":
            return True, 200, self.call("digitalocean_report", data)
        if path == "/api/reporting-export":
            return True, 200, self.call("export_reporting_database", data)
        if path == "/api/test-models":
            results = []
            for model in self.deps["text_models"]():
                status, payload = self.call("chat_completion", {"model": model, "messages": [{"role": "user", "content": "Reply only ok"}], "max_tokens": 8})
                results.append({"model": model, "status": int(status), "ok": int(status) < 400, "response": payload})
            image_model = self.call("default_image_model")
            status, payload = self.call("generate_images", {"model": image_model, "prompt": "small smoke test tile with the word OK", "size": "512x512", "count": 1, "style": "technical"})
            results.append({"model": image_model, "status": int(status), "ok": int(status) < 400, "response": payload})
            return True, 200, {"results": results}
        if path == "/api/tmux/start":
            data, retrieval = self.with_retrieval(data, "code")
            if "permission_simulation" in self.deps:
                data = dict(data)
                data["permission_summary"] = self.call("permission_simulation", data)
            status, payload = self.call("tmux_start", data)
            if isinstance(payload, dict) and retrieval.get("enabled"):
                payload["retrieval"] = retrieval
            payload = self.trace_action("tmux.start", status, payload, data)
            return self.result(status, payload, default_message="tmux session start failed")
        if path == "/api/tmux/permissions":
            return True, 200, {"permission_summary": self.call("permission_simulation", data)}
        if path == "/api/tmux/capture":
            status, payload = self.call("tmux_capture", data.get("name"))
            return self.result(status, payload, default_message="tmux capture failed")
        if path == "/api/tmux/send":
            status, payload = self.call("tmux_send_text", data.get("name"), data.get("text") or "", bool(data.get("enter")))
            return self.result(status, payload, default_message="tmux send failed")
        if path == "/api/tmux/key":
            status, payload = self.call("tmux_send_key", data.get("name"), data.get("key"))
            return self.result(status, payload, default_message="tmux key send failed")
        if path == "/api/tmux/stop":
            status, payload = self.call("tmux_stop", data.get("name"))
            return self.result(status, payload, default_message="tmux stop failed")
        if path == "/api/tmux/rename":
            status, payload = self.call("tmux_rename_session", data.get("old_name"), data.get("new_name"), data.get("display_name"))
            return self.result(status, payload, default_message="tmux rename failed")
        if path == "/api/terminal/start":
            status, payload = self.call("terminal_start", data)
            return self.result(status, payload, default_message="terminal start failed")
        if path == "/api/terminal/read":
            status, payload = self.call("terminal_read", data.get("id"))
            return self.result(status, payload, default_message="terminal read failed")
        if path == "/api/terminal/write":
            status, payload = self.call("terminal_write", data.get("id"), data.get("text") or "")
            return self.result(status, payload, default_message="terminal write failed")
        if path == "/api/terminal/stop":
            status, payload = self.call("terminal_stop", data.get("id"))
            return self.result(status, payload, default_message="terminal stop failed")
        return False, 404, {}
