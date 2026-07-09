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
- Local eval datasets and model comparison runs with cost, latency, failures, selected answers, and baseline deltas
- global model management with key audit, allowed/forbidden states, enriched model labels, and detailed model hero cards
- Serverless and Dedicated Inference lifecycle controls with build, health, budget, idle teardown, and fallback routing feedback

Create workspace behavior is documented in `docs/create-experience.md`. Rich model detail cards are documented in `docs/model-hero-cards.md`.

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

The launcher requires a Matts Value Set model access key. Write it to:

```text
$HOME/.mcnf-do-model-access-token
```

or intentionally override it for one run:

```bash
MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE=1 MATTS_VALUE_SET_ACCESS_KEY=... ./claude-DO.sh --doctor
```

The launcher no longer ships with a default embedded access key. If neither the token file nor the explicit override is present, it exits before starting the proxy.

The proxy listens on:

```text
127.0.0.1:18081
```

Console runtime defaults are stored in:

```text
config/console.json
```

Use `MATTS_CONSOLE_CONFIG_FILE=/path/to/console.json` to point at another JSON config. Environment variables such as `MATTS_STUDIO_PORT`, `MATTS_VALUE_SET_PROXY_PORT`, `MATTS_MODEL_AUTO_ENABLE_MAX_USD`, and `MATTS_CONSOLE_LOG_LEVEL` still override the file. The `paths` section controls template, default model registry, active model registry, Dedicated, Serverless cache, tmux registry, wallpaper, usage, budget, and log locations; existing path-specific environment variables still take precedence. Model pricing comes from the configured model registry data. Secrets and tokens remain file/env based and are not stored in this config.

The active model registry is `config/models.json`. `./claude-DO.sh --list-models`, the proxy `/v1/models` endpoint, Code/Create selectors, model hero cards, and Console LLM management all derive from that registry. Serverless catalog refresh can add new DigitalOcean-hosted models, and models priced below the configured auto-enable threshold are enabled by policy once access audit confirms the key can use them.

Use Console > LLM Management > key audit to probe Serverless text models with a tiny request. The result marks models as allowed, forbidden, rate-limited, or probe-failed, syncs the proxy, and prevents Code/Create from showing stale selectable models. Chat message `Show Detail` exposes requested model, routed model, backend, trace ID, usage, cost, upstream ID, and fallback/routing reason. `Model Info` opens the richer model profile.

Console auth supports the generated owner token plus optional scoped role/session tokens. Sensitive model, Dedicated, budget, billing, tmux, and terminal actions are permission-checked and written to `$HOME/.cache/matts-value-set/studio/audit.jsonl`. Role-token setup is documented in `SECURITY.md`.

Dedicated Inference live state is runtime data. The default state file is under the console app cache, and `config/dedicated-inference.example.json` is the publishable template. Do not commit live Dedicated endpoint metadata, access tokens, CA certificates, or raw DigitalOcean resource payloads.

Release config and runtime state are intentionally separate:

| Area | Release-owned file | Runtime-owned default |
| --- | --- | --- |
| Console defaults | `config/console.json` | `MATTS_CONSOLE_CONFIG_FILE` override when needed |
| Default model bootstrap | `config/default-models.json` | Active registry below |
| Active model registry | `config/models.json` | Operator-edited source of truth; schema_version `1` |
| Dedicated Inference | `config/dedicated-inference.example.json` | `$HOME/.cache/matts-value-set/studio/dedicated-inference.json` |
| Serverless catalog cache | none | `$HOME/.cache/matts-value-set/studio/serverless-model-catalog.json` |
| Audit log | none | `$HOME/.cache/matts-value-set/studio/audit.jsonl` |
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

Console JSON API v1 is available under `/api/v1/*`. Legacy `/api/*` paths remain compatible and include deprecation headers; migration details are in `docs/api-versioning.md`.

Run the local unit/smoke test suite with the standard library runner:

```bash
python3 -m unittest discover -s tests -v
```

Before committing or publishing a release, run the repeatable local release check:

```bash
scripts/release-check.sh
```

It runs the unit/smoke suite, coverage report, Python syntax checks, template JavaScript syntax checks when `node` is available, and a headless browser smoke check when Playwright is installed. GitHub Actions installs Playwright and requires the browser smoke pass for Code, Create, Console, and terminal page navigation.

The full-screen terminal uses one WebSocket connection per browser attachment and one temporary `tmux attach-session` PTY child per connection. The bridge clamps resize messages, handles WebSocket ping/pong control frames, logs connect/disconnect reasons, and tears down the attach child on close. Connection pooling is intentionally not used because tmux is already the persistent layer; pooling browser PTYs would make stale socket state harder to reason about without improving session durability.

Release, upgrade, rollback, runtime-state backup, and post-upgrade health validation are documented in `RELEASE.md`.

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

Dedicated Inference automation also requires a DigitalOcean API token with permission to create, inspect, and destroy Dedicated Inference resources and create access tokens. The Console preflight and lifecycle panels surface missing permissions, region/GPU availability, account status, balance/prepay status when available, idle warnings, and teardown countdowns.

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
