# MDE LLM-PROXY

Private Claude Code launcher and Anthropic-compatible local proxy for the current MDE LLM-PROXY models.

## Quick Start

1. Put the MDE LLM-PROXY model access key in `$HOME/.mcnf-do-model-access-token`.
2. Verify the launcher, registry, and local proxy:

```bash
./claude-DO.sh --doctor
./claude-DO.sh --list-models
```

3. Start the React V2 console:

```bash
./matts-v2-console.py --build-frontend
```

4. Open the printed token-protected URL, usually `http://SERVER_IP:18182/?token=...`.
5. Before committing or publishing changes, run:

```bash
MATTS_BROWSER_SMOKE_REQUIRED=1 ./scripts/release-check.sh
```

Primary local services:

| Surface | Command | Default address | Purpose |
| --- | --- | --- | --- |
| Local proxy | `./claude-DO.sh --doctor` or any `./claude-DO.sh --model ...` launch | `127.0.0.1:18081` | Anthropic-compatible model proxy |
| React V2 console | `./matts-v2-console.py --build-frontend` | `0.0.0.0:18182` | Primary Carbon-styled operator interface and `/v2/*` API |

Use V2 for console work. The Python `image-studio.py` module remains as a V2 service-adapter composition layer, not as a supported standalone V1 UI.

## Governance

Project governance, architectural locks, runtime-state boundaries, definition of
done, and AI-assisted work rules are in `GOVERNANCE.md`. Supporting operator and
release-readiness documents:

- `docs/DECISIONS.md` - append-only architecture and policy decision log
- `docs/NEEDS-OPERATOR.md` - work that needs a live cloud resource or operator decision
- `docs/THREAT_MODEL.md` - proxy, console, terminal, model, trace, and cloud threat model
- `docs/COMPLIANCE.md` - integrity sweep checklist and findings log
- `docs/console-app-shell.md` - ConsoleApp shell, lifecycle hooks, and handler dependency migration
- `docs/domain-models.md` - dataclass domain records, validation, and JSON compatibility conventions
- `docs/policy-service.md` - centralized policy decisions, precedence, and side-effect boundaries
- `docs/runtime-state-repositories.md` - shared runtime JSON/JSONL repositories, metadata, redaction, and backup conventions
- `docs/event-envelope.md` - unified local event envelope, redaction, sinks, and correlation semantics
- `docs/run-experience.md` - V2 prompt template, run profile, run record, and runtime-state boundaries
- `docs/opentelemetry.md` - optional OTLP/HTTP trace and metrics export setup and privacy notes
- `docs/grafana-reporting.md` - Prometheus metrics, Grafana OSS dashboards, and local setup snippets
- `docs/sql-reporting-export.md` - redacted DuckDB/SQLite reporting export for Metabase and local SQL tools
- `docs/gateway-routing.md` - gateway policy precedence, SLO routing, constraints, and proof
- `docs/cost-forecasting.md` - pre-run budget forecasts, warnings, and calibration notes
- `docs/cost-anomaly-detection.md` - local cost spike detection, attribution, and response workflow
- `docs/agent-execution-graphs.md` - AgentBoard execution graph sources, confidence levels, and privacy notes
- `docs/model-scorecards.md` - model scorecard sources, scoring, and confidence levels
- `docs/unified-model-card.md` - unified model identity card anatomy, Health grades, favorites, and detail dialog
- `docs/eval-gates.md` - eval-on-change gates, evidence matching, and override semantics
- `docs/review-queue.md` - human review queue triggers, lifecycle, and promotions
- `docs/replay.md` - trace and saved-chat replay targets, diffs, and redaction limits
- `docs/repository-context-import.md` - GitHub issue/PR context preview, import, metadata, and privacy boundaries
- `docs/ci-failure-triage.md` - failed check summaries, taxonomy hints, log excerpts, and Code fix-session launch
- `docs/patch-review-assistant.md` - local changed-file summaries, risk notes, commit/PR suggestions, and privacy limits
- `docs/golden-path-onboarding.md` - first-run setup checklist, headless host flow, runtime completion state, and redaction limits
- `docs/decision-explanations.md` - Explain views for routing, quota, budget, eval, Dedicated, and policy decisions
- `docs/provider-health.md` - provider health signals, classifications, and operator actions
- `docs/failure-taxonomy.md` - normalized failure categories, remediation hints, and aggregation surfaces
- `docs/model-access-drift.md` - model access regression detection, alerts, and recovery workflow
- `docs/model-deprecation-workflow.md` - deprecated model detection, migration preview, and rollback workflow
- `docs/dedicated-capacity-planner.md` - Dedicated cost, fit, break-even, and capacity uncertainty planning
- `docs/quota-planner.md` - quota policy, precedence, warnings, and block behavior
- `docs/config-drift.md` - last-known-good baselines, drift acknowledgement, and rollback guidance
- `docs/rollback-wizard.md` - rollback target discovery, pre-rollback backups, restore flow, and health checks
- `docs/release-candidate-dashboard.md` - release readiness checks, blockers, advisories, and report workflow
- `docs/automation-rules.md` - local event automation rules, signed webhooks, and safety patterns
- `docs/notifications.md` - persistent operational inbox, categories, retention, and triage workflow
- `docs/audit-explorer.md` - audit-log search, related evidence links, export, and retention notes
- `docs/policy-as-code.md` - validated policy bundles, fingerprints, history, and rollback workflow
- `docs/synthetic-load-testing.md` - bounded model-route load tests, safety limits, and provider-risk guidance
- `docs/offline-mode.md` - offline/degraded mode behavior, cache confidence, and live-action guards
- `docs/workspace-bundles.md` - redacted workspace export/import bundles and migration workflow
- `docs/context-window-inspector.md` - prompt token estimates, context-fit warnings, and accuracy limits
- `docs/streaming-metrics.md` - elapsed time, first-token latency, tokens/sec, and streaming fallback semantics
- `docs/conversation-branching.md` - chat fork storage, branch comparison, eval promotion, and replay limits
- `docs/comparison-reports.md` - saved model comparison reports, exports, eval promotion, and privacy notes
- `docs/local-rag.md` - local document collections, indexing, retrieval controls, citations, and privacy boundaries
- `docs/permission-simulator.md` - Claude Code launch permission preview, warnings, safer presets, and override limits
- `docs/session-resources.md` - local tmux session CPU, memory, process, idle, and disk monitoring limits
- `docs/session-snapshots.md` - local AgentBoard diagnostic snapshots, redaction, and safe sharing guidance
- `docs/evals.md` - local eval datasets, dataset builder APIs, and privacy boundaries
- `docs/command-palette.md` - searchable operator commands, shortcuts, context, permissions, and audit behavior
- `DISCLAIMER.md` - private-operator and cloud-cost disclaimer
- `SUPPORT.md` - support and diagnostic entry points

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

