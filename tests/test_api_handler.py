import unittest

from src.console.handlers.api_handler import ConsoleApiHandler
from src.console.services.failure_taxonomy import FailureTaxonomyService


class ConsoleApiHandlerTests(unittest.TestCase):
    def handler(self):
        calls = []

        def record(name, result):
            def inner(*args, **kwargs):
                calls.append((name, args, kwargs))
                return result
            return inner

        def append_trace(trace_record):
            calls.append(("append_trace", (trace_record,), {}))
            return {"trace_id": "trace-%d" % len([call for call in calls if call[0] == "append_trace"]), "status": trace_record.get("status")}

        deps = {
            "read_history": record("read_history", [{"id": "img"}]),
            "list_chats": record("list_chats", [{"id": "chat"}]),
            "load_chat": lambda chat_id: {"id": chat_id} if chat_id == "ok" else None,
            "branch_comparison": lambda chat_id: {"parent": {"id": chat_id}, "branches": [{"id": "branch-a"}]},
            "list_comparison_reports": lambda: [{"id": "report-a"}],
            "load_comparison_report": lambda report_id: {"id": report_id, "results": []} if report_id == "report-a" else None,
            "export_comparison_report": lambda report_id, fmt: {"id": report_id, "format": fmt, "content": "export"},
            "tmux_session_items": record("tmux_session_items", [{"name": "live", "live": True}, {"name": "old", "live": False}]),
            "agentboard_payload": record("agentboard_payload", {"agents": []}),
            "plugins_payload": record("plugins_payload", {"plugins": [{"id": "plug"}]}),
            "analytics_payload": lambda days=7: {"days": days, "summary": {}},
            "reporting_integration_payload": lambda: {"metrics": {"endpoint": "/metrics"}, "dashboards": [{"name": "overview"}]},
            "reporting_export_status": lambda: {"available": True, "exports": [{"format": "sqlite"}]},
            "export_reporting_database": lambda data: {"format": data.get("format") or "duckdb", "path": "build/reporting/mde-llm-proxy-reporting.sqlite"},
            "model_scorecards_payload": lambda days=30: {"days": days, "scorecards": [{"model": "model-a"}]},
            "model_deprecation_payload": lambda: {"deprecated_models": [{"model": "old-model"}], "summary": {"count": 1}},
            "provider_health_payload": lambda: {"providers": [{"id": "digitalocean"}], "findings": []},
            "quota_planner_payload": lambda: {"enabled": True, "quotas": []},
            "quota_planner_preview": lambda path, data: {"allowed": True, "path": path, "action": data.get("action")},
            "synthetic_load_payload": lambda: {"runs": [{"id": "load-a"}], "limits": {"max_requests": 50}},
            "preview_synthetic_load": lambda data: {"dry_run": True, "request": {"request_count": data.get("request_count")}},
            "run_synthetic_load": lambda data: {"id": "load-a", "summary": {"requests": data.get("request_count")}},
            "config_drift_payload": lambda: {"summary": {"state": "clean"}, "drift": []},
            "mark_config_drift_baseline": lambda data: {"summary": {"state": "clean"}, "baseline": {"reason": data.get("reason")}},
            "acknowledge_config_drift": lambda data: {"summary": {"state": "acknowledged"}, "acknowledged": data.get("items")},
            "rollback_targets_payload": lambda: {"targets": [{"id": "runtime:a"}]},
            "rollback_preview_payload": lambda data: {"target": {"id": data.get("target_id")}, "summary": {"will_restore": 1}},
            "rollback_apply_payload": lambda data: {"target": {"id": data.get("target_id")}, "pre_backup": "/tmp/pre.tar.gz", "restored": [{"name": "model_registry"}]},
            "release_candidate_payload": lambda: {"ready": True, "checks": []},
            "write_release_candidate_report": lambda data: {"ready": True, "label": data.get("label"), "report_file": "/tmp/rc.json"},
            "automation_payload": lambda: {"config": {"rules": []}, "executions": []},
            "save_automation_rules": lambda data: {"config": {"rules": data.get("rules") or []}},
            "test_automation_event": lambda data: {"dry_run": True, "event": data.get("event"), "matched_count": 1},
            "run_automation_event": lambda data: {"dry_run": False, "event": data.get("event"), "matched_count": 1},
            "cost_anomaly_payload": lambda data=None: {"anomalies": [{"id": "cost-a"}], "summary": {"count": 1}},
            "update_cost_anomaly": lambda data: {"updated": data.get("id"), "action": data.get("action")},
            "notification_payload": lambda status="", severity="", category="": {"notifications": [{"id": "n1", "status": status or "new", "severity": severity or "high", "category": category or "review"}], "summary": {"new": 1}},
            "update_notification": lambda data: {"notifications": [{"id": data.get("id"), "status": data.get("status")}], "summary": {"new": 0}},
            "offline_mode_payload": lambda: {"mode": "online", "cache": {"serverless_catalog": {"confidence": "fresh"}}},
            "workspace_bundle_payload": lambda: {"bundles": [{"id": "bundle-a", "sections": ["model_registry"]}]},
            "export_workspace_bundle": lambda data: {"bundle_id": "bundle-a", "summary": {"model_registry": 1}, "bundle": {"manifest": {"id": "bundle-a"}, "sections": {}}},
            "preview_workspace_bundle_import": lambda data: {"dry_run": True, "blocking": False, "selected_sections": data.get("sections") or []},
            "import_workspace_bundle": lambda data: {"dry_run": False, "applied": data.get("sections") or []},
            "rag_payload": lambda: {"config": {"collections": []}, "index": []},
            "save_rag_config": lambda data: {"collections": data.get("collections") or []},
            "index_rag": lambda data: {"indexed": [{"id": data.get("collection_id") or "project-docs"}]},
            "search_rag": lambda data: {"query": data.get("query"), "matches": [{"path": "README.md"}]},
            "augment_with_retrieval": lambda data, action: {"data": {**data, "messages": [{"role": "system", "content": "retrieved"}] + data.get("messages", [])}, "retrieval": {"enabled": True, "action": action, "matches": [{"path": "README.md"}]}},
            "models_payload": lambda refresh_catalog=True: {"models": [], "refresh_catalog": refresh_catalog},
            "active_auth_sessions": record("active_auth_sessions", {"sessions": [{"session_id": "session-a"}]}),
            "audit_explorer_payload": lambda data=None: {"records": [{"action": data.get("action") if isinstance(data, dict) else ""}], "summary": {"returned": 1}},
            "audit_explorer_export": lambda data=None: {"format": (data or {}).get("format") or "json", "content": "audit-export"},
            "policy_payload": lambda: {"bundle": {"schema_version": 1}, "history": []},
            "preview_policy": lambda data: {"dry_run": True, "blocking": False, "bundle": data.get("bundle")},
            "apply_policy": lambda data: {"applied": True, "sections": data.get("sections") or []},
            "rollback_policy": lambda data: {"rolled_back": True, "version_id": data.get("version_id") or ""},
            "model_info_payload": lambda model_id=None: (200, {"model_id": model_id, "cards": []}),
            "sync_serverless_model_catalog": lambda **kwargs: {"ok": True, "kwargs": kwargs},
            "proxy_sync_payload": lambda **kwargs: {"in_sync": True, "kwargs": kwargs},
            "active_model_access_key_info": record("active_model_access_key_info", {"configured": True}),
            "cost_summary_payload": record("cost_summary_payload", {"cost": 1}),
            "cost_forecast_payload": lambda data: {"forecast_id": "forecast-a", "estimated_total_usd": 0.02, "request": data},
            "compare_forecast_actual": lambda forecast, actual: {"forecast_id": forecast.get("forecast_id"), "estimated_usd": forecast.get("estimated_total_usd"), "actual_usd": round(float(actual or 0), 8)},
            "context_window_payload": lambda data: {"action": data.get("action"), "models": [{"model": "model-a", "fits": True}]},
            "eval_gate_payload": lambda data: {"surface": data.get("surface"), "recommended_datasets": [{"id": "smoke"}]},
            "review_queue_payload": lambda status="", severity="", reason="": {"reviews": [{"id": "review-a", "status": status or "open", "severity": severity or "high", "reason": reason or "manual"}]},
            "create_review_item": lambda data: {"review": {"id": "review-new", **data}},
            "update_review_item": lambda data: {"review": {"id": data.get("id"), "status": data.get("status")}},
            "promote_review_item": lambda data: {"promotion": {"type": data.get("target") or "eval"}},
            "replay_snapshot_payload": lambda data: {"snapshot": {"source": data.get("source"), "available": True}},
            "replay_payload": lambda data: {"id": "replay-a", "source": data.get("source"), "results": []},
            "replay_records_payload": lambda limit=50: {"replays": [{"id": "replay-a", "limit": limit}]},
            "repository_context_payload": lambda: {"connectors": [{"id": "github", "configured": True}]},
            "preview_repository_context": lambda data: {"prompt": "Repository context", "reference": data.get("reference")},
            "import_repository_context": lambda data: {"launch_patch": {"print_prompt_append": "Repository context", "imported_context": {"repo": "app", "number": 42}}},
            "ci_triage_payload": lambda: {"supported": ["github_checks"]},
            "preview_ci_triage": lambda data: {"failure_count": 1, "reference": data.get("reference")},
            "launch_ci_triage": lambda data: {"launch_patch": {"print_prompt_append": "CI fix", "imported_context": {"repo": "app", "ci_failures": [{"name": "unit"}]}}},
            "patch_review_payload": lambda data: {"summary": {"changed_files": 1}, "session": data.get("session")},
            "onboarding_payload": lambda: {"summary": {"incomplete": 1}, "checks": [{"id": "model_access_token"}]},
            "complete_onboarding_item": lambda data: {"summary": {"incomplete": 0}, "completed": data.get("id")},
            "explain_decision_payload": lambda data: {"type": data.get("type") or "generic", "selected_action": "allow"},
            "command_palette_payload": lambda query="", context=None: {"commands": [{"id": "traces.open", "query": query, "context": context or {}}], "summary": {"commands": 1}},
            "dispatch_command": lambda data: {"command": {"id": data.get("id")}, "action": {"type": "console_view", "target": "traces"}},
            "create_session_snapshot": lambda data: {"snapshot": {"session": data.get("session")}, "files": {"json": "/tmp/s.json", "markdown": "/tmp/s.md"}},
            "read_traces": lambda **kwargs: [{"trace_id": "trace-a", "kwargs": kwargs}],
            "append_trace": append_trace,
            "wallpaper_payload": lambda randomize=False: {"randomize": randomize},
            "dedicated_status_payload": lambda poll=True: {"poll": poll},
            "dedicated_events": record("dedicated_events", [{"state": "ready"}]),
            "dedicated_discovery": lambda path: (207, {"path": path}),
            "proxy_get": lambda path: (200, {"path": path}),
            "port_open": lambda host, port: True,
            "proxy_host": lambda: "127.0.0.1",
            "proxy_port": lambda: 18081,
            "token_file": lambda: "/tmp/token",
            "tail_jsonl": lambda path: [{"log": str(path)}],
            "log_file": lambda: "/tmp/log",
            "tmux_sessions": record("tmux_sessions", ["one"]),
            "launcher_health": record("launcher_health", {"ok": True}),
            "generate_images": lambda data: (201, {"images": [data]}),
            "chat_completion": lambda data: (202, {"text": data["messages"][0]["content"]}),
            "list_eval_datasets": record("list_eval_datasets", [{"id": "smoke"}]),
            "list_eval_runs": record("list_eval_runs", [{"id": "eval-a"}]),
            "run_eval": lambda data: {"run": data},
            "save_eval_dataset": lambda data: {"saved": data},
            "build_eval_dataset": lambda data: {"built": data},
            "save_chat": lambda data: {"id": "chat-compare", "title": data.get("title"), "messages": data.get("messages") or []},
            "fork_chat": lambda data: {"id": "branch-a", "branch": {"parent_chat_id": data.get("source_chat_id")}},
            "save_comparison_report": lambda data: {"id": "report-a", "title": data.get("title")},
            "delete_chat": lambda chat_id: chat_id == "chat",
            "delete_history_item": lambda image_id: image_id == "img",
            "save_models_payload": lambda data: (203, {"models": data["models"]}),
            "audit_model_access_key": record("audit_model_access_key", {"checked": 2}),
            "acknowledge_model_access_drift": lambda data: {"acknowledged": data.get("ids") or ["all"], "active_count": 0},
            "preview_model_deprecation": lambda data: {"model": data.get("model_id"), "replacement_model": data.get("replacement_model") or "model-a", "affected": []},
            "apply_model_deprecation": lambda data: {"migration": {"id": "migration-a", "model": data.get("model_id"), "replacement_model": data.get("replacement_model")}},
            "rollback_model_deprecation": lambda data: {"rolled_back": {"id": data.get("migration_id"), "status": "rolled_back"}},
            "dedicated_preflight": lambda data: {"errors": [], "warnings": ["warn"], "config": {"id": "cfg"}},
            "dedicated_capacity_plan": lambda data: {"recommendation": "build", "cost": {"daily_usd": 24}, "capacity": {"uncertain": False}, "request": data},
            "append_dedicated_event": lambda *args, **kwargs: calls.append(("append_dedicated_event", args, kwargs)),
            "dedicated_build": lambda data: (204, {"built": data}),
            "dedicated_teardown": lambda data: (205, {"torn_down": data}),
            "dedicated_policy": lambda data: (206, {"policy": data}),
            "dedicated_keep_alive": lambda data: (207, {"keep_alive": data}),
            "save_budget": lambda data: {"daily": data.get("daily")},
            "digitalocean_report": lambda data: {"report": data},
            "text_models": lambda: ["model-a", "model-b"],
            "default_image_model": lambda: "image-a",
            "permission_simulation": lambda data: {"risk_level": "high", "mode": data.get("permission_mode"), "warnings": [{"code": "broad_bash"}]},
            "tmux_start": lambda data: (210, {"started": data}),
            "tmux_capture": lambda name: (211, {"name": name}),
            "tmux_send_text": lambda name, text, enter: (212, {"name": name, "text": text, "enter": enter}),
            "tmux_send_key": lambda name, key: (213, {"name": name, "key": key}),
            "tmux_stop": lambda name: (214, {"name": name}),
            "tmux_rename_session": lambda old, new, display: (215, {"old": old, "new": new, "display": display}),
            "terminal_start": lambda data: (216, {"id": "term"}),
            "terminal_read": lambda session_id: (217, {"id": session_id}),
            "terminal_write": lambda session_id, text: (218, {"id": session_id, "text": text}),
            "terminal_stop": lambda session_id: (219, {"id": session_id}),
        }
        return ConsoleApiHandler(**deps), calls

    def test_get_chat_load_validation_and_tmux_sessions(self):
        handler, _ = self.handler()

        handled, status, payload = handler.get("/api/chat/load", {})
        self.assertTrue(handled)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "id query parameter is required")
        self.assertEqual(payload["code"], "missing_chat_id")
        self.assertEqual(payload["category"], "client")

        handled, status, payload = handler.get("/api/chat/load", {"id": ["missing"]})
        self.assertTrue(handled)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "chat not found")
        self.assertEqual(payload["code"], "chat_not_found")
        self.assertEqual(payload["details"], {"id": "missing"})
        self.assertEqual(handler.get("/api/chat/load", {"id": ["ok"]}), (True, 200, {"id": "ok"}))
        self.assertEqual(handler.get("/api/plugins"), (True, 200, {"plugins": [{"id": "plug"}]}))
        self.assertEqual(handler.get("/api/chat/branches", {"id": ["ok"]}), (True, 200, {"parent": {"id": "ok"}, "branches": [{"id": "branch-a"}]}))
        self.assertEqual(handler.get("/api/comparison-reports"), (True, 200, {"reports": [{"id": "report-a"}]}))
        self.assertEqual(handler.get("/api/comparison-reports/load", {"id": ["report-a"]}), (True, 200, {"report": {"id": "report-a", "results": []}}))
        self.assertEqual(handler.get("/api/comparison-reports/export", {"id": ["report-a"], "format": ["csv"]}), (True, 200, {"id": "report-a", "format": "csv", "content": "export"}))
        self.assertEqual(handler.get("/api/analytics", {"days": ["3"]}), (True, 200, {"days": 3, "summary": {}}))
        self.assertEqual(handler.get("/api/reporting-integrations"), (True, 200, {"metrics": {"endpoint": "/metrics"}, "dashboards": [{"name": "overview"}]}))
        self.assertEqual(handler.get("/api/reporting-export"), (True, 200, {"available": True, "exports": [{"format": "sqlite"}]}))
        self.assertEqual(handler.get("/api/model-scorecards", {"days": ["14"]}), (True, 200, {"days": 14, "scorecards": [{"model": "model-a"}]}))
        self.assertEqual(handler.get("/api/model-deprecations"), (True, 200, {"deprecated_models": [{"model": "old-model"}], "summary": {"count": 1}}))
        self.assertEqual(handler.get("/api/provider-health"), (True, 200, {"providers": [{"id": "digitalocean"}], "findings": []}))
        self.assertEqual(handler.get("/api/quotas"), (True, 200, {"enabled": True, "quotas": []}))
        self.assertEqual(handler.get("/api/synthetic-load"), (True, 200, {"runs": [{"id": "load-a"}], "limits": {"max_requests": 50}}))
        self.assertEqual(handler.get("/api/config-drift"), (True, 200, {"summary": {"state": "clean"}, "drift": []}))
        self.assertEqual(handler.get("/api/rollback"), (True, 200, {"targets": [{"id": "runtime:a"}]}))
        self.assertEqual(handler.get("/api/release-candidate"), (True, 200, {"ready": True, "checks": []}))
        self.assertEqual(handler.get("/api/automation"), (True, 200, {"config": {"rules": []}, "executions": []}))
        self.assertEqual(handler.get("/api/cost-anomalies"), (True, 200, {"anomalies": [{"id": "cost-a"}], "summary": {"count": 1}}))
        self.assertEqual(handler.get("/api/notifications", {"status": ["new"], "severity": ["high"], "category": ["review"]}), (True, 200, {"notifications": [{"id": "n1", "status": "new", "severity": "high", "category": "review"}], "summary": {"new": 1}}))
        self.assertEqual(handler.get("/api/offline-mode"), (True, 200, {"mode": "online", "cache": {"serverless_catalog": {"confidence": "fresh"}}}))
        self.assertEqual(handler.get("/api/workspace-bundles"), (True, 200, {"bundles": [{"id": "bundle-a", "sections": ["model_registry"]}]}))
        self.assertEqual(handler.get("/api/rag"), (True, 200, {"config": {"collections": []}, "index": []}))
        self.assertEqual(handler.get("/api/eval-gates", {"surface": ["model_registry"]}), (True, 200, {"surface": "model_registry", "recommended_datasets": [{"id": "smoke"}]}))
        self.assertEqual(handler.get("/api/reviews", {"status": ["open"], "severity": ["high"]}), (True, 200, {"reviews": [{"id": "review-a", "status": "open", "severity": "high", "reason": "manual"}]}))
        self.assertEqual(handler.get("/api/replays", {"limit": ["3"]}), (True, 200, {"replays": [{"id": "replay-a", "limit": 3}]}))
        self.assertEqual(handler.get("/api/repository-context"), (True, 200, {"connectors": [{"id": "github", "configured": True}]}))
        self.assertEqual(handler.get("/api/ci-triage"), (True, 200, {"supported": ["github_checks"]}))
        self.assertEqual(handler.get("/api/onboarding"), (True, 200, {"summary": {"incomplete": 1}, "checks": [{"id": "model_access_token"}]}))
        self.assertEqual(handler.get("/api/commands", {"q": ["trace"], "trace_id": ["trace-a"]}), (True, 200, {"commands": [{"id": "traces.open", "query": "trace", "context": {"trace_id": "trace-a"}}], "summary": {"commands": 1}}))

    def test_error_responses_include_failure_hints_when_taxonomy_is_configured(self):
        handler, calls = self.handler()
        taxonomy = FailureTaxonomyService()
        handler.deps["failure_taxonomy_payload"] = lambda payload, status=None, trace_id=None: taxonomy.decorate(payload, status=status, trace_id=trace_id)

        handled, status, payload = handler.error(429, "Too many requests", code="rate_limited")
        self.assertTrue(handled)
        self.assertEqual(status, 429)
        self.assertEqual(payload["failure"]["category"], "rate_limit")
        self.assertIn("suggested_fix", payload["failure"])
        self.assertTrue(payload["diagnostics"]["redacted"])

        traced = handler.trace_action("quota.test", 429, {"message": "budget blocked", "details": {"token": "secret"}}, {})
        self.assertEqual(traced["failure"]["category"], "budget")
        self.assertEqual(traced["failure"]["trace_id"], "trace-1")
        self.assertEqual(calls[-1][1][0]["error_category"], "budget")

    def test_get_model_info_routes(self):
        handler, _ = self.handler()

        self.assertEqual(handler.get("/api/model-info", {}), (True, 200, {"model_id": None, "cards": []}))
        self.assertEqual(handler.get("/api/model-info", {"model": ["qwen3"]}), (True, 200, {"model_id": "qwen3", "cards": []}))
        self.assertEqual(handler.get("/api/models/qwen3/info", {}), (True, 200, {"model_id": "qwen3", "cards": []}))
        handled, status, payload = handler.get("/api/tmux/sessions")

        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["sessions"], ["live"])
        self.assertEqual(handler.get("/api/auth/sessions"), (True, 200, {"sessions": [{"session_id": "session-a"}]}))
        self.assertEqual(handler.get("/api/audit", {"action": ["review"]}), (True, 200, {"records": [{"action": "review"}], "summary": {"returned": 1}}))
        self.assertEqual(handler.get("/api/audit/export", {"format": ["csv"]}), (True, 200, {"format": "csv", "content": "audit-export"}))
        self.assertEqual(handler.get("/api/policies"), (True, 200, {"bundle": {"schema_version": 1}, "history": []}))

    def test_get_serverless_catalog_status_and_unknown(self):
        handler, _ = self.handler()
        handled, status, payload = handler.get("/api/models/serverless-catalog")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertTrue(payload["serverless_catalog"]["ok"])
        self.assertFalse(payload["refresh_catalog"])
        self.assertEqual(payload["trace"]["status"], "success")

        handled, status, payload = handler.get("/api/status")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertTrue(payload["proxy_listening"])
        self.assertEqual(payload["proxy"], "http://127.0.0.1:18081")
        self.assertEqual(payload["models"], {"path": "/v1/models"})

        handled, status, payload = handler.get("/api/traces", {"model": ["model-a"], "limit": ["5"]})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["traces"][0]["trace_id"], "trace-a")
        self.assertEqual(payload["traces"][0]["kwargs"]["model"], "model-a")
        self.assertEqual(payload["traces"][0]["kwargs"]["limit"], 5)

        handled, status, payload = handler.get("/api/evals")
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["datasets"], [{"id": "smoke"}])
        self.assertEqual(payload["runs"], [{"id": "eval-a"}])

        self.assertEqual(handler.get("/not-found"), (False, 404, {}))

    def test_operator_actions_emit_traces(self):
        handler, calls = self.handler()

        actions = [
            ("/api/generate", {"model": "image-a", "prompt": "tile"}, "image.generate"),
            ("/api/model-access-audit", {}, "model_access.audit"),
            ("/api/dedicated/build", {"model_id": "dedicated-a", "provider": "digitalocean"}, "dedicated.build"),
            ("/api/dedicated/teardown", {"model_id": "dedicated-a"}, "dedicated.teardown"),
            ("/api/tmux/start", {"name": "STARTTIME_session", "model": "model-a"}, "tmux.start"),
        ]

        for path, request, expected_action in actions:
            handled, status, payload = handler.post(path, request)
            self.assertTrue(handled)
            self.assertLess(status, 400)
            self.assertIn("trace_id", payload)
            self.assertEqual(calls[-1][0], "append_trace")
            self.assertEqual(calls[-1][1][0]["action"], expected_action)

        traced_actions = [call[1][0]["action"] for call in calls if call[0] == "append_trace"]
        self.assertIn("image.generate", traced_actions)
        self.assertIn("model_access.audit", traced_actions)
        self.assertIn("dedicated.build", traced_actions)
        self.assertIn("dedicated.teardown", traced_actions)
        self.assertIn("tmux.start", traced_actions)

    def test_post_chat_dedicated_preflight_test_models_and_tmux_terminal(self):
        handler, calls = self.handler()

        self.assertEqual(handler.post("/api/chat", {"messages": [{"content": "hi"}]}), (True, 202, {"text": "hi"}))
        handled, status, payload = handler.post("/api/chat", {"messages": [{"role": "user", "content": "hi"}], "retrieval": {"enabled": True}})
        self.assertTrue(handled)
        self.assertEqual(status, 202)
        self.assertEqual(payload["retrieval"]["matches"][0]["path"], "README.md")

        handled, status, payload = handler.post("/api/cost-forecast", {"action": "comparison"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["forecast_id"], "forecast-a")

        handled, status, payload = handler.post("/api/quota-planner", {"path": "/api/chat", "action": "chat"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["path"], "/api/chat")
        self.assertEqual(handler.post("/api/synthetic-load/preview", {"request_count": 3}), (True, 200, {"dry_run": True, "request": {"request_count": 3}}))
        self.assertEqual(handler.post("/api/synthetic-load/run", {"request_count": 3}), (True, 200, {"id": "load-a", "summary": {"requests": 3}}))
        self.assertEqual(handler.post("/api/config-drift/baseline", {"reason": "release"}), (True, 200, {"summary": {"state": "clean"}, "baseline": {"reason": "release"}}))
        self.assertEqual(handler.post("/api/config-drift/acknowledge", {"items": ["model_registry"]}), (True, 200, {"summary": {"state": "acknowledged"}, "acknowledged": ["model_registry"]}))
        self.assertEqual(handler.post("/api/rollback/preview", {"target_id": "runtime:a"}), (True, 200, {"target": {"id": "runtime:a"}, "summary": {"will_restore": 1}}))
        self.assertEqual(handler.post("/api/rollback/apply", {"target_id": "runtime:a", "reason": "restore"}), (True, 200, {"target": {"id": "runtime:a"}, "pre_backup": "/tmp/pre.tar.gz", "restored": [{"name": "model_registry"}]}))
        self.assertEqual(handler.post("/api/release-candidate/report", {"label": "rc1"}), (True, 200, {"ready": True, "label": "rc1", "report_file": "/tmp/rc.json"}))
        self.assertEqual(handler.post("/api/automation/rules", {"rules": [{"id": "r1"}]}), (True, 200, {"config": {"rules": [{"id": "r1"}]}}))
        self.assertEqual(handler.post("/api/automation/test", {"event": {"event": "eval_failure"}}), (True, 200, {"dry_run": True, "event": {"event": "eval_failure"}, "matched_count": 1}))
        self.assertEqual(handler.post("/api/automation/run", {"event": {"event": "eval_failure"}}), (True, 200, {"dry_run": False, "event": {"event": "eval_failure"}, "matched_count": 1}))
        self.assertEqual(handler.post("/api/policies/preview", {"bundle": {"schema_version": 1}}), (True, 200, {"dry_run": True, "blocking": False, "bundle": {"schema_version": 1}}))
        self.assertEqual(handler.post("/api/policies/apply", {"sections": ["budgets"]}), (True, 200, {"applied": True, "sections": ["budgets"]}))
        self.assertEqual(handler.post("/api/policies/rollback", {"version_id": "v1"}), (True, 200, {"rolled_back": True, "version_id": "v1"}))
        self.assertEqual(handler.post("/api/cost-anomalies/update", {"id": "cost-a", "action": "acknowledged"}), (True, 200, {"updated": "cost-a", "action": "acknowledged"}))
        self.assertEqual(handler.post("/api/notifications/update", {"id": "n1", "status": "acknowledged"}), (True, 200, {"notifications": [{"id": "n1", "status": "acknowledged"}], "summary": {"new": 0}}))
        self.assertEqual(handler.post("/api/workspace-bundles/export", {"sections": ["model_registry"]}), (True, 200, {"bundle_id": "bundle-a", "summary": {"model_registry": 1}, "bundle": {"manifest": {"id": "bundle-a"}, "sections": {}}}))
        self.assertEqual(handler.post("/api/workspace-bundles/preview", {"sections": ["eval_datasets"]}), (True, 200, {"dry_run": True, "blocking": False, "selected_sections": ["eval_datasets"]}))
        self.assertEqual(handler.post("/api/workspace-bundles/import", {"sections": ["eval_datasets"], "dry_run": False}), (True, 200, {"dry_run": False, "applied": ["eval_datasets"]}))

        handled, status, payload = handler.post("/api/context-window", {"action": "chat"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["models"][0]["model"], "model-a")

        self.assertEqual(handler.post("/api/rag/config", {"collections": [{"id": "docs"}]}), (True, 200, {"config": {"collections": [{"id": "docs"}]}}))
        self.assertEqual(handler.post("/api/rag/index", {"collection_id": "docs"}), (True, 200, {"indexed": [{"id": "docs"}]}))
        self.assertEqual(handler.post("/api/rag/search", {"query": "readme"}), (True, 200, {"query": "readme", "matches": [{"path": "README.md"}]}))
        self.assertEqual(handler.post("/api/tmux/permissions", {"permission_mode": "auto"}), (True, 200, {"permission_summary": {"risk_level": "high", "mode": "auto", "warnings": [{"code": "broad_bash"}]}}))
        self.assertEqual(handler.post("/api/model-access-drift/acknowledge", {"ids": ["event-a"]}), (True, 200, {"acknowledged": ["event-a"], "active_count": 0}))
        self.assertEqual(handler.post("/api/model-deprecations/preview", {"model_id": "old-model"}), (True, 200, {"model": "old-model", "replacement_model": "model-a", "affected": []}))
        self.assertEqual(handler.post("/api/model-deprecations/apply", {"model_id": "old-model", "replacement_model": "model-a"}), (True, 200, {"migration": {"id": "migration-a", "model": "old-model", "replacement_model": "model-a"}}))
        self.assertEqual(handler.post("/api/model-deprecations/rollback", {"migration_id": "migration-a"}), (True, 200, {"rolled_back": {"id": "migration-a", "status": "rolled_back"}}))

        handled, status, payload = handler.post("/api/eval-gates", {"surface": "gateway_policy"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["recommended_datasets"][0]["id"], "smoke")

        handled, status, payload = handler.post("/api/reviews", {"title": "Check output"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["review"]["id"], "review-new")
        self.assertEqual(handler.post("/api/reviews/update", {"id": "review-new", "status": "approved"}), (True, 200, {"review": {"id": "review-new", "status": "approved"}}))
        self.assertEqual(handler.post("/api/reviews/promote", {"id": "review-new", "target": "worklist"}), (True, 200, {"promotion": {"type": "worklist"}}))
        self.assertEqual(handler.post("/api/replay/snapshot", {"source": {"type": "chat", "id": "chat-a"}}), (True, 200, {"snapshot": {"source": {"type": "chat", "id": "chat-a"}, "available": True}}))
        self.assertEqual(handler.post("/api/replay", {"source": {"type": "chat", "id": "chat-a"}}), (True, 200, {"id": "replay-a", "source": {"type": "chat", "id": "chat-a"}, "results": []}))
        self.assertEqual(handler.post("/api/repository-context/preview", {"reference": "acme/app#42"}), (True, 200, {"prompt": "Repository context", "reference": "acme/app#42"}))
        self.assertEqual(handler.post("/api/repository-context/import", {"reference": "acme/app#42"}), (True, 200, {"launch_patch": {"print_prompt_append": "Repository context", "imported_context": {"repo": "app", "number": 42}}}))
        self.assertEqual(handler.post("/api/ci-triage/preview", {"reference": "acme/app#42"}), (True, 200, {"failure_count": 1, "reference": "acme/app#42"}))
        self.assertEqual(handler.post("/api/ci-triage/launch", {"reference": "acme/app#42"}), (True, 200, {"launch_patch": {"print_prompt_append": "CI fix", "imported_context": {"repo": "app", "ci_failures": [{"name": "unit"}]}}}))
        self.assertEqual(handler.post("/api/patch-review", {"session": "work"}), (True, 200, {"summary": {"changed_files": 1}, "session": "work"}))
        self.assertEqual(handler.post("/api/onboarding/complete", {"id": "model_access_token"}), (True, 200, {"summary": {"incomplete": 0}, "completed": "model_access_token"}))
        self.assertEqual(handler.post("/api/explain-decision", {"type": "quota"}), (True, 200, {"type": "quota", "selected_action": "allow"}))
        self.assertEqual(handler.post("/api/commands/dispatch", {"id": "traces.open"}), (True, 200, {"command": {"id": "traces.open"}, "action": {"type": "console_view", "target": "traces"}}))
        self.assertEqual(handler.post("/api/reporting-export", {"format": "sqlite"}), (True, 200, {"format": "sqlite", "path": "build/reporting/mde-llm-proxy-reporting.sqlite"}))
        self.assertEqual(handler.post("/api/session-snapshots", {"session": "work"}), (True, 200, {"snapshot": {"session": "work"}, "files": {"json": "/tmp/s.json", "markdown": "/tmp/s.md"}}))

        handled, status, payload = handler.post("/api/chat/compare", {"models": ["model-a", "model-b"], "prompt": "hi", "forecast": {"forecast_id": "forecast-a", "estimated_total_usd": 0.02}})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["models"], ["model-a", "model-b"])
        self.assertEqual(payload["chat"]["message_count"], 3)
        self.assertEqual(payload["forecast_actual"]["forecast_id"], "forecast-a")

        handled, status, payload = handler.post("/api/tmux/start", {"name": "work", "permission_mode": "bypassPermissions", "allowed_tools": "Bash(*)"})
        self.assertTrue(handled)
        self.assertEqual(status, 210)
        self.assertEqual(payload["started"]["permission_summary"]["risk_level"], "high")
        self.assertEqual(payload["started"]["permission_summary"]["mode"], "bypassPermissions")

        handler.deps["run_eval"] = lambda data: {"run": data, "summary": [{"total_cost_usd": 0.03}]}
        handled, status, payload = handler.post("/api/evals/run", {"dataset_id": "smoke", "forecast": {"forecast_id": "forecast-b", "estimated_total_usd": 0.05}})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["run"]["dataset_id"], "smoke")
        self.assertEqual(payload["forecast_actual"]["actual_usd"], 0.03)

        handled, status, payload = handler.post("/api/evals/datasets", {"id": "manual"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["dataset"], {"saved": {"id": "manual"}})

        handled, status, payload = handler.post("/api/evals/datasets/build", {"id": "from-trace"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["dataset"], {"built": {"id": "from-trace"}})

        handled, status, payload = handler.post("/api/chat/fork", {"source_chat_id": "ok", "message_index": 1})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["branch"]["id"], "branch-a")

        handled, status, payload = handler.post("/api/comparison-reports", {"title": "Report"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["report"]["id"], "report-a")

        handled, status, payload = handler.post("/api/dedicated/preflight", {"region": "nyc"})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["dedicated"], {"id": "cfg"})
        self.assertEqual(payload["events"], [{"state": "ready"}])
        self.assertTrue(any(call[0] == "append_dedicated_event" for call in calls))

        handled, status, payload = handler.post("/api/dedicated/capacity-plan", {"price_per_hour": 1})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual(payload["recommendation"], "build")
        self.assertEqual(payload["cost"]["daily_usd"], 24)
        self.assertEqual(payload["request"]["price_per_hour"], 1)

        handled, status, payload = handler.post("/api/dedicated/keep-alive", {"seconds": 600})
        self.assertTrue(handled)
        self.assertEqual(status, 207)
        self.assertEqual(payload["keep_alive"], {"seconds": 600})

        handled, status, payload = handler.post("/api/test-models", {})
        self.assertTrue(handled)
        self.assertEqual(status, 200)
        self.assertEqual([item["model"] for item in payload["results"]], ["model-a", "model-b", "image-a"])

        self.assertEqual(handler.post("/api/tmux/send", {"name": "s", "text": "hello", "enter": True}), (True, 212, {"name": "s", "text": "hello", "enter": True}))
        self.assertEqual(handler.post("/api/terminal/read", {"id": "term"}), (True, 217, {"id": "term"}))
        self.assertEqual(handler.post("/not-found", {}), (False, 404, {}))

    def test_post_service_errors_are_normalized_at_api_boundary(self):
        handler, _ = self.handler()
        handler.deps["chat_completion"] = lambda data: (400, {"error": "message is required", "trace_id": "abc"})

        handled, status, payload = handler.post("/api/chat", {"messages": []})

        self.assertTrue(handled)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "message is required")
        self.assertEqual(payload["message"], "message is required")
        self.assertEqual(payload["category"], "client")
        self.assertEqual(payload["status"], 400)
        self.assertEqual(payload["trace_id"], "abc")


if __name__ == "__main__":
    unittest.main()
