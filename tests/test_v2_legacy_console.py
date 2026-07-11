import types
import unittest
from http import HTTPStatus

from backend.v2.services.legacy_console import LegacyConsoleAdapter


class V2LegacyConsoleAdapterTests(unittest.TestCase):
    def test_overview_combines_sessions_and_agentboard_summary(self):
        module = types.SimpleNamespace(
            tmux_session_items=lambda: [
                {"name": "live-one", "live": True},
                {"name": "previous-one", "live": False},
            ],
            agentboard_payload=lambda: {
                "counts": {"working": 1, "waiting": 0},
                "sessions": [{"name": "live-one"}],
                "tasks": [{"session": "live-one", "status": "working"}],
                "leaderboard": [{"name": "live-one", "score": 1}],
                "usage": {"total_usd": 0.5},
                "evals": {"requests_ok": 3, "requests_error": 1, "spend_usd": 0.25},
            },
        )
        adapter = LegacyConsoleAdapter(module_loader=lambda: module, clock=lambda: 123.0)

        payload = adapter.overview()

        self.assertEqual(payload["generated_at"], 123.0)
        self.assertEqual(payload["summary"]["sessions_total"], 2)
        self.assertEqual(payload["summary"]["sessions_live"], 1)
        self.assertEqual(payload["summary"]["agent_sessions"], 1)
        self.assertEqual(payload["summary"]["requests_ok"], 3)
        self.assertEqual(payload["summary"]["requests_error"], 1)
        self.assertEqual(payload["summary"]["spend_usd"], 0.25)
        self.assertEqual(payload["errors"], {})

    def test_overview_reports_legacy_failures_without_raising(self):
        def fail_sessions():
            raise RuntimeError("tmux unavailable")

        def fail_agentboard():
            raise RuntimeError("agentboard unavailable")

        module = types.SimpleNamespace(tmux_session_items=fail_sessions, agentboard_payload=fail_agentboard)
        adapter = LegacyConsoleAdapter(module_loader=lambda: module)

        payload = adapter.overview()

        self.assertEqual(payload["sessions"], [])
        self.assertIn("tmux unavailable", payload["errors"]["sessions"])
        self.assertIn("agentboard unavailable", payload["errors"]["agentboard"])

    def test_code_session_defaults_and_actions_delegate_to_legacy_module(self):
        calls = []
        tmux_calls = []
        audits = []
        drift_actions = []
        drift_rollback = {"note": "Compare and restore only after review.", "restore_command": "python3 scripts/runtime-state.py restore <archive>"}
        drift_current = {"sha256_short": "current1234567890", "sha256": "current1234567890abcdef", "rollback": drift_rollback}
        drift_baseline = {"sha256_short": "baseline12345678", "sha256": "baseline12345678abcdef", "rollback": drift_rollback}

        module = types.SimpleNamespace(
            TEXT_MODELS=["model-a", "model-b"],
            default_text_model=lambda: "model-a",
            script_dir=lambda: "/workspace/project",
            tmux_session_items=lambda: [
                {"name": "v2-code", "display_name": "V2 Code", "live": True, "attached": False, "estimated_cost_usd": 0.01, "estimated_tokens": 123},
                {"name": "previous-code", "display_name": "Previous Code", "live": False, "read_only": True, "estimated_cost_usd": 0.02, "estimated_tokens": 10},
            ],
            permission_simulation=lambda payload: {"risk_level": "critical", "mode": payload.get("permission_mode"), "warnings": [{"code": "permission_bypass"}]},
            commands_payload=lambda query="", actor=None, context=None: {"commands": [{"id": "traces.open", "title": "Open Traces", "available": True, "action": {"type": "console_view", "target": "traces"}}], "summary": {"commands": 1}},
            dispatch_command=lambda payload: {"command": {"id": payload["id"], "title": "Open Traces"}, "action": {"type": "console_view", "target": "traces"}, "dispatched_at": 123.0},
            replay_records_payload=lambda limit=50: {"replays": [{"id": "replay-a"}], "limit": limit},
            replay_snapshot_payload=lambda payload: {"snapshot": {"source": payload["source"], "available": True, "redaction": "trace_summary"}},
            replay_payload=lambda payload: {"id": "replay-b", "source": payload["source"], "summary": {"models": 1}},
            workspace_bundle_payload=lambda: {"bundles": [{"id": "bundle-a"}]},
            export_workspace_bundle=lambda payload: {"bundle_id": "bundle-b", "bundle": {"manifest": {"id": "bundle-b"}}, "actor": payload.get("actor")},
            preview_workspace_bundle_import=lambda payload: {"blocking": False, "selected_sections": payload.get("selected_sections") or []},
            import_workspace_bundle=lambda payload: {"dry_run": False, "applied": payload.get("selected_sections") or []},
            context_window_payload=lambda payload: {"action": payload.get("action") or "chat", "input_tokens_est": 12, "models": [{"model": "model-a", "fits": True}]},
            chat_completion=lambda payload: (HTTPStatus.OK, {"text": "answer", "model": payload.get("model")}),
            console_status=lambda: {"status": "ok"},
            cost_summary_payload=lambda: {"last_24h_total_usd": 1.25},
            analytics_payload=lambda days=7: {"summary": {"requests": 3}, "days": days},
            provider_health_payload=lambda: {"findings": []},
            console_metrics_text=lambda: 'matts_model_requests_total{model="model-a",route="serverless",status="success"} 1\nmatts_budget_used_usd{window="24h"} 0.5\n',
            read_traces=lambda **kwargs: [{"trace_id": "trace-a", "status": "ok", "kwargs": kwargs}],
            audit_explorer_payload=lambda payload=None: {"records": [{"action": "chat", "payload": payload or {}}], "summary": {"returned": 1}},
            list_eval_datasets=lambda: [{"id": "smoke", "name": "Smoke", "example_count": 2}],
            list_eval_runs=lambda: [{"id": "eval-a", "summary": [{"requests": 2, "failures": 1, "total_cost_usd": 0.015}]}],
            save_eval_dataset=lambda payload: {"id": payload.get("id"), "examples": payload.get("examples") or []},
            build_eval_dataset=lambda payload: {"id": payload.get("id"), "examples": payload.get("examples") or []},
            run_eval=lambda payload: {"id": "eval-run", "dataset_id": payload.get("dataset_id"), "summary": []},
            reporting_export_status=lambda: {"status": "ready"},
            export_reporting_database=lambda payload: {"format": payload.get("format") or "duckdb", "path": "/tmp/mde-llm-proxy-reporting.sqlite", "redaction_mode": "default_safe"},
            reporting_integration_payload=lambda: {"dashboards": [], "metrics": {"reachable": True, "series_count": 2}, "exporter": {"enabled": False, "kind": "opentelemetry"}, "privacy": {"bounded_labels": True, "excluded": ["prompts"]}},
            eval_gate_payload=lambda payload: {"decision": "allowed", "surface": payload.get("surface")},
            review_queue_payload=lambda status="", severity="", reason="": {"reviews": [{"id": "review-a", "status": "open"}], "summary": {"open": 1}},
            release_candidate_payload=lambda: {"checks": [{"name": "tests", "status": "passed"}], "summary": {"blocking": 0}},
            rollback_targets_payload=lambda: {"targets": [{"id": "rollback-a"}]},
            config_drift_payload=lambda: {
                "items": [{"name": "console_config"}, {"name": "tmux_registry"}],
                "drift": [{
                    "name": "console_config",
                    "risk": "high",
                    "status": "changed",
                    "path": "config/console.json",
                    "rollback": drift_rollback,
                    "current": drift_current,
                    "baseline": drift_baseline,
                }],
                "summary": {"active_drift_count": 1},
            },
            mark_config_drift_baseline=lambda payload: drift_actions.append(("baseline", payload)) or {"summary": {"state": "clean"}, "baseline_file": "/tmp/baseline.json", "actor": payload.get("actor")},
            acknowledge_config_drift=lambda payload: drift_actions.append(("acknowledge", payload)) or {"summary": {"state": "acknowledged"}, "acknowledged": payload.get("items"), "actor": payload.get("actor")},
            automation_payload=lambda: {"rules": [{"id": "rule-a"}]},
            quota_planner_payload=lambda: {"budgets": [{"id": "daily"}]},
            synthetic_load_payload=lambda: {"runs": [{"id": "load-a"}]},
            ci_triage_payload=lambda: {"findings": [{"id": "ci-a"}]},
            preview_ci_triage=lambda payload: {"reference": payload.get("reference"), "failure_count": 0},
            launch_ci_triage=lambda payload: {"reference": payload.get("reference"), "failure_count": 1, "launch_patch": {"print_prompt_append": "CI fix"}},
            preview_repository_context=lambda payload: {"reference": payload.get("reference"), "prompt": "Repository context"},
            import_repository_context=lambda payload: {"preview": {"reference": payload.get("reference"), "degraded": False}, "launch_patch": {"print_prompt_append": "Repository context"}},
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            offline_mode_payload=lambda: {"enabled": False},
            model_deprecation_payload=lambda payload=None: {"items": [{"id": "model-a"}]},
            write_release_candidate_report=lambda payload: {"label": payload.get("label"), "report_file": "/tmp/release.json"},
            rollback_preview_payload=lambda payload: {"target_id": payload.get("target_id"), "summary": {"will_restore": 0}},
            rollback_apply_payload=lambda payload: {"target_id": payload.get("target_id"), "reason": payload.get("reason"), "restored": []},
            update_review_item=lambda payload: {"review": {"id": payload.get("id"), "status": payload.get("status")}},
            promote_review_item=lambda payload: {"promotion": {"type": payload.get("target") or "eval"}},
            save_automation_rules=lambda payload: {"config": {"rules": payload.get("rules") or []}},
            test_automation_event=lambda payload: {"dry_run": True, "matched_count": 1, "event": payload.get("event")},
            run_automation_event=lambda payload: {"dry_run": False, "matched_count": 1, "event": payload.get("event")},
            run_due_automation_schedules=lambda payload: {"dry_run": bool(payload.get("dry_run")), "executed_count": 1, "schedules": [{"rule_id": "scheduled-eval", "due": True}]},
            preview_model_deprecation=lambda payload: {"model": payload.get("model_id"), "replacement_model": "model-b"},
            apply_model_deprecation=lambda payload: {"migration": {"id": "migration-a", "model": payload.get("model_id"), "replacement_model": payload.get("replacement_model")}},
            rollback_model_deprecation=lambda payload: {"rolled_back": {"id": payload.get("migration_id"), "status": "rolled_back"}},
            explain_decision_payload=lambda payload: {"type": "gateway_routing", "selected_action": payload.get("trace_id") or "decision", "raw": {"prompt": "[redacted]"}},
            tmux_start=lambda payload: (HTTPStatus.OK, {"name": payload["name"], "sessions": []}),
            tmux_capture=lambda name: (HTTPStatus.OK, {"name": name, "screen": "ready"}),
            tmux_send_text=lambda name, text, enter=True: calls.append((name, text, enter)) or (HTTPStatus.OK, {"ok": True}),
            tmux_send_key=lambda name, key: tmux_calls.append(("key", name, key)) or (HTTPStatus.OK, {"ok": True}),
            tmux_rename_session=lambda old_name, new_name, display_name=None: tmux_calls.append(("rename", old_name, new_name, display_name)) or (HTTPStatus.OK, {"ok": True, "name": new_name, "display_name": display_name or new_name}),
            tmux_stop=lambda name: (HTTPStatus.OK, {"ok": True, "name": name}),
        )
        adapter = LegacyConsoleAdapter(module_loader=lambda: module)

        defaults = adapter.code_session_defaults()
        self.assertEqual(defaults["default_project_dir"], "/workspace/project")
        self.assertEqual(defaults["default_model"], "model-a")
        self.assertEqual(defaults["text_models"], ["model-a", "model-b"])

        preview = adapter.preview_code_session_permissions({"permission_mode": "bypassPermissions"})
        self.assertEqual(preview["risk_level"], "critical")
        self.assertEqual(preview["mode"], "bypassPermissions")
        commands = adapter.command_palette("trace")
        self.assertEqual(commands["commands"][0]["id"], "traces.open")
        dispatched = adapter.dispatch_command({"id": "traces.open", "actor": {"permissions": ["view_traces"]}})
        self.assertEqual(dispatched["action"]["target"], "traces")
        self.assertEqual(adapter.replay_records(limit=5)["replays"][0]["id"], "replay-a")
        self.assertTrue(adapter.replay_snapshot({"source": {"type": "trace", "id": "trace-a"}})["snapshot"]["available"])
        self.assertEqual(adapter.run_replay({"source": {"type": "trace", "id": "trace-a"}})["summary"]["models"], 1)
        self.assertEqual(adapter.workspace_bundles()["bundles"][0]["id"], "bundle-a")
        self.assertEqual(adapter.export_workspace_bundle({"actor": {"id": "owner"}})["bundle_id"], "bundle-b")
        self.assertFalse(adapter.preview_workspace_bundle_import({"selected_sections": ["prompt_templates"]})["blocking"])
        self.assertEqual(adapter.import_workspace_bundle({"selected_sections": ["run_profiles"]})["applied"], ["run_profiles"])
        self.assertEqual(adapter.context_window({"action": "chat"})["input_tokens_est"], 12)
        self.assertEqual(adapter.chat_completion({"model": "model-a"})[1]["text"], "answer")
        observe = adapter.observe_payload(days=3, trace_limit=2, audit_limit=1)
        self.assertEqual(observe["console"]["status"], "ok")
        self.assertEqual(observe["analytics"]["days"], 3)
        self.assertEqual(observe["traces"][0]["trace_id"], "trace-a")
        self.assertEqual(observe["evals"]["summary"]["datasets"], 1)
        self.assertEqual(observe["evals"]["summary"]["requests"], 2)
        self.assertEqual(observe["evals"]["summary"]["total_cost_usd"], 0.015)
        self.assertEqual(observe["telemetry"]["policy"]["status"], "pass")
        self.assertIn("matts_model_requests_total", observe["telemetry"]["metric_families"])
        self.assertEqual(adapter.observe_traces(limit=1)["traces"][0]["trace_id"], "trace-a")
        self.assertEqual(adapter.observe_audit({"limit": 1})["summary"]["returned"], 1)
        self.assertEqual(adapter.eval_payload()["datasets"][0]["id"], "smoke")
        self.assertEqual(adapter.telemetry_payload()["label_keys"], ["model", "route", "status", "window"])
        self.assertEqual(adapter.export_reporting({"format": "sqlite"})["format"], "sqlite")
        self.assertEqual(adapter.export_reporting({"format": "sqlite"})["redaction_mode"], "default_safe")
        operate = adapter.operate_payload()
        self.assertEqual(operate["eval_gates"]["decision"], "allowed")
        self.assertEqual(operate["summary"]["open_reviews"], 1)
        self.assertEqual(operate["summary"]["release_checks"], 1)
        self.assertEqual(operate["summary"]["rollback_targets"], 1)
        self.assertEqual(operate["summary"]["config_drift_items"], 1)
        self.assertEqual(len(operate["config_drift"]["items"]), 2)
        self.assertEqual(operate["config_drift"]["drift"][0]["name"], "console_config")
        self.assertEqual(operate["config_drift"]["drift"][0]["current"]["sha256_short"], "current1234567890")
        self.assertEqual(operate["config_drift"]["drift"][0]["baseline"]["sha256_short"], "baseline12345678")
        self.assertEqual(operate["config_drift"]["drift"][0]["rollback"]["note"], "Compare and restore only after review.")
        self.assertEqual(operate["config_drift"]["drift"][0]["current"]["rollback"]["note"], "Compare and restore only after review.")
        baseline = adapter.mark_config_drift_baseline({"reason": "verified release", "actor": {"id": "infra"}})
        acked = adapter.acknowledge_config_drift({"items": ["console_config"], "reason": "expected", "actor": {"id": "infra"}})
        self.assertEqual(baseline["actor"]["id"], "infra")
        self.assertEqual(acked["acknowledged"], ["console_config"])
        self.assertEqual(drift_actions[0][0], "baseline")
        self.assertEqual(drift_actions[1][1]["reason"], "expected")
        self.assertEqual(adapter.preview_ci_triage({"reference": "acme/app#5"})["reference"], "acme/app#5")
        launch = adapter.launch_ci_triage({"reference": "acme/app#5", "actor": {"id": "owner"}})
        self.assertEqual(launch["launch_patch"]["print_prompt_append"], "CI fix")
        self.assertEqual(audits[-1][0][0], "ci_triage.launch")
        self.assertEqual(audits[-1][1]["request"]["reference"], "acme/app#5")
        self.assertEqual(adapter.preview_repository_context({"reference": "acme/app#6"})["prompt"], "Repository context")
        repo_import = adapter.import_repository_context({"reference": "acme/app#6", "actor": {"id": "owner"}})
        self.assertEqual(repo_import["launch_patch"]["print_prompt_append"], "Repository context")
        self.assertEqual(audits[-1][0][0], "repository_context.import")
        self.assertEqual(audits[-1][1]["request"]["reference"], "acme/app#6")
        self.assertEqual(adapter.write_release_candidate_report({"label": "rc"})["label"], "rc")
        self.assertEqual(adapter.preview_rollback({"target_id": "rollback-a"})["target_id"], "rollback-a")
        self.assertEqual(adapter.apply_rollback({"target_id": "rollback-a", "reason": "restore"})["reason"], "restore")
        self.assertEqual(adapter.update_review({"id": "review-a", "status": "approved"})["review"]["status"], "approved")
        self.assertEqual(adapter.promote_review({"id": "review-a", "target": "worklist"})["promotion"]["type"], "worklist")
        self.assertEqual(adapter.save_eval_dataset({"id": "dataset-a", "examples": [{"input": "ok"}]})["dataset"]["id"], "dataset-a")
        self.assertEqual(adapter.build_eval_dataset({"id": "dataset-b", "examples": [{"input": "ok"}]})["dataset"]["id"], "dataset-b")
        self.assertEqual(adapter.run_eval({"dataset_id": "dataset-a"})["dataset_id"], "dataset-a")
        self.assertEqual(adapter.save_automation_rules({"rules": [{"id": "rule-a"}]})["config"]["rules"][0]["id"], "rule-a")
        self.assertTrue(adapter.test_automation_event({"event": {"event": "eval_failure"}})["dry_run"])
        self.assertFalse(adapter.run_automation_event({"event": {"event": "eval_failure"}})["dry_run"])
        self.assertEqual(adapter.run_due_automation_schedules({"dry_run": True})["schedules"][0]["rule_id"], "scheduled-eval")
        self.assertEqual(adapter.preview_model_deprecation({"model_id": "model-a"})["replacement_model"], "model-b")
        self.assertEqual(adapter.apply_model_deprecation({"model_id": "model-a", "replacement_model": "model-b"})["migration"]["id"], "migration-a")
        self.assertEqual(adapter.rollback_model_deprecation({"migration_id": "migration-a"})["rolled_back"]["status"], "rolled_back")
        self.assertEqual(adapter.explain_decision({"trace_id": "trace-a"})["selected_action"], "trace-a")
        tmux_workspace = adapter.tmux_workspace()
        self.assertEqual(tmux_workspace["summary"]["sessions_total"], 2)
        self.assertEqual(tmux_workspace["summary"]["sessions_live"], 1)
        self.assertEqual(tmux_workspace["summary"]["sessions_read_only"], 1)
        self.assertEqual(tmux_workspace["summary"]["estimated_tokens"], 133)
        self.assertIn("C-c", tmux_workspace["allowed_keys"])
        self.assertEqual(tmux_workspace["terminal"]["path"], "/#code")
        self.assertEqual(tmux_workspace["terminal"]["query_param"], "session")
        self.assertEqual(tmux_workspace["terminal"]["default_legacy_port"], 18182)
        self.assertEqual(adapter.start_code_session({"name": "v2-code"})[1]["name"], "v2-code")
        self.assertEqual(adapter.capture_code_session("v2-code")[1]["screen"], "ready")
        self.assertEqual(adapter.send_code_session("v2-code", "hello", enter=False)[1]["ok"], True)
        self.assertEqual(adapter.start_tmux_session({"name": "v2-tmux"})[1]["name"], "v2-tmux")
        self.assertEqual(adapter.capture_tmux_session("v2-code")[1]["screen"], "ready")
        self.assertEqual(adapter.send_tmux_text("v2-code", "world", enter=True)[1]["ok"], True)
        self.assertEqual(adapter.send_tmux_key("v2-code", "C-c")[1]["ok"], True)
        self.assertEqual(adapter.rename_tmux_session("v2-code", "v2-renamed", "Renamed")[1]["display_name"], "Renamed")
        self.assertEqual(adapter.stop_tmux_session("v2-code")[1]["name"], "v2-code")
        self.assertEqual(calls, [("v2-code", "hello", False), ("v2-code", "world", True)])
        self.assertEqual(tmux_calls, [("key", "v2-code", "C-c"), ("rename", "v2-code", "v2-renamed", "Renamed")])
        self.assertEqual(adapter.stop_code_session("v2-code")[1]["name"], "v2-code")


if __name__ == "__main__":
    unittest.main()