All local controls are exposed through the React V2 console:

```bash
./matts-v2-console.py --build-frontend
```

On a headless machine, the console binds to `0.0.0.0:18182` and prints a token-protected bootstrap URL such as:

```text
http://SERVER_IP:18182/?token=...
```

The React v2 console serves the built frontend and API from port `18182` and also binds to all interfaces by default:

```bash
./matts-v2-console.py --build-frontend
```

When `frontend/node_modules` is missing, the V2 launcher and release checks use `npm ci --no-audit` against `frontend/package-lock.json` for reproducible installs. `npm install --no-audit` is only used as a fallback if no lockfile exists; dependency audit enforcement is handled by the explicit production audit gate in `scripts/release-check.sh`.

For remote browser sessions, open `18182/tcp` on the host firewall and use the printed bootstrap URL. V2 stores the token in browser storage, removes `?token=...` from the address bar after first load, and sends follow-up API requests with `x-matts-console-token` headers. A fresh same-browser tab can reuse the stored token; a new browser/profile can use the in-app Sign In control or the printed bootstrap URL. Put the bootstrap token before any hash route, for example `http://SERVER_IP:18182/?token=...#research`; V2 also recovers tokens from hash-style URLs when a remote session rewrites the route. If the frontend is served from a different origin, set `VITE_API_BASE_URL=http://SERVER_IP:18182` when building/serving the frontend, or allow explicit origins with repeated `--cors-origin` flags.

## React V2 Console

