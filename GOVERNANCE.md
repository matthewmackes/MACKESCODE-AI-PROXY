# Governance And Architectural Locks

This repository is a private-operator Claude Code launcher, Anthropic-compatible
local proxy, and web console for DigitalOcean-hosted LLMs. This file is the
project rulebook for architecture, safety, release discipline, and AI-assisted
work. When this file conflicts with older prose elsewhere, the newer explicit
lock here wins. Product decisions that reopen a lock must be recorded in
`docs/DECISIONS.md`.

## Master Rule

Keep the platform private-operator safe, observable, and reversible. The system
may automate expensive cloud actions, route source code and prompts through LLMs,
and expose local terminals through a browser; every change must make those
operations clearer, safer, or more reliable.

## Source Of Truth

- `config/models.json` is the active source of truth for model ids, aliases,
  enabled state, access status, pricing, origin, metadata, and Dedicated
  Inference routing state.
- `config/default-models.json` is bootstrap fallback data only.
- Code, Create, Console selectors, `/v1/models`, model hero cards, key audit,
  and proxy sync must all derive from the same registry.
- Runtime state belongs under `$HOME/.cache/matts-value-set/` or an explicit
  operator-provided path. Do not commit live cloud identifiers, endpoint
  credentials, auth/session tokens, trace logs, usage logs, wallpaper cache
  files, tmux registries, or generated images.

## Security And Secrets

- The proxy binds to `127.0.0.1` by default. Any broader exposure must keep
  token authentication and scoped roles enabled.
- Tokens and secrets never belong in committed config, command examples, traces,
  screenshots, or worklist notes. Prefer file/env lookup and redacted display.
- Dedicated Inference public/private endpoint FQDNs, access tokens, CA
  certificates, VPC UUIDs, inference ids, raw DigitalOcean payloads, billing
  account details, and model-access audit results are sensitive operational
  metadata.
- Console owner/scoped tokens, JWT sessions, role-token files, audit logs, and
  tmux terminal writes are security surfaces. Changes touching them require
  tests and `SECURITY.md` review.
- Trace records are operational metadata, not transcripts. Default traces must
  not store full prompts or assistant responses. See
  `docs/trace-redaction-policy.md`.

## Routing And Cost Safety

- Every routed chat/proxy/Dedicated/image action should emit traceable routing
  proof: requested model, routed model, provider, endpoint mode, reason/fallback,
  latency, token/cost metadata, and error category when available.
- Dedicated Inference is preferred only when a configured server is online and
  healthy. If no server is online, UI and proxy feedback must offer the operator
  a clear build or fallback path.
- Dedicated servers are cost-bearing cloud resources. Build, rebuild, policy
  override, idle extension, teardown, billing, and model-registry actions must be
  permission checked and audit logged.
- Idle warning, idle teardown, unhealthy teardown, and budget-guard behavior
  must not depend solely on a browser page staying open.
- Cost displays must distinguish DigitalOcean month-to-date total, last-24-hour
  total, and month-to-date Dedicated server cost when data is available.

## Interface Rules

- The web console is an operations tool, not a marketing site. Console surfaces
  should be dense, predictable, Carbon-inspired, and built for repeated use.
- Create should remain wallpaper-forward and conversational: floating chat,
  visible routing detail, graceful weather/wallpaper fallback, and no opaque
  panels that block the intended background experience.
- Code should keep the terminal workflow direct: session chooser, model/session
  setup wizard, clear state, and stable paste/shortcut controls.
- Dark mode, tab navigation, and global status/cost controls must work across
  Code, Create, and Console, not just inside one tab.
- UI changes are not complete until they are exercised with browser smoke or
  equivalent rendered-state evidence.

## Definition Of Done

A change is done only when it is runtime-reachable and observably works.

- No dead UI controls, decorative-only workflows, stale mockups, placeholder
  routes, or "documented but not wired" features.
- No broad claims of completion without evidence matched to the requirement
  scope.
- Tests should scale with risk: unit tests for services and policy, API tests
  for routing/security/cost behavior, and browser smoke for UI workflow changes.
- Documentation must be updated when behavior, operator workflows, security
  posture, release process, or runtime-state boundaries change.
- Release candidates must pass `scripts/release-check.sh`; strict local/CI runs
  should set `MATTS_BROWSER_SMOKE_REQUIRED=1`.

## Work Tracking

- `MAIN-WORKLIST.md` is the main task ledger.
- `docs/requirements-ledger.md` preserves product decisions from surveys and
  long-running conversations.
- `docs/DECISIONS.md` records changes to governance locks and durable
  architecture decisions.
- `docs/NEEDS-OPERATOR.md` records work that cannot be closed by code alone
  because it needs a live cloud resource, account permission, token, billing
  condition, GitHub decision, or explicit operator choice.
- `docs/COMPLIANCE.md` records integrity sweeps. Findings should be framed as
  FINISH, REMOVE, or ACCEPTED with evidence.

## Import Note

This governance model was adapted from the `magic-mesh` rulebook. The portable
parts are architectural locks, definition of done, operator-needed tracking,
decision logging, threat modeling, compliance sweeps, and GUI polish discipline.
`magic-mesh`-specific locks for Nebula, egui/DRM, Rust crates, Fedora images,
and build-farm topology do not apply to this project.
