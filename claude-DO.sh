#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
home_dir="${HOME:-/root}"

proxy_script="${MATTS_VALUE_SET_PROXY_SCRIPT:-$script_dir/do-anthropic-proxy.py}"
token_file="${MATTS_VALUE_SET_TOKEN_FILE:-$home_dir/.mcnf-do-model-access-token}"
embedded_access_key=""
access_key=""
if [[ "${MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE:-0}" == "1" && -n "${MATTS_VALUE_SET_ACCESS_KEY:-}" ]]; then
  access_key="$MATTS_VALUE_SET_ACCESS_KEY"
elif [[ ! -s "$token_file" ]]; then
  access_key="$embedded_access_key"
fi
base_url="${MATTS_VALUE_SET_BASE_URL:-https://inference.do-ai.run}"
proxy_host="${MATTS_VALUE_SET_PROXY_HOST:-127.0.0.1}"
proxy_port="${MATTS_VALUE_SET_PROXY_PORT:-18081}"
cost_file="${MATTS_VALUE_SET_COST_FILE:-$home_dir/.cache/matts-value-set/usage.jsonl}"
budget_file="${MATTS_VALUE_SET_BUDGET_FILE:-$home_dir/.cache/matts-value-set/budgets.json}"
log_file="${MATTS_VALUE_SET_LOG_FILE:-$home_dir/.cache/matts-value-set/proxy.jsonl}"
proxy_stdout_log="$home_dir/.cache/matts-value-set/proxy-stdout.log"
tmux_session="${MATTS_VALUE_SET_TMUX_SESSION:-matts-value-set-proxy}"

model="${MATTS_VALUE_SET_MODEL:-deepseek-3.2}"
model_config_file="${MATTS_MODEL_CONFIG_FILE:-$script_dir/config/models.json}"
model_access_state_file="${MATTS_MODEL_ACCESS_STATE_FILE:-$home_dir/.cache/matts-value-set/studio/model-access-state.json}"
default_model_config_file="${MATTS_DEFAULT_MODEL_CONFIG_FILE:-$script_dir/config/default-models.json}"
# Filled by load_model_registry from config/models.json, falling back to the
# sanctioned bootstrap data in config/default-models.json.
models='[]'
text_models=()
image_models=()
declare -A model_aliases=()
load_model_registry() {
  local output
  output="$(python3 - "$model_config_file" "$default_model_config_file" "$model_access_state_file" <<'REGISTRYPY'
import json, shlex, sys

def load_access_state(path):
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    models = data.get('models')
    return models if isinstance(models, dict) else {}

def apply_access_state(rows, state):
    if not state:
        return rows
    out = []
    for row in rows:
        item = dict(row)
        overlay = state.get(str(item.get('id') or ''))
        if isinstance(overlay, dict):
            if overlay.get('access_status'):
                item['access_status'] = str(overlay.get('access_status'))
            if overlay.get('last_error'):
                item['last_error'] = str(overlay.get('last_error'))
        out.append(item)
    return out

def route_enabled(m):
    if not isinstance(m, dict) or not m.get('enabled', True) or not m.get('id'):
        return False
    if m.get('serverless') and m.get('type', 'text') == 'text':
        return m.get('access_status') == 'ok'
    return True

def active_models(path, access_state=None):
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    rows = data.get('models', data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    rows = apply_access_state(rows, access_state or {})
    return [m for m in rows if route_enabled(m)]

registry_file, bootstrap_file, access_state_file = sys.argv[1], sys.argv[2], sys.argv[3]
access_state = load_access_state(access_state_file)
try:
    active = active_models(registry_file, access_state)
except Exception:
    active = []
if not active:
    try:
        active = active_models(bootstrap_file)
    except Exception:
        active = []
    if active:
        print('claude-DO: model registry %s is unavailable; using bootstrap fallback %s' % (registry_file, bootstrap_file), file=sys.stderr)
if not active:
    print('claude-DO: model registry %s and bootstrap fallback %s are unavailable; using minimal fallback model list' % (registry_file, bootstrap_file), file=sys.stderr)
    active = [{'id': 'deepseek-3.2', 'type': 'text'}]
text=[str(m['id']) for m in active if m.get('type','text') == 'text']
image=[str(m['id']) for m in active if m.get('type') == 'image']
all_ids=text+image
aliases=[]
for m in active:
    for alias in m.get('aliases') or []:
        if alias:
            aliases.append((str(alias), str(m['id'])))
print('models='+shlex.quote(json.dumps(all_ids)))
print('text_models=('+ ' '.join(shlex.quote(x) for x in text) +')')
print('image_models=('+ ' '.join(shlex.quote(x) for x in image) +')')
print('model_aliases=()')
for alias, target in aliases:
    print('model_aliases['+shlex.quote(alias)+']='+shlex.quote(target))
REGISTRYPY
  )"
  eval "$output"
}
load_model_registry