The React V2 console is the primary operator interface. It is built around Carbon Design styling, Carbon icon assets from `branding/Mackes-Carbon/scalable`, IBM Plex Sans for interface text, and IBM Plex Mono for terminals, traces, and diagnostic output.

Start with the workspace that matches the job:

- Use **Chat** for direct model work and transcript handoff.
- Use **Code** for Claude Code/tmux sessions, terminal command history, per-event packets, and screenshot review.
- Use **Research** when an answer needs search, citations, images, examples, maps, Wikipedia, technical docs, DigitalOcean references, and multiple fast analyst models.
- Use **Create** for image generation, image model selection, output metadata, and image history reuse.
- Use **Advanced** for the Models tab plus Console, Run, Observe, Operate, drift, release, and rollback operations. The drawer nav stays Chat/Code/Research/Create; open Advanced from the drawer's Settings button, the Ctrl/Command+K quick switcher, or `#advanced` / `#models` URLs.

V2 workspaces:

- **Chat** - model-selected conversation, voice profile controls, transcript copy/download, and direct composer input without canned suggestions. Use Ctrl/Command+Enter to send multiline prompts; plain Enter stays available for new lines.
- **Code** - Claude Code/tmux session launch, the TMux/TUI console, terminal input, command output history, per-event copy packets, Code Brief export, and screenshot/image review. Use Ctrl/Command+Enter to send terminal input; paste, drop, or attach PNG/JPEG/WebP/GIF images so a selected model can inspect UI, terminal, or code screenshots.
- **Research** - Bing-style search line with Enter-to-search, custom engine selection, at least two search engines per run, required source packs, three low-cost fast analyst LLMs, and a fourth coordinator LLM. Evidence includes search results, image sources, examples, mapping coordinates, Wikipedia, technical documentation, DigitalOcean LLM references, and local RAG when enabled. Research briefs and individual source packets are copyable.
- **Create** - image-only generation studio with image model selection, generated asset rendering, output metadata, Ctrl/Command+Enter submit, and image history restore/copy packets.
- **Advanced** - operational surfaces grouped into Monitor (Observe), Configure (Models, Run, Console), and Govern (Operate), with Overview folded into the Models landing. The Models tab is the centerpiece LLM showcase: route status, pricing, access state, measured Health grades, brand identity and flags, model comparison, discovery, and a startup **Whats New** modal with DigitalOcean LLM links. The Console tab is a lean System Operations dashboard (proxy/TUI status, command palette, operational state), while accounting, reporting, governance, evals, and deprecations live across the Operate, Observe, and Models tabs. Terminal and tmux/TUI controls belong in Code.

Model cards should remain a showcase for the available LLMs. Every surface renders one unified model identity card — brand accent, national-flag badge, status/cost/context facts, a measured Health letter grade (A-D from recent trace success rate and p50 latency), and a favorite star — and clicking a card opens the shared model-detail dialog (`docs/unified-model-card.md`). Favorites lead every list: Chat keeps a Pinned contact strip over a collapsed all-contacts drawer, dropdowns tuck non-favorites behind a "More models" expander, and the Models grid leads with favorite cards. When model metadata includes public company artwork or brand URLs, V2 displays that artwork with tracked source notes; otherwise it falls back to local brand marks or generated initials. Nation palettes are based on the model training nation, so USA, China, and other model families stay visually distinct.

Copy/export behavior is intentionally broad: Chat transcripts, Research briefs, Research source packets, Code Briefs, per-event Code output packets, Create history packets, model details, and operational reports are designed to move cleanly into tickets, reviews, docs, or follow-up prompts.

If a remote browser shows a blank page, first verify `http://SERVER_IP:18182/v2/health` from the host, then confirm the host firewall allows `18182/tcp`, the browser has bootstrapped the current token, and any split-origin frontend was built with `VITE_API_BASE_URL=http://SERVER_IP:18182`. Wrong-host API calls usually show as `api endpoint not found` or failed `/v2/*` requests in the browser developer console.

The console includes:

