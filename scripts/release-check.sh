#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RELEASE_RUNTIME_ROOT="${MATTS_RELEASE_CHECK_RUNTIME_DIR:-$ROOT_DIR/build/release-check-runtime}"
tmp_js=""

release_check_proxy_pids() {
  local line pid cmd
  pgrep -af "do-anthropic-proxy.py" 2>/dev/null | while IFS= read -r line; do
    pid="${line%% *}"
    cmd="${line#* }"
    if [[ "$pid" != "$$" ]] && (
      [[ "$cmd" == *"--cost-file ${RELEASE_RUNTIME_ROOT}/"* ]] ||
      [[ "$cmd" == *"--budget-file ${RELEASE_RUNTIME_ROOT}/"* ]] ||
      [[ "$cmd" == *"--log-file ${RELEASE_RUNTIME_ROOT}/"* ]] ||
      [[ "$cmd" == *"--trace-file ${RELEASE_RUNTIME_ROOT}/"* ]]
    ); then
      printf '%s\n' "$pid"
    fi
  done
}

cleanup_release_proxy_processes() {
  local pid
  local pids=()
  local survivors=()
  while IFS= read -r pid; do
    if [[ -n "$pid" ]]; then
      pids+=("$pid")
    fi
  done < <(release_check_proxy_pids)
  if (( ${#pids[@]} == 0 )); then
    return
  fi
  echo "==> Cleaning release-check proxy processes: ${pids[*]}" >&2
  kill -TERM "${pids[@]}" 2>/dev/null || true
  sleep 0.5
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      survivors+=("$pid")
    fi
  done
  if (( ${#survivors[@]} > 0 )); then
    kill -KILL "${survivors[@]}" 2>/dev/null || true
  fi
}

release_check_cleanup() {
  cleanup_release_proxy_processes
  if [[ -n "${tmp_js:-}" ]]; then
    rm -f "$tmp_js"
  fi
}

trap release_check_cleanup EXIT
cleanup_release_proxy_processes
rm -rf "$RELEASE_RUNTIME_ROOT"
mkdir -p \
  "$RELEASE_RUNTIME_ROOT/studio" \
  "$RELEASE_RUNTIME_ROOT/evals" \
  "$RELEASE_RUNTIME_ROOT/eval-runs" \
  "$RELEASE_RUNTIME_ROOT/reporting" \
  "$RELEASE_RUNTIME_ROOT/wallpapers" \
  "$RELEASE_RUNTIME_ROOT/workspace-bundles"

export MATTS_STUDIO_DIR="$RELEASE_RUNTIME_ROOT/studio"
export MATTS_TRACE_FILE="$MATTS_STUDIO_DIR/traces.jsonl"
export MATTS_EVENT_FILE="$MATTS_STUDIO_DIR/events.jsonl"
export MATTS_AUDIT_FILE="$MATTS_STUDIO_DIR/audit.jsonl"
export MATTS_TMUX_SESSION_REGISTRY_FILE="$MATTS_STUDIO_DIR/tmux-sessions.json"
export MATTS_AUTH_SESSION_FILE="$MATTS_STUDIO_DIR/auth-sessions.json"
export MATTS_CONSOLE_AUTH_FILE="$MATTS_STUDIO_DIR/console-auth-token"
export MATTS_SERVERLESS_CATALOG_CACHE_FILE="$MATTS_STUDIO_DIR/serverless-model-catalog.json"
export MATTS_MODEL_ACCESS_DRIFT_FILE="$MATTS_STUDIO_DIR/model-access-drift.json"
export MATTS_MODEL_DEPRECATION_FILE="$MATTS_STUDIO_DIR/model-deprecations.json"
export MATTS_DEDICATED_CONFIG_FILE="$MATTS_STUDIO_DIR/dedicated-inference.json"
export MATTS_DEDICATED_EVENTS_FILE="$MATTS_STUDIO_DIR/dedicated-events.jsonl"
export MATTS_REVIEW_QUEUE_FILE="$MATTS_STUDIO_DIR/reviews.jsonl"
export MATTS_REPLAY_FILE="$MATTS_STUDIO_DIR/replays.jsonl"
export MATTS_RAG_CONFIG_FILE="$MATTS_STUDIO_DIR/local-rag.json"
export MATTS_RAG_INDEX_FILE="$MATTS_STUDIO_DIR/local-rag-index.json"
export MATTS_QUOTA_FILE="$MATTS_STUDIO_DIR/quotas.jsonl"
export MATTS_EVALS_DIR="$RELEASE_RUNTIME_ROOT/evals"
export MATTS_EVAL_RUNS_DIR="$RELEASE_RUNTIME_ROOT/eval-runs"
export MATTS_COMPARISON_REPORTS_DIR="$MATTS_STUDIO_DIR/comparison-reports"
export MATTS_SESSION_SNAPSHOTS_DIR="$MATTS_STUDIO_DIR/session-snapshots"
export MATTS_CONFIG_DRIFT_BASELINE_FILE="$MATTS_STUDIO_DIR/config-drift-baseline.json"
export MATTS_ONBOARDING_STATE_FILE="$MATTS_STUDIO_DIR/onboarding.json"
export MATTS_ROLLBACK_BACKUP_DIR="$MATTS_STUDIO_DIR/rollback-backups"
export MATTS_RELEASE_CANDIDATE_REPORTS_DIR="$MATTS_STUDIO_DIR/release-candidates"
export MATTS_AUTOMATION_RULES_FILE="$MATTS_STUDIO_DIR/automation-rules.json"
export MATTS_AUTOMATION_EXECUTION_LOG_FILE="$MATTS_STUDIO_DIR/automation-executions.jsonl"
export MATTS_POLICY_BUNDLE_FILE="$MATTS_STUDIO_DIR/policies.json"
export MATTS_POLICY_HISTORY_FILE="$MATTS_STUDIO_DIR/policy-history.jsonl"
export MATTS_SYNTHETIC_LOAD_RUNS_FILE="$MATTS_STUDIO_DIR/synthetic-load-runs.jsonl"
export MATTS_NOTIFICATION_STATE_FILE="$MATTS_STUDIO_DIR/notifications.json"
export MATTS_COST_ANOMALY_FILE="$MATTS_STUDIO_DIR/cost-anomalies.json"
export MATTS_WORKSPACE_BUNDLES_DIR="$RELEASE_RUNTIME_ROOT/workspace-bundles"
export MATTS_REPORTING_EXPORT_DIR="$RELEASE_RUNTIME_ROOT/reporting"
export MATTS_VALUE_SET_COST_FILE="$RELEASE_RUNTIME_ROOT/usage.jsonl"
export MATTS_VALUE_SET_BUDGET_FILE="$RELEASE_RUNTIME_ROOT/budgets.json"
export MATTS_VALUE_SET_LOG_FILE="$RELEASE_RUNTIME_ROOT/proxy.jsonl"
export MATTS_WALLPAPER_CACHE_DIR="$RELEASE_RUNTIME_ROOT/wallpapers"
export MATTS_V2_RUN_DB="$MATTS_STUDIO_DIR/v2-run.sqlite3"
export MATTS_V2_RAG_CONFIG_FILE="$MATTS_STUDIO_DIR/v2-rag-config.json"
export MATTS_V2_RAG_INDEX_FILE="$MATTS_STUDIO_DIR/v2-rag-index.json"

echo "==> Python unit and smoke tests"
python3 -m unittest discover -s tests -v

echo "==> Coverage report"
python3 scripts/coverage-report.py --fail-under 40

echo "==> Python syntax checks"
python3 -m py_compile \
  image-studio.py \
  do-anthropic-proxy.py \
  matts-console.py \
  matts-v2-console.py \
  matts-proxy-tui \
  backend/v2/app.py \
  backend/v2/contracts.py \
  backend/v2/api/auth.py \
  backend/v2/api/chat.py \
  backend/v2/api/code.py \
  backend/v2/api/console.py \
  backend/v2/api/create.py \
  backend/v2/api/models.py \
  backend/v2/api/observe.py \
  backend/v2/api/operate.py \
  backend/v2/api/research.py \
  backend/v2/api/run.py \
  backend/v2/api/tui.py \
  backend/v2/services/capabilities.py \
  backend/v2/services/code_attachments.py \
  backend/v2/services/legacy_console.py \
  backend/v2/services/model_showcase.py \
  backend/v2/services/proxy_cli.py \
  backend/v2/services/research_search.py \
  backend/v2/services/run_store.py \
  backend/v2/services/tui_session.py \
  src/console/handlers/api_handler.py \
  src/console/handlers/api_versioning.py \
  src/console/handlers/auth_handler.py \
  src/console/handlers/static_handler.py \
  src/console/handlers/template_handler.py \
  src/console/handlers/websocket_handler.py \
  src/console/utils/errors.py \
  src/console/services/agentboard.py \
  src/console/services/analytics.py \
  src/console/services/auth_session.py \
  src/console/services/audit.py \
  src/console/services/automation_rules.py \
  src/console/services/chat.py \
  src/console/services/comparison_reports.py \
  src/console/services/context_window.py \
  src/console/services/config_drift.py \
  src/console/services/cost_forecast.py \
  src/console/services/dedicated.py \
  src/console/services/digitalocean.py \
  src/console/services/eval_gates.py \
  src/console/services/health.py \
  src/console/services/http_json.py \
  src/console/services/image_generation.py \
  src/console/services/local_rag.py \
  src/console/services/permission_simulator.py \
  src/console/services/model_scorecards.py \
  src/console/services/model_registry.py \
  src/console/services/notifications.py \
  src/console/services/offline_mode.py \
  src/console/services/opentelemetry.py \
  src/console/services/persistence.py \
  src/console/services/plugins.py \
  src/console/services/provider_health.py \
  src/console/services/quota_planner.py \
  src/console/services/proxy_process.py \
  src/console/services/rate_limit.py \
  src/console/services/replay.py \
  src/console/services/release_candidate.py \
  src/console/services/review_queue.py \
  src/console/services/rollback_wizard.py \
  src/console/services/runtime_config.py \
  src/console/services/serverless_catalog.py \
  src/console/services/session.py \
  src/console/services/session_resources.py \
  src/console/services/session_snapshots.py \
  src/console/services/streaming_metrics.py \
  src/console/services/terminal.py \
  src/console/services/tmux_control.py \
  src/console/services/usage.py \
  src/console/services/wallpaper.py \
  src/console/services/websocket.py \
  src/console/services/workspace_bundles.py \
  tests/test_analytics_service.py \
  tests/test_api_handler.py \
  tests/test_api_versioning.py \
  tests/test_auth_session_service.py \
  tests/test_auth_handler.py \
  tests/test_audit_service.py \
  tests/test_agentboard_service.py \
  tests/test_automation_rules_service.py \
  tests/test_bootstrap_fallbacks.py \
  tests/test_chat_service.py \
  tests/test_comparison_report_service.py \
  tests/test_console_smoke.py \
  tests/test_context_window_service.py \
  tests/test_config_drift_service.py \
  tests/test_cost_forecast_service.py \
  tests/test_dedicated_service.py \
  tests/test_digitalocean_service.py \
  tests/test_eval_gate_service.py \
  tests/test_error_utils.py \
  tests/test_health_service.py \
  tests/test_http_json_service.py \
  tests/test_image_generation_service.py \
  tests/test_local_rag_service.py \
  tests/test_permission_simulator_service.py \
  tests/test_model_scorecards.py \
  tests/test_model_registry.py \
  tests/test_model_registry_service.py \
  tests/test_notification_center_service.py \
  tests/test_offline_mode_service.py \
  tests/test_opentelemetry_service.py \
  tests/test_persistence_service.py \
  tests/test_plugin_service.py \
  tests/test_provider_health_service.py \
  tests/test_proxy_process_service.py \
  tests/test_proxy_registry_reload.py \
  tests/test_quota_planner_service.py \
  tests/test_rate_limit_service.py \
  tests/test_release_scripts.py \
  tests/test_replay_service.py \
  tests/test_release_candidate_service.py \
  tests/test_review_queue_service.py \
  tests/test_rollback_wizard_service.py \
  tests/test_runtime_config_service.py \
  tests/test_serverless_catalog_service.py \
  tests/test_session_service.py \
  tests/test_session_resource_service.py \
  tests/test_session_snapshot_service.py \
  tests/test_static_handler.py \
  tests/test_streaming_metrics_service.py \
  tests/test_template_handler.py \
  tests/test_terminal_service.py \
  tests/test_tmux_control_service.py \
  tests/test_usage_service.py \
  tests/test_v2_capabilities_service.py \
  tests/test_v2_code_attachments.py \
  tests/test_v2_legacy_console.py \
  tests/test_v2_model_showcase_service.py \
  tests/test_v2_openapi_generation.py \
  tests/test_v2_proxy_cli_service.py \
  tests/test_v2_research_api.py \
  tests/test_v2_research_search_service.py \
  tests/test_v2_run_api.py \
  tests/test_v2_run_store.py \
  tests/test_v2_tui_session.py \
  tests/test_wallpaper_service.py \
  tests/test_workspace_bundle_service.py \
  tests/test_websocket_handler.py \
  tests/test_websocket_service.py \
  scripts/coverage-report.py \
  scripts/check-v2-frontend-audit.py \
  scripts/check-v2-frontend-bundles.py \
  scripts/browser-smoke.py \
  scripts/generate-v2-openapi.py \
  scripts/v2-browser-smoke.py \
  scripts/health-validate.py \
  scripts/runtime-state.py

echo "==> V2 OpenAPI generated artifact drift"
python3 scripts/generate-v2-openapi.py --check

if command -v node >/dev/null 2>&1; then
  echo "==> Template JavaScript syntax"
  tmp_js="$(mktemp --suffix=.js)"
  python3 - "$tmp_js" <<'PY'
import re
import sys
from pathlib import Path

html = Path("templates/main.html").read_text(encoding="utf-8")
scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
Path(sys.argv[1]).write_text("\n;\n".join(scripts), encoding="utf-8")
PY
  node --check "$tmp_js"
else
  if [[ "${MATTS_BROWSER_SMOKE_REQUIRED:-0}" == "1" ]]; then
    echo "Template JavaScript syntax requires node when MATTS_BROWSER_SMOKE_REQUIRED=1. Install Node.js and rerun release-check." >&2
    exit 1
  fi
  echo "==> Template JavaScript syntax skipped: node is not installed"
fi

if command -v npm >/dev/null 2>&1; then
  echo "==> React frontend build"
  if [[ ! -d frontend/node_modules ]]; then
    if [[ -f frontend/package-lock.json ]]; then
      npm ci --prefix frontend --no-audit
    else
      npm install --prefix frontend --no-audit
    fi
  fi
  npm run build --prefix frontend
  python3 scripts/check-v2-frontend-bundles.py
  python3 scripts/check-v2-frontend-audit.py
else
  if [[ "${MATTS_BROWSER_SMOKE_REQUIRED:-0}" == "1" ]]; then
    echo "React frontend build requires npm when MATTS_BROWSER_SMOKE_REQUIRED=1. Install Node.js/npm and rerun release-check." >&2
    exit 1
  fi
  echo "==> React frontend build skipped: npm is not installed"
fi

echo "==> Headless browser smoke"
if [[ "${MATTS_BROWSER_SMOKE_REQUIRED:-0}" == "1" ]]; then
  python3 scripts/browser-smoke.py --required --quiet
else
  python3 scripts/browser-smoke.py --quiet
fi

echo "==> V2 headless browser smoke"
if [[ "${MATTS_BROWSER_SMOKE_REQUIRED:-0}" == "1" ]]; then
  python3 scripts/v2-browser-smoke.py --required
else
  python3 scripts/v2-browser-smoke.py
fi

echo "Release check passed."