doctor=0
list_models=0
show_costs=0
show_budget=0
restart=0
test_models=0
show_status=0
project_dir=""
project_dir_explicit=0
claude_passthrough=()

usage() {
  cat <<'EOF'
usage: claude-DO.sh [--model MODEL] [--doctor] [--list-models] [--costs] [--budget] [--status]
                    [--restart] [--test-models] [--project-dir DIR] [-- CLAUDE_ARGS...]

Current models are loaded from config/models.json.
Run --list-models to inspect the active global registry.
EOF
}

resolve_model() {
  local key="${1:-}"
  if [[ -n "${model_aliases[$key]:-}" ]]; then
    printf '%s
' "${model_aliases[$key]}"
  else
    printf '%s
' "$key"
  fi
}

is_known_model() {
  local candidate
  candidate="$(resolve_model "$1")"
  python3 - "$candidate" "$models" <<'PY'
import json
import sys
print("yes" if sys.argv[1] in json.loads(sys.argv[2]) else "no")
PY
}

model="$(resolve_model "$model")"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --doctor)
      doctor=1
      shift
      ;;
    --list-models|models)
      list_models=1
      shift
      ;;
    --costs|costs)
      show_costs=1
      shift
      ;;
    --budget|budget)
      show_budget=1
      shift
      ;;
    --status|status)
      show_status=1
      shift
      ;;
    --restart)
      restart=1
      shift
      ;;
    --test-models|test-models)
      test_models=1
      shift
      ;;
    --model)
      model="$(resolve_model "${2:-}")"
      [[ -n "$model" ]] || { echo "--model requires a model id" >&2; exit 2; }
      shift 2
      ;;
    --model=*)
      model="$(resolve_model "${1#*=}")"
      shift
      ;;
    --project-dir|--cwd)
      project_dir="${2:-}"
      [[ -n "$project_dir" ]] || { echo "$1 requires a directory" >&2; exit 2; }
      project_dir_explicit=1
      shift 2
      ;;
    --project-dir=*|--cwd=*)
      project_dir="${1#*=}"
      project_dir_explicit=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      claude_passthrough+=("$@")
      break
      ;;
    *)
      claude_passthrough+=("$1")
      shift
      ;;
  esac
done

if [[ "$list_models" != "1" && "$show_costs" != "1" && "$show_budget" != "1" && "$show_status" != "1" && "$doctor" != "1" && "$(is_known_model "$model")" != "yes" ]]; then
  echo "Unknown model: $model" >&2
  usage >&2
  exit 2
fi

if [[ "$project_dir_explicit" == "1" ]]; then
  [[ -d "$project_dir" ]] || { echo "Project directory does not exist: $project_dir" >&2; exit 1; }
  cd "$project_dir"
fi

if [[ "$list_models" == "1" ]]; then
  python3 - "$models" <<'PY'
import json
import sys

models = json.loads(sys.argv[1])
print(json.dumps({
    "object": "list",
    "data": [{"id": model, "object": "model"} for model in models],
}, indent=2))
PY
  exit 0
fi

umask 077
mkdir -p "$(dirname -- "$token_file")" "$(dirname -- "$cost_file")" "$(dirname -- "$budget_file")" "$(dirname -- "$log_file")" "$(dirname -- "$proxy_stdout_log")"
if [[ -n "$access_key" ]]; then
  printf '%s\n' "$access_key" >"$token_file"
elif [[ ! -s "$token_file" ]]; then
  echo "Set MATTS_VALUE_SET_ACCESS_KEY or write a model access key to $token_file" >&2
  exit 1
fi
chmod 600 "$token_file"

proxy_is_listening() {
  python3 - "$proxy_host" "$proxy_port" <<'PY'
import socket
import sys

sock = socket.socket()
sock.settimeout(0.2)
try:
    sock.connect((sys.argv[1], int(sys.argv[2])))
finally:
    sock.close()
PY
}