- embedded Claude Code terminal
- persistent Claude Code tmux sessions that survive browser refreshes
- full-screen external browser terminal backed by xterm.js and tmux attach
- V2 keyboard-first Chat, Code, Create, and Research inputs: Ctrl/Command+Enter sends multiline Chat/Create prompts and Code terminal input, while Enter runs the Research search line
- autonomy profiles, permission modes, tool allow/deny lists, context dirs, run modes, output formats, and budget caps
- text model chat and smoke tests
- image prompt studio, comparison grid, builder, history, and iteration
- proxy status, costs, budgets, and recent logs
- pre-run budget forecasts for comparisons, evals, image batches, and Dedicated builds
- reporting page for local model usage and DigitalOcean billing data
- AgentBoard tab for all local tmux sessions, status inference, task/trajectory summaries, approximate eval metrics, and model/session leaderboard data
- AgentBoard graph timelines for session state, model routes, audit actions, terminal snapshots, approval prompts, cost, latency, and errors
- Local eval datasets and model comparison runs with cost, latency, failures, selected answers, and baseline deltas
- global model management with key audit, allowed/forbidden states, enriched model labels, and detailed model hero cards
- model quality scorecards with eval, trace, usage, registry, latency, cost, and confidence data
- eval-on-change gates for model registry, gateway policy, prompt template, and run profile changes
- human review queue for failed gates, high-cost runs, routing uncertainty, and manual flags
- trace and saved-chat replay with target model selection, diffs, cost, latency, and routing comparisons
- conversation branching from saved chat messages with sibling comparison, branch notes, and eval promotion
- saved model comparison reports with Markdown, CSV, and JSON export
- local RAG document workspace for opt-in chat, eval, comparison, and Claude Code prompt grounding
- Claude Code permission simulator for launch-time tool, command, and path risk preview
- local session resource monitoring for CPU, memory, process age, child processes, idle time, and disk/artifact warnings
- one-click AgentBoard session snapshots with traces, audit records, tmux excerpts, costs, resource metrics, and config fingerprints
- config drift detection for registry, gateway policy, console config, Dedicated, budgets, quotas, auth/session state, and role-token policy summaries
- rollback wizard for runtime-state archive discovery, impact preview, pre-rollback backups, restore, audit, and post-rollback checks
- release candidate dashboard with tests, coverage, smoke, drift, reviews, operator-needed items, recent failures, and report snapshots
- local automation rules for eval failures, budgets, provider health, Dedicated events, release failures, review creation, and signed webhooks
- notification center for review, provider, release, eval, automation, Dedicated, cost, quota, and security events
- offline/degraded mode with cached Serverless catalogs, local registry/eval workflows, cache age, and live-cloud action guards
- workspace bundle export/import for profiles, templates, eval datasets, reports, model registry snapshots, and gateway policy with redaction and dry-run validation
- provider health dashboard for DigitalOcean status, account, model access, proxy sync, Dedicated readiness, and local telemetry
- model access drift alerts for allowed-to-forbidden, rate-limited, probe-failed, removed, and restored Serverless models
- Serverless and Dedicated Inference lifecycle controls with build, health, budget, idle teardown, and fallback routing feedback

