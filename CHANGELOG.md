# Changelog

## Unreleased

- Promoted dark mode from the Chat-scoped toggle to a global, persisted console
  theme: shell-chrome toggle with `prefers-color-scheme` default, pre-paint boot
  theming, tokenized dark surfaces across all six workspaces, a dark Ant Design
  algorithm for Advanced Console/Run/Observe/Operate, and dark-visible Carbon
  icons. The old chat-only toggle drove shared CSS but was deleted on leaving
  Chat; both toggles now drive one persistent theme.
- Converted hardcoded light-surface colors in the V2 stylesheet to shared theme
  tokens (new `--cds-chrome`, `--cds-layer-accent`, `--cds-layer-danger`,
  `--cds-link-strong`), keeping light mode pixel-stable while dark mode inherits
  automatically; Create's over-wallpaper glass panels intentionally keep their
  glass look in both themes.
- Made webfont loading non-render-blocking: the Google Fonts CSS `@import`
  moved to async preconnect/preload links in `index.html`, so offline or
  egress-restricted networks fall back to system fonts without stalling first
  paint.
- Surfaced silent mutation failures as visible alerts across Advanced Run
  (template/profile save, activate, eval-gate preview, rollback, record, branch,
  snapshot), Console (take/release control, tmux capture/send/key/rename/stop,
  code-session actions), and Operate (template seeding); Operate no longer fires
  a template-seed write just from viewing the page, and invalid template values
  JSON now reports a friendly message instead of a raw SyntaxError.
- Replaced always-visible raw JSON dumps in Observe, Operate, and Run with
  human-readable summaries plus consistent "Raw payload" disclosures; chat
  responses without readable text render a diagnostic message instead of a
  stringified object; Observe gates its initial load and reports "not
  configured"/"n/a" instead of optimistic "ready" and substituted counts.
- Readability, accessibility, and consistency polish: human-readable model
  access statuses on Models spotlight/showcase, denser Code/Research/Advanced
  headers, larger chat answer text, "n/a" guards for missing timestamps,
  labeled icon-only controls with Carbon close icons replacing literal "x"
  glyphs, reduced-motion coverage for skeleton and cost-pulse animations,
  offline styling for the cost pill, routable-only Create image model choices,
  and brand SVG artwork moved to a lazy chunk to keep the first-load shell
  within its budget.

## 2.2.0 — Branding, voice, navigation, and cost guardrails (2026-07-12)

- Added canonical MDE / LLM-PROXY branding, app icon assets, manifest metadata,
  and shell branding across the V2 console.
- Added platform speech support with Qwen3 TTS service plumbing, browser
  fallback behavior, Firefox/Chromium/Safari voice-chat support, and global
  voice controls in the floating toolbar.
- Replaced the persistent V2 side rail with hamburger drawer navigation while
  preserving workspace routing, quick switcher, settings, sign-in, and startup
  What's New behavior.
- Moved below-navigation summary content into Advanced > Overview and kept
  Console, Run, Observe, and Operate as Advanced tabs.
- Added V2 cost burn-rate controls with minute/day/month visibility, Dedicated
  vs LLM-as-a-service breakdowns, monthly thresholds, hard-pause enforcement,
  authorized overrides, and Operate payment-review checklist.
- Improved Chat dark mode, typography, and GUI polish guidance, including the
  project `world-class-gui-polish` skill.

## 2.1.0 — Research dossiers, onboarding templates, and UI polish (2026-07-12)

- Added model-scoped onboarding prompt templates so new chat sessions can start
  with prepared, formatted content suited to each model family.
- Refined Chat diagnostics and response presentation so malformed, empty, or
  tool-call-shaped upstream failures are surfaced as useful operator evidence.
- Expanded the V2 Research workflow with dossier, pinning, and report packet
  surfaces for richer source review.
- Restyled Chat and Research into more distinctive ICQ/Carbon and legal research
  inspired workspaces while preserving the V2 console navigation model.
- Fixed model artwork rendering so tracked logo, brand, and background sources
  display as artwork instead of plain URL references.