proxy_matches_config() {
  python3 - "$base_url" "$models" "http://${proxy_host}:${proxy_port}/v1/claude-do/capabilities" <<'PY'
import json
import sys
import urllib.request

expected = sys.argv[1].rstrip("/")
expected_models = json.loads(sys.argv[2])
try:
    with urllib.request.urlopen(sys.argv[3], timeout=1) as resp:
        data = json.load(resp)
except Exception:
    sys.exit(1)

actual = str(data.get("base_url", "")).rstrip("/")
actual_models = data.get("models") or []
sys.exit(0 if data.get("provider") == "matts-value-set" and actual == expected and actual_models == expected_models else 1)
PY
}

stop_proxy() {
  local pids=""
  if command -v tmux >/dev/null 2>&1; then
    tmux kill-session -t "$tmux_session" 2>/dev/null || true
  fi
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"$proxy_port" -sTCP:LISTEN 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    pids="$(fuser -n tcp "$proxy_port" 2>/dev/null || true)"
  fi
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    sleep 0.2
  fi
}

start_proxy() {
  if [[ "$restart" == "1" ]]; then
    stop_proxy
  fi
  if proxy_is_listening 2>/dev/null && ! proxy_matches_config 2>/dev/null; then
    stop_proxy
  fi
  if ! proxy_is_listening 2>/dev/null; then
    local proxy_cmd=(
      python3 "$proxy_script"
      --provider matts-value-set
      --default-model "$model"
      --host "$proxy_host"
      --port "$proxy_port"
      --token-file "$token_file"
      --base-url "$base_url"
      --model-config-file "$model_config_file"
      --models "$models"
      --cost-file "$cost_file"
      --budget-file "$budget_file"
      --log-file "$log_file"
    )
    if command -v tmux >/dev/null 2>&1; then
      local tmux_cmd=""
      printf -v tmux_cmd '%q ' "${proxy_cmd[@]}"
      tmux kill-session -t "$tmux_session" 2>/dev/null || true
      tmux new-session -d -s "$tmux_session" "$tmux_cmd"
    elif command -v setsid >/dev/null 2>&1; then
      setsid -f "${proxy_cmd[@]}" >"$proxy_stdout_log" 2>&1
    else
      nohup "${proxy_cmd[@]}" >"$proxy_stdout_log" 2>&1 &
    fi
    for _ in {1..50}; do
      proxy_is_listening 2>/dev/null && break
      sleep 0.1
    done
  fi
}

pretty_json() {
  python3 -m json.tool 2>/dev/null || cat
}

