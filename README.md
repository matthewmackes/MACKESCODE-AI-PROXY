# Matts Value Set Claude Code Proxy

Private Claude Code launcher and Anthropic-compatible local proxy for the current Matts Value Set models.

## Current Models

- `deepseek` -> `deepseek-3.2`
- `deepseek-v4` -> `deepseek-v4-pro`
- `glm` -> `glm-5`
- `mistral` -> `mistral-3-14B`
- `codex` -> `openai-gpt-5.3-codex`
- `sd35` -> `stable-diffusion-3.5-large`

## Launch Claude Code

```bash
./claude-DO.sh --model deepseek
./claude-DO.sh --model deepseek-v4
./claude-DO.sh --model glm
./claude-DO.sh --model mistral
./claude-DO.sh --model codex
```

Shortcut wrappers:

```bash
./claude-deepseek
./claude-deepseek-v4
./claude-glm
./claude-mistral
./claude-codex
```

All local controls are exposed through the pure Python unified web console:

```bash
./matts-console.py
```

On a headless machine, the console binds to `0.0.0.0:18181` and prints a token-protected URL such as:

```text
http://SERVER_IP:18181/?token=...
```

The console includes:

- embedded Claude Code terminal
- persistent Claude Code tmux sessions that survive browser refreshes
- full-screen external browser terminal backed by xterm.js and tmux attach
- autonomy profiles, permission modes, tool allow/deny lists, context dirs, run modes, output formats, and budget caps
- text model chat and smoke tests
- image prompt studio, comparison grid, builder, history, and iteration
- proxy status, costs, budgets, and recent logs
- reporting page for local model usage and DigitalOcean billing data
- AgentBoard tab for all local tmux sessions, status inference, task/trajectory summaries, approximate eval metrics, and model/session leaderboard data

Stable Diffusion is also available through the one-shot helper:

```bash
./matts-image --prompt "a product render of a titanium keyboard" --output out.png
```

## Operations

```bash
./claude-DO.sh --doctor
./claude-DO.sh --list-models
./claude-DO.sh --costs
./claude-DO.sh --budget
./claude-DO.sh --restart --doctor
./claude-DO.sh --test-models
./matts-console.py --no-open
```

The launcher writes the embedded Matts Value Set access key to:

```text
$HOME/.mcnf-do-model-access-token
```

To intentionally override the embedded key for one run:

```bash
MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE=1 MATTS_VALUE_SET_ACCESS_KEY=... ./claude-DO.sh --doctor
```

The proxy listens on:

```text
127.0.0.1:18081
```

Console runtime defaults are stored in:

```text
config/console.json
```

Use `MATTS_CONSOLE_CONFIG_FILE=/path/to/console.json` to point at another JSON config. Environment variables such as `MATTS_STUDIO_PORT`, `MATTS_VALUE_SET_PROXY_PORT`, `MATTS_MODEL_AUTO_ENABLE_MAX_USD`, and `MATTS_CONSOLE_LOG_LEVEL` still override the file. The `paths` section controls template, default model registry, active model registry, Dedicated, Serverless cache, tmux registry, wallpaper, usage, budget, and log locations; existing path-specific environment variables still take precedence. Model pricing comes from the configured model registry data. Secrets and tokens remain file/env based and are not stored in this config.

Dedicated Inference live state is runtime data. The default state file is under the console app cache, and `config/dedicated-inference.example.json` is the publishable template. Do not commit live Dedicated endpoint metadata, access tokens, CA certificates, or raw DigitalOcean resource payloads.

Release config and runtime state are intentionally separate:

| Area | Release-owned file | Runtime-owned default |
| --- | --- | --- |
| Console defaults | `config/console.json` | `MATTS_CONSOLE_CONFIG_FILE` override when needed |
| Default model bootstrap | `config/default-models.json` | Active registry below |
| Active model registry | `config/models.json` | Operator-edited source of truth; schema_version `1` |
| Dedicated Inference | `config/dedicated-inference.example.json` | `$HOME/.cache/matts-value-set/studio/dedicated-inference.json` |
| Serverless catalog cache | none | `$HOME/.cache/matts-value-set/studio/serverless-model-catalog.json` |
| Wallpaper cache | none | `$HOME/.cache/matts-value-set/wallpapers/` |
| Weather defaults/cache | none | Browser/runtime fallback state only |
| Usage, budget, and traces | none | `$HOME/.cache/matts-value-set/usage.jsonl`, budgets, and trace files |
| tmux sessions | none | `$HOME/.cache/matts-value-set/studio/tmux-sessions.json` |

The web console exposes unauthenticated operational endpoints for local smoke checks and monitoring:

```text
/health   basic liveness
/ready    readiness with proxy and launcher checks
/version  console version metadata
/metrics  Prometheus text metrics
```

Console JSON API failures use a standard error shape:

```json
{"error":"message","message":"message","code":"machine_code","category":"client","status":400}
```

The `error` field remains a plain string for older clients. New UI and diagnostics should prefer `code`, `category`, `status`, and optional `details`. JSON error responses are also logged as sanitized structured warning records with request method, path, status, code, category, message, and detail keys only.

Run the local unit/smoke test suite with the standard library runner:

```bash
python3 -m unittest discover -s tests -v
```

Before committing or publishing a release, run the repeatable local release check:

```bash
scripts/release-check.sh
```

It runs the unit/smoke suite, coverage report, Python syntax checks, template JavaScript syntax checks when `node` is available, and a headless browser smoke check when Playwright is installed. GitHub Actions installs Playwright and requires the browser smoke pass for Code, Create, Console, and terminal page navigation.

To run the browser smoke locally:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
scripts/browser-smoke.py --required
```

Generate the dependency-free line-hit coverage report directly with:

```bash
scripts/coverage-report.py
```

Coverage artifacts are written under `build/coverage/`.

DigitalOcean reporting uses the public DigitalOcean API. To enable account billing data, set:

```bash
export DIGITALOCEAN_TOKEN=...
export DIGITALOCEAN_ACCOUNT_URN=do:team:...
```

The token needs `billing:read`. Without those values, the Reporting page still shows local model spend from proxy logs.

## AgentBoard

The console includes an AgentBoard-inspired tab built into the existing `18181` GUI. It discovers all local tmux sessions, captures pane previews, infers whether sessions are working, waiting, or asking for permission, and exposes full controls to open, send input, send common keys, or kill a selected session. The task, eval, and leaderboard views are derived from tmux pane state plus local proxy usage logs; no separate AgentBoard service or database is required.

Real-time usage and estimated costs are appended to:

```text
$HOME/.cache/matts-value-set/usage.jsonl
```

Budget limits can be configured in:

```text
$HOME/.cache/matts-value-set/budgets.json
```

Example:

```json
{"daily_usd": 10, "monthly_usd": 100}
```