Create workspace behavior is documented in `docs/create-experience.md`. V2 Run workspace behavior is documented in `docs/run-experience.md`. The unified model identity card and favorites behavior are documented in `docs/unified-model-card.md`; rich model detail content is documented in `docs/model-hero-cards.md`.

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
./matts-v2-console.py --build-frontend
```

The launcher requires an MDE LLM-PROXY model access key. Write it to:

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

Non-loopback proxy binds fail closed unless you set `MATTS_PROXY_AUTH_TOKEN` or pass `--inbound-auth-token`. Remote clients must send that value in `x-matts-proxy-token` or `Authorization: Bearer ...`. An explicit `--allow-unauthenticated-remote` / `MATTS_PROXY_ALLOW_UNAUTHENTICATED_REMOTE=1` override exists only for trusted, isolated networks.

Console runtime defaults are stored in:

```text
config/console.json
```

Use `MATTS_CONSOLE_CONFIG_FILE=/path/to/console.json` to point at another JSON config. Environment variables such as `MATTS_STUDIO_PORT`, `MATTS_VALUE_SET_PROXY_PORT`, `MATTS_MODEL_AUTO_ENABLE_MAX_USD`, and `MATTS_CONSOLE_LOG_LEVEL` still override the file. The `paths` section controls template, default model registry, active model registry, Dedicated, Serverless cache, tmux registry, wallpaper, usage, budget, and log locations; existing path-specific environment variables still take precedence. Model pricing comes from the configured model registry data. Secrets and tokens remain file/env based and are not stored in this config.

The active model registry is `config/models.json`. `./claude-DO.sh --list-models`, the proxy `/v1/models` endpoint, Code/Create selectors, model hero cards, and the Advanced Models tab all derive from that registry. Serverless catalog refresh can add new DigitalOcean-hosted models, and models priced below the configured auto-enable threshold are enabled by registry policy. Key-specific access audit results are runtime state under `$HOME/.cache/matts-value-set/studio/model-access-state.json` and are merged into UI/proxy reads without being committed to the registry.

Run the backend/CLI key audit to probe Serverless text models with a tiny request. The result marks models as allowed, forbidden, rate-limited, or probe-failed in runtime state, surfaces as access-state on the Advanced Models tab, syncs the proxy, and prevents Code/Create from showing stale selectable models. Chat message `Show Detail` exposes requested model, routed model, backend, trace ID, usage, cost, upstream ID, and fallback/routing reason. `Model Info` opens the richer model profile.

Console auth supports the generated owner token, optional scoped role tokens, and short-lived JWT sessions with rotating refresh tokens. Sensitive model, Dedicated, budget, billing, tmux, terminal, and auth-session actions are permission-checked and written to `$HOME/.cache/matts-value-set/studio/audit.jsonl`. Role-token and session setup is documented in `SECURITY.md`.

Dedicated Inference live state is runtime data. The default state file is under the console app cache, and `config/dedicated-inference.example.json` is the publishable template. Do not commit live Dedicated endpoint metadata, access tokens, CA certificates, or raw DigitalOcean resource payloads.

Release config and runtime state are intentionally separate:

| Area | Release-owned file | Runtime-owned default |
| --- | --- | --- |
| Console defaults | `config/console.json` | `MATTS_CONSOLE_CONFIG_FILE` override when needed |
| Default model bootstrap | `config/default-models.json` | Active registry below |
| Active model registry | `config/models.json` | Operator-edited source of truth; schema_version `1` |
| Model access audit state | none | `$HOME/.cache/matts-value-set/studio/model-access-state.json` |
| Dedicated Inference | `config/dedicated-inference.example.json` | `$HOME/.cache/matts-value-set/studio/dedicated-inference.json` |
| Serverless catalog cache | none | `$HOME/.cache/matts-value-set/studio/serverless-model-catalog.json` |
| Model access drift | none | `$HOME/.cache/matts-value-set/studio/model-access-drift.json` |
| Model deprecations | none | `$HOME/.cache/matts-value-set/studio/model-deprecations.json` |
| Audit log | none | `$HOME/.cache/matts-value-set/studio/audit.jsonl` |
| Auth sessions | none | `$HOME/.cache/matts-value-set/studio/auth-sessions.json` |
| Automation rules and executions | none | `$HOME/.cache/matts-value-set/studio/automation-rules.json`, `$HOME/.cache/matts-value-set/studio/automation-executions.jsonl` |
| Cost anomaly decisions | none | `$HOME/.cache/matts-value-set/studio/cost-anomalies.json` |
| Policy bundles and history | none | `$HOME/.cache/matts-value-set/studio/policies.json`, `$HOME/.cache/matts-value-set/studio/policy-history.jsonl` |
| Synthetic load runs | none | `$HOME/.cache/matts-value-set/studio/synthetic-load-runs.jsonl` |
| Notification state | none | `$HOME/.cache/matts-value-set/studio/notifications.json` |
| Workspace bundles | none | `$HOME/.cache/matts-value-set/studio/workspace-bundles/` |
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

Console API rate limits are configured in `config/console.json` under `rate_limits`. Limits are keyed by console token fingerprint when a token is present, otherwise by actor/client identity. API responses include `x-ratelimit-limit`, `x-ratelimit-remaining`, and `x-ratelimit-reset`; blocked requests return `429` with `retry-after`.

Daily and monthly quota planning is configured under `rate_limits.quotas`. It can warn or block by actor role, action, model, project, request count, and estimated USD before provider work starts; details are in `docs/quota-planner.md`.

Context window inspection is available through `POST /api/v1/context-window` and in the Chat/Create, Claude Code, and Eval Runner UI. It estimates prompt tokens, remaining model context, and truncation risk from registry metadata; accuracy limits are documented in `docs/context-window-inspector.md`.

Streaming response metrics are recorded in traces and shown in chat diagnostics when available. See `docs/streaming-metrics.md` for route health, buffered fallback, and tokens/sec semantics.

Local retrieval grounding is configured by document collections and enabled per request. The console can index selected Markdown, text, JSON, and source files locally, add cited snippets to chat/eval/comparison/Claude Code prompts, and show retrieval metadata in response details. See `docs/local-rag.md`.

Claude Code launch permissions can be previewed with `POST /api/v1/tmux/permissions` and in the session wizard. The simulator flags risky tool/path combinations, suggests safer presets, and records the server-side summary with tmux launch metadata. See `docs/permission-simulator.md`.

Live tmux sessions include local resource summaries in the session drawer and AgentBoard. Metrics use tmux pane PIDs, `ps`, and workspace disk stats while avoiding process command arguments. See `docs/session-resources.md`.

AgentBoard can write local session snapshots as JSON and Markdown under runtime cache paths. Snapshots include redacted session, trace, audit, tmux, cost, resource, and config-fingerprint context. See `docs/session-snapshots.md`.

Authenticated clients can mint JWT sessions with `POST /api/v1/auth/session`, refresh them with `POST /api/v1/auth/refresh`, inspect active sessions with `GET /api/v1/auth/sessions`, and revoke with `POST /api/v1/auth/revoke`.

Console plugins are manifest based and discovered from `plugins.directories` in `config/console.json`. `GET /api/v1/plugins` reports enabled, disabled, and invalid plugin manifests plus supported extension points. The manifest contract is documented in `docs/plugins.md`.

Theme defaults are configured in `config/console.json` under `theme`. The UI uses CSS variables, honors `prefers-color-scheme` when `theme.default` is `system`, and persists manual Light/Dark choices in localStorage.

The Console Analytics tab aggregates recent traces and local usage into request, error, latency, model, daily cost, and CSV export views. It is backed by `GET /api/v1/analytics?days=7`.

Run the local unit/smoke test suite with the standard library runner:

```bash
python3 -m unittest discover -s tests -v
```

For documentation-only changes, at minimum run:

```bash
git diff --check -- README.md MAIN-WORKLIST.md
```

Before committing or publishing a release, run the repeatable local release check:

```bash
MATTS_BROWSER_SMOKE_REQUIRED=1 ./scripts/release-check.sh
```

It runs the unit/smoke suite, coverage report, Python syntax checks, V2 OpenAPI/client drift checks, a React frontend build, a V2 frontend bundle-boundary check, a production frontend dependency audit with `npm audit --omit=dev`, and a headless browser smoke check when Playwright is installed. GitHub Actions installs Playwright and requires the browser smoke pass for Code, Create, Console, and terminal page navigation.

The v2 console is launched with `matts-v2-console.py`. It builds the React frontend when needed, starts the FastAPI app, serves the built React assets from `frontend/dist`, and exposes the generated `/v2/*` API surface. The release check also validates generated OpenAPI/client freshness and runs the V2 Playwright smoke including the standing Console TUI bridge.

The full-screen terminal uses one WebSocket connection per browser attachment and one temporary `tmux attach-session` PTY child per connection. The bridge clamps resize messages, handles WebSocket ping/pong control frames, logs connect/disconnect reasons, and tears down the attach child on close. Connection pooling is intentionally not used because tmux is already the persistent layer; pooling browser PTYs would make stale socket state harder to reason about without improving session durability.

Release, upgrade, rollback, runtime-state backup, and post-upgrade health validation are documented in `RELEASE.md`.

To run the browser smoke locally:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
MATTS_BROWSER_SMOKE_REQUIRED=1 python3 scripts/v2-browser-smoke.py --required
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

The V2 console includes AgentBoard-inspired tmux/session views. It discovers managed local tmux sessions, captures pane previews, infers whether sessions are working, waiting, or asking for permission, and exposes controls to open, send input, send common keys, or stop a selected session. The task, eval, and leaderboard views are derived from tmux pane state plus local proxy usage logs; no separate AgentBoard service or database is required.

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