- Hardened browser smoke coverage for the polished V2 console surfaces.

## 2.0.0 — Release RPM and Chat permission fix (2026-07-11)

- Fixed V2 Chat RBAC so view-only users can load the Chat workspace while model
  execution still requires `model_use`.
- Added a dismissible sign-in escalation flow for Chat model-use permission.
- Added a repeatable RPM build script that vendors pure-Python runtime
  dependencies and rejects native `.so` extensions to keep the package `noarch`.
- Updated systemd units to import the packaged vendor runtime and refreshed RPM
  metadata for the public release.
- Closed the Operate operator-handoff ledger for the v2.0.0 release policy,
  packaging acceptance, brand decision, and retired survey-answer work.

## Unreleased — Platform review hardening (2026-07-11)

Security and reliability fixes from the comprehensive architecture/UX review
(see `docs/PLATFORM-REVIEW-2026-07-11.md`):

- Model registry (`config/models.json`) is now written atomically (temp file +
  fsync + `os.replace`) under a process lock, so a concurrent write can no
  longer produce a torn file that resets the governance-locked source of truth
  to bundled defaults.
- Dedicated Inference idle/unhealthy teardown and state advancement no longer
  depend on a browser polling the status endpoint: the 30s background worker now
  refreshes live DigitalOcean state and applies policy headlessly (`reconcile`).
- Dedicated budget guard now reconstructs billing intervals from structured state
  transitions (not human-readable event copy) and tears down an over-budget active
  server in the headless policy path, audit-logged with the numeric budget state.
- Dedicated keep-alive can only ever extend the idle-teardown deadline, never
  shorten it.
- Dedicated status payloads and lifecycle events now redact access tokens,
  endpoint FQDNs, inference ids, VPC UUIDs, CA certs, and raw DigitalOcean
  payloads, exposing `*_configured` booleans instead of the secret values.
- tmux attach/capture/send/stop are scoped to console-managed (`matts-`) sessions,
  and AgentBoard no longer surfaces screen previews of foreign host tmux sessions.
- Proxy budget check on `/v1/messages` no longer re-parses the entire usage log
  per request (incremental in-memory aggregator); `tail_jsonl` reads only the tail.
- `/api/cost-summary` and `/api/analytics` cache the live DigitalOcean billing
  call (TTL) and share a single usage-log parse instead of re-reading per request.
- Serverless catalog sync and Dedicated `register_model` no longer rewrite the
  model registry on every status poll when nothing changed; fixed a bug where a
  catalog model's `auto_managed` flag flipped on every sync (non-idempotent entry).
- Console template rendering escapes JSON interpolated into `<script>` blocks, so
  model metadata containing `</script>` can no longer break out (stored XSS).
- The wallpaper image proxy enforces a host allowlist, https-only, internal-IP
  blocking, redirect suppression with final-URL re-validation, and a response
  size cap + timeout (SSRF/DoS hardening).
- Added proxy message-translation tests (OpenAI↔Anthropic text/tool_use/budget)
  and HTTP-level authorization-enforcement tests.
- The proxy's bare `--port` default is now `18081` (was `18080`), matching the
  launcher, console, and `config/console.json` so running the proxy directly
  binds the port the rest of the system expects.
- The proxy now truly streams: `stream:true` requests forward upstream tokens
  incrementally (real time-to-first-byte) instead of buffering the whole
  response and replaying it as one SSE burst. Non-streaming requests, with their
  context-retry and serverless failover, are unchanged.
- Removed dead `gateway-policy.json` keys that were advertised via
  `/v1/claude-do/gateway-policy` but never honored (failover max-attempts /
  preference / reason-codes, retries enable/max/backoff, and the budget toggles);
  `retries.retry_statuses` is retained (it drives failover triggering).
- Added an audit of the pre-existing worklist COMPLETED claims
  (`docs/worklist-audit-2026-07-11.md`): 12 confirmed, 2 partial, 0 unsubstantiated.
- V1-only UI remediations from the source worktree were not ported because
  ADR-0003 makes the V2 React console the current product surface.