test_text_model() {
  local model_id="$1"
  python3 - "$model_id" "http://${proxy_host}:${proxy_port}/v1/messages" <<'PY'
import json
import sys
import urllib.error
import urllib.request

model, url = sys.argv[1:]
body = {
    "model": model,
    "messages": [{"role": "user", "content": "Reply with only: ok"}],
    "max_tokens": 8,
    "stream": False,
}
req = urllib.request.Request(
    url,
    data=json.dumps(body).encode("utf-8"),
    headers={"content-type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    text = "".join(part.get("text", "") for part in data.get("content", []) if isinstance(part, dict))
    print(f"PASS {model}: {text[:80]}")
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"FAIL {model}: HTTP {exc.code} {detail[:240]}")
    sys.exit(1)
except Exception as exc:
    print(f"FAIL {model}: {type(exc).__name__}: {exc}")
    sys.exit(1)
PY
}

test_image_model() {
  local model_id="$1"
  python3 - "$model_id" "http://${proxy_host}:${proxy_port}/v1/images/generations" <<'PY'
import json
import sys
import urllib.error
import urllib.request

model, url = sys.argv[1:]
body = {
    "model": model,
    "prompt": "simple smoke test image of the word ok on white paper",
    "size": "512x512",
    "n": 1,
}
req = urllib.request.Request(
    url,
    data=json.dumps(body).encode("utf-8"),
    headers={"content-type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    count = len(data.get("data") or [])
    print(f"PASS {model}: {count} image result(s)")
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"FAIL {model}: HTTP {exc.code} {detail[:240]}")
    sys.exit(1)
except Exception as exc:
    print(f"FAIL {model}: {type(exc).__name__}: {exc}")
    sys.exit(1)
PY
}

start_proxy

if [[ "$show_costs" == "1" ]]; then
  curl -fsS "http://${proxy_host}:${proxy_port}/v1/claude-do/costs" | pretty_json
  exit 0
fi

if [[ "$show_budget" == "1" ]]; then
  curl -fsS "http://${proxy_host}:${proxy_port}/v1/claude-do/budget" | pretty_json
  exit 0
fi

if [[ "$show_status" == "1" ]]; then
  printf 'MODE=matts-value-set\n'
  printf 'MODEL=%s\n' "$model"
  printf 'BASE_URL=%s\n' "$base_url"
  printf 'PROXY=http://%s:%s\n' "$proxy_host" "$proxy_port"
  printf 'TOKEN_FILE=%s\n' "$token_file"
  printf 'PROXY_LISTENING='
  if proxy_is_listening 2>/dev/null; then
    printf 'yes\n'
  else
    printf 'no\n'
  fi
  exit 0
fi

if [[ "$doctor" == "1" ]]; then
  printf 'MODE=matts-value-set\n'
  printf 'MODEL=%s\n' "$model"
  printf 'BASE_URL=%s\n' "$base_url"
  printf 'PROXY=http://%s:%s\n' "$proxy_host" "$proxy_port"
  printf 'TOKEN_FILE=%s\n' "$token_file"
  printf 'MODELS=%s\n' "$models"
  exit 0
fi

if [[ "$test_models" == "1" ]]; then
  status=0
  for model_id in "${text_models[@]}"; do
    test_text_model "$model_id" || status=1
  done
  for model_id in "${image_models[@]}"; do
    test_image_model "$model_id" || status=1
  done
  exit "$status"
fi

if [[ "$model" == "stable-diffusion-3.5-large" ]]; then
  echo "stable-diffusion-3.5-large is an image model. Use ./matts-image instead." >&2
  exit 2
fi

export DISABLE_TELEMETRY=1
export DISABLE_ERROR_REPORTING=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export ANTHROPIC_BASE_URL="http://${proxy_host}:${proxy_port}"
export ANTHROPIC_AUTH_TOKEN="$(<"$token_file")"
export ANTHROPIC_CUSTOM_HEADERS="Authorization: Bearer $ANTHROPIC_AUTH_TOKEN"
unset ANTHROPIC_API_KEY
export ANTHROPIC_MODEL="$model"
export ANTHROPIC_DEFAULT_OPUS_MODEL="$model"
export ANTHROPIC_DEFAULT_SONNET_MODEL="$model"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$model"
export CLAUDE_CODE_SUBAGENT_MODEL="$model"

claude_args=(--setting-sources user,project,local --model "$model")
has_permission_arg=0
for arg in "${claude_passthrough[@]}"; do
  case "$arg" in
    --permission-mode|--permission-mode=*|--dangerously-skip-permissions|--allow-dangerously-skip-permissions)
      has_permission_arg=1
      ;;
  esac
done
if [[ "$has_permission_arg" == "0" ]]; then
  if [[ "${EUID:-$(id -u)}" == "0" || -n "${SUDO_UID:-}" ]]; then
    claude_args+=(--permission-mode acceptEdits)
  else
    if [[ "${MATTS_REQUIRE_PERMISSION_PROMPTS:-0}" == "1" ]]; then
      echo "ERROR: MATTS_REQUIRE_PERMISSION_PROMPTS=1 is set; refusing to auto-enable --dangerously-skip-permissions." >&2
      echo "       Pass an explicit --permission-mode <mode> (e.g. acceptEdits) to launch." >&2
      exit 1
    fi
    echo "WARNING: defaulting to --dangerously-skip-permissions; Claude Code permission prompts are disabled for this session." >&2
    echo "         Pass --permission-mode <mode> to override, or set MATTS_REQUIRE_PERMISSION_PROMPTS=1 to refuse this default." >&2
    claude_args+=(--dangerously-skip-permissions)
  fi
fi

if ! proxy_is_listening 2>/dev/null; then
  echo "ERROR: proxy is not listening on ${proxy_host}:${proxy_port}; not launching Claude Code against a dead proxy." >&2
  echo "       Inspect the proxy log (tmux session '${tmux_session}' or ${proxy_stdout_log}) and retry, or run: $0 --doctor" >&2
  exit 1
fi

exec claude "${claude_args[@]}" "${claude_passthrough[@]}"
