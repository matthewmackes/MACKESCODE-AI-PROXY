#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Python unit and smoke tests"
python3 -m unittest discover -s tests -v

echo "==> Coverage report"
python3 scripts/coverage-report.py --fail-under 1

echo "==> Python syntax checks"
python3 -m py_compile \
  image-studio.py \
  do-anthropic-proxy.py \
  matts-console.py \
  src/console/handlers/api_handler.py \
  src/console/handlers/api_versioning.py \
  src/console/handlers/auth_handler.py \
  src/console/handlers/static_handler.py \
  src/console/handlers/template_handler.py \
  src/console/handlers/websocket_handler.py \
  src/console/services/agentboard.py \
  src/console/services/audit.py \
  src/console/services/chat.py \
  src/console/services/dedicated.py \
  src/console/services/digitalocean.py \
  src/console/services/health.py \
  src/console/services/http_json.py \
  src/console/services/image_generation.py \
  src/console/services/model_registry.py \
  src/console/services/persistence.py \
  src/console/services/proxy_process.py \
  src/console/services/runtime_config.py \
  src/console/services/serverless_catalog.py \
  src/console/services/session.py \
  src/console/services/terminal.py \
  src/console/services/tmux_control.py \
  src/console/services/usage.py \
  src/console/services/wallpaper.py \
  src/console/services/websocket.py \
  tests/test_api_handler.py \
  tests/test_api_versioning.py \
  tests/test_auth_handler.py \
  tests/test_audit_service.py \
  tests/test_agentboard_service.py \
  tests/test_chat_service.py \
  tests/test_console_smoke.py \
  tests/test_dedicated_service.py \
  tests/test_digitalocean_service.py \
  tests/test_health_service.py \
  tests/test_http_json_service.py \
  tests/test_image_generation_service.py \
  tests/test_model_registry.py \
  tests/test_model_registry_service.py \
  tests/test_persistence_service.py \
  tests/test_proxy_process_service.py \
  tests/test_proxy_registry_reload.py \
  tests/test_release_scripts.py \
  tests/test_runtime_config_service.py \
  tests/test_serverless_catalog_service.py \
  tests/test_session_service.py \
  tests/test_static_handler.py \
  tests/test_template_handler.py \
  tests/test_terminal_service.py \
  tests/test_tmux_control_service.py \
  tests/test_usage_service.py \
  tests/test_wallpaper_service.py \
  tests/test_websocket_handler.py \
  tests/test_websocket_service.py \
  scripts/coverage-report.py \
  scripts/browser-smoke.py \
  scripts/health-validate.py \
  scripts/runtime-state.py

if command -v node >/dev/null 2>&1; then
  echo "==> Template JavaScript syntax"
  tmp_js="$(mktemp --suffix=.js)"
  trap 'rm -f "$tmp_js"' EXIT
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
  echo "==> Template JavaScript syntax skipped: node is not installed"
fi

echo "==> Headless browser smoke"
if [[ "${MATTS_BROWSER_SMOKE_REQUIRED:-0}" == "1" ]]; then
  python3 scripts/browser-smoke.py --required
else
  python3 scripts/browser-smoke.py
fi

echo "Release check passed."