- Registry writes are now centrally non-churning: `ModelRegistryService.save()`
  skips the write when the on-disk content already matches.
- V2 TMux attach now has a native `/ws/tmux` FastAPI bridge, so browser
  attachments no longer fall through the React static mount and immediately
  detach.
- Browser TMux/TUI terminals now use an explicit ANSI color palette and attach
  tmux clients with 256-color/RGB features, preserving Claude Code color output
  for sessions such as `MDEBUILD`.
- Proxy `/v1/images/generations` now enforces the budget guard and the model
  allowlist, matching the chat path; over-budget or unconfigured-model image
  requests are rejected instead of silently spending or forwarding arbitrary
  models upstream.
- Proxy request handlers no longer crash the request thread on malformed client
  JSON, a malformed upstream 200 response, or a missing token file; unhandled
  errors now return a logged `502` (or nothing extra once a stream has started).
- Console authorization now gates cost-bearing (`/api/chat`, `/api/chat/compare`,
  `/api/generate`) and live-terminal-read (`/api/tmux/capture`,
  `/api/terminal/read`) routes on `model_use`/`tmux_control`, and permission-checks
  state-mutating GET routes (`/api/models/serverless-catalog`). A view-only token
  can no longer spend budget or read terminals.
- Launcher warns visibly when it defaults to `--dangerously-skip-permissions`
  (with `MATTS_REQUIRE_PERMISSION_PROMPTS=1` to refuse it) and refuses to launch
  Claude Code against a proxy that is not listening.
- Coverage reporting now measures the expanded shipped Python module set; the
  current V2 release gate keeps its real coverage floor at 40%.

## Current

- Removed the old whiptail launcher interface.
- Removed old `claude-pro`, `claude-flash`, and `claude-sonnet` wrappers.
- Added wrappers for the current text models: DeepSeek V4, GLM, Mistral, and Codex.
- Replaced stale Codex references with `openai-gpt-5.3-codex`.
- Simplified the proxy model list to the current MDE LLM-PROXY models.
- Removed catalog filtering, provider fallback, and upstream Anthropic model pass-through code.
- Added `./claude-DO.sh --test-models` to smoke-test all configured current models.
- Added the pure Python `image-studio.py` unified web console with embedded Claude Code, text model chat, image studio, history, budgets, costs, and logs.
- Added `matts-console.py` as the main Python entry point for the unified web interface.
- Made the unified console headless/public-facing by default with generated token authentication.
- Replaced the raw browser PTY with tmux-backed Claude Code sessions for continuity and a readable browser view.
- Added enterprise Claude Code launch controls: autonomy profiles, permission modes, tool boundaries, context directories, run modes, output formats, budget caps, safe mode, and bare mode.
- Added a Reporting page with local model usage plus optional DigitalOcean balance, billing history, and daily spend insights.
- Added a full-screen xterm.js terminal page connected to tmux over WebSocket for a real interactive Claude Code console.
- Added global model registry management, Serverless catalog import, model access key audit, and selector labels with cost, origin, access state, and use-case context.
- Added DigitalOcean Dedicated Inference lifecycle automation with preflight, build, status, access-token creation, budget guard, idle warning, auto-teardown, and Serverless fallback routing.
- Added per-message routing detail, trace search, gateway policy visibility, model comparison/eval workflows, and model hero cards.
- Separated release config from runtime state for Dedicated lifecycle data, Serverless cache, traces, usage, wallpaper cache, budgets, and tmux sessions.
- Removed default embedded model access key behavior; the launcher now requires a token file or explicit one-run override.
- Added `RELEASE.md`, runtime-state backup/restore tooling, and post-upgrade health validation.
- Converted `matts-image` from a shell helper to a Python CLI.

### Migration Notes

- Run `scripts/runtime-state.py backup` before upgrading hosts that have local chats, usage logs, tmux sessions, or Dedicated Inference state.
- Run `scripts/health-validate.py` after restarting the proxy and Console.
- Token files are not included in runtime-state backups unless `--include-secrets` is supplied.
