# Requirements Ledger

**Purpose:** Durable product decisions extracted from the completed worklist and interface surveys.

**Last updated:** 2026-07-09

This ledger keeps survey decisions executable after chat compaction. It is not a transcript. Each item is mapped to an owning worklist task and uses one of these evidence levels:

- `Confirmed`: explicitly preserved in `MAIN-WORKLIST.md`, specs, or implemented UI behavior.
- `Inferred`: strongly implied by preserved decisions, but still needs verification during implementation.
- `Needs confirmation`: the original survey answer is not reconstructable from local project state.

## Create Experience

| Decision | Evidence | Owner |
| --- | --- | --- |
| Create should prioritize atmosphere first, conversational presence second, and creative workflow third. | Confirmed | `INT-014` |
| Text and Image should be sibling experiences under one Bing-like Create surface, not separate admin-style pages. | Confirmed | `INT-014` |
| Chat bubbles should float over the scenic wallpaper instead of blocking it with an opaque conversation panel. | Confirmed | `INT-014` |
| Desktop should include subtle always-on atmosphere: particles/light motes, cursor-reactive light, and time/weather mood. | Confirmed | `INT-014` |
| Mobile should preserve the wallpaper but disable heavy atmospheric effects. | Confirmed | `INT-014` |
| Assistant replies should reveal progressively for new answers, support click-to-skip, and persist only final text in history. | Confirmed | `INT-014` |
| Waiting state should show selected model identity, routing stage, elapsed time, and compact routing-change notices. | Confirmed | `INT-014`, `INT-020` |
| Text comparison should support up to five models in the same conversation, with strict unavailable-model handling, cost/latency detail, and one saved comparison history entry. | Confirmed | `INT-014`, `INT-021` |
| Weather should degrade gracefully when geolocation or weather data is unavailable. | Confirmed | `INT-014` |
| Wallpaper should use remote/cache metadata with attribution, not bundled copyrighted wallpaper assets. | Confirmed | `INT-014`, `INT-018` |

## Code Experience

| Decision | Evidence | Owner |
| --- | --- | --- |
| Code should use a wizard-like process for standing up tmux sessions with model, session, profile, run mode, prompt, and review choices. | Confirmed | `INT-016`, `INT-007` |
| The session chooser and model chooser share top-screen horizontal space; details should be rich but compact. | Confirmed | `INT-016`, `INT-014` |
| New sessions should be highlighted at the top with a sparkle treatment. | Confirmed | `INT-016` |
| Session display names should be editable inline, while tmux identifiers remain stable. | Confirmed | `INT-016` |
| Generated session names should include `STARTTIME_`. | Confirmed | `INT-016` |
| Previous sessions should remain visible as read-only entries with red text/status treatment. | Confirmed | `INT-016` |
| Removed older Code controls should stay removed after the wizard replaces them. | Confirmed | `INT-014`, `INT-024` |

## Console And Operations

| Decision | Evidence | Owner |
| --- | --- | --- |
| Console should be organized into distinct operational areas: Accounting & Time, Inference Hosting Lifecycle, LLM Management, AgentBoard, and System Operations. | Confirmed | `INT-014`, `INT-016` |
| Console should use Carbon-inspired dense operational styling rather than marketing-page styling. | Confirmed | `INT-014`, `INT-012` |
| Console content must not bleed under Code/Create and must load pinned to the top. | Confirmed | `INT-014`, `INT-005` |
| Header ordering should keep primary tabs centered and operational controls on the right: Dark Mode, Status, Cost, Console icon. | Confirmed | `INT-014`, `INT-012` |
| Dark mode must apply globally, not just to forms or Console. | Confirmed | `INT-012` |

## Model Management

| Decision | Evidence | Owner |
| --- | --- | --- |
| `config/models.json` is the private-operator source of truth for model availability, metadata, access state, pricing, and enabled policy. | Confirmed | `INT-015`, `INT-018` |
| Serverless catalog sync should add all DigitalOcean models, retain removed models as unavailable records, and avoid routing disabled or forbidden models. | Confirmed | `INT-015` |
| Newly discovered low-cost models should be auto-enabled only when every known price is below `$0.45` per 1M/unit and access probes pass. | Confirmed | `INT-015` |
| Model labels should include human-readable cost, training-origin country, brand/provider identity, access state, and use-case/comparison context. | Confirmed | `INT-015`, `INT-017` |
| New models should receive a seven-day global sparkle treatment and generated style fallback when no curated provider style exists. | Confirmed | `INT-014`, `INT-015`, `INT-017` |
| Each chat message should expose a Show Detail view with requested model, routed model, fallback reason, provider, endpoint mode, trace ID, cost, and latency where available. | Confirmed | `INT-015`, `INT-020` |
| Model access key verification should be automatable and should record allowed/forbidden model status back into the registry. | Confirmed | `INT-015`, `INT-019` |

## Dedicated Inference And Cost Controls

| Decision | Evidence | Owner |
| --- | --- | --- |
| Dedicated should be preferred only when a built server is online; otherwise the UI should offer a Build Server action. | Confirmed | `INT-016`, `INT-022` |
| Dedicated servers should be destroyed when not in use, with idle warning after five minutes and teardown after ten minutes. | Confirmed | `INT-016` |
| Idle reset should count only successful Dedicated model work. | Confirmed | `INT-016`, `INT-020` |
| Dedicated uptime and estimated cost should be visible globally while a server is online. | Confirmed | `INT-016` |
| Cost displays should distinguish DigitalOcean month-to-date total, last-24-hour total, and month-to-date Dedicated server cost. | Confirmed | `INT-016`, `INT-020` |
| Dedicated lifecycle feedback should be human-friendly, with raw diagnostics behind details. | Confirmed | `INT-016`, `INT-020` |
| DigitalOcean account status, prepay/balance status, platform uptime, incidents, and token scope status should be surfaced in lifecycle panels when available. | Confirmed | `INT-016`, `INT-019` |
| Budget-critical Dedicated builds should be blocked by default but overridable by the current console-token operator, with full audit context. | Confirmed | `INT-016`, `INT-023` |
| Budget-blocked Dedicated routing should fall back to Serverless with a visible pre-reply notice and trace reason `budget_blocked_fallback`. | Confirmed | `INT-016`, `INT-022` |

## Observability, Evals, And Gateway Policy

| Decision | Evidence | Owner |
| --- | --- | --- |
| Trace-first observability is a prerequisite for enterprise reliability, evals, cost governance, and user-visible routing proof. | Confirmed | `INT-020` |
| Every routed chat/proxy/Dedicated/image action should emit a trace with model, provider, endpoint mode, fallback, latency, token, cost, and error category details. | Confirmed | `INT-020` |
| Evals should compare selected models/prompts with cost, latency, failures, human notes, and exportable history before model registry changes become defaults. | Confirmed | `INT-021` |
| Gateway policy should cover failover, circuit breakers, rate limits, quotas, cache controls, budget-aware routing, and trace-visible decisions. | Confirmed | `INT-022` |

## Follow-Up Survey Reconciliation

The latest follow-up survey sequence was mostly preserved as answer choices without the original prompts. The following decisions are durable because they can be reconstructed from worklist entries, implemented behavior, or explicit user requests around the answer sequence.

| Decision | Evidence | Owner |
| --- | --- | --- |
| Disabled managed Dedicated models should stay visible in selectors and expose a guarded Build Again path with estimated hourly cost confirmation. | Confirmed | `INT-016` |
| Build Again should respect the daily Dedicated budget guard, but a console-token operator may explicitly override after a second confirmation. | Confirmed | `INT-016`, `INT-023` |
| Dedicated lifecycle warnings must be global, not Console-only, so idle, unhealthy, and budget countdowns are visible across Code, Create, and Console. | Confirmed | `INT-016`, `INT-020` |
| Follow-up answer-only choices should not be copied into implementation tasks unless the original product decision can be reconstructed from durable project state. | Confirmed | `INT-026` |
| Remaining enterprise-class work should proceed through traceability, gateway policy, eval/comparison, Create completion, documentation, and release packaging in that order. | Confirmed | `INT-020`, `INT-022`, `INT-021`, `INT-014`, `INT-019`, `INT-024` |

## Release Readiness

| Decision | Evidence | Owner |
| --- | --- | --- |
| The project should be publishable from a clean checkout without leaking local runtime state, live cloud identifiers, tokens, or endpoint credentials. | Confirmed | `INT-018`, `INT-024` |
| Release docs should match current behavior for model registry, Serverless, Dedicated, billing, token scopes, and quickstart commands. | Confirmed | `INT-019`, `INT-024` |
| Release gates should include unit tests, syntax checks, coverage, JavaScript checks, and headless browser smoke. | Confirmed | `INT-005`, `INT-024` |
| Upgrade and rollback must preserve registry, chats, usage logs, tmux sessions, and Dedicated lifecycle state without orphaning cloud resources. | Confirmed | `INT-024` |

## Open Confirmations

These items were requested through survey flow, but the specific answer content cannot be reconstructed with enough confidence from local files alone.

| Item | Why it needs confirmation | Suggested owner |
| --- | --- | --- |
| Exact 100-question answer mapping by question number. | Chat compaction preserved many selected options but not all original question prompts. | `INT-025` follow-up note only; do not block implementation. |
| Latest follow-up answer-only sequence ending with "add to worklist". | Reconciled on 2026-07-08. Reconstructable decisions were promoted above; any remaining raw answer choices lack their prompts and should stay unreconstructable until the user restates the product decision. | `INT-026` |
| Additional post-reconciliation "add to worklist" confirmation. | User repeated the instruction after another answer-only continuation. Treat it as confirmation to preserve backlog hygiene, not as permission to guess missing survey prompts. | `INT-026` |
| 2026-07-09 answer-only continuation ending with "add to worklist". | User requested worklist preservation after another answer sequence, but the compacted context does not preserve enough prompt text to promote each answer safely. Reconcile only reconstructable decisions during the next ledger pass. | `INT-026` |
| Latest 2026-07-09 "add to worklist" request after an answer-only continuation. | The instruction is durable, but the underlying question prompt is not recoverable from project files. Preserve it as backlog hygiene and wait for an explicit product decision before adding implementation criteria. | `INT-026` |
| Preferred weather provider and whether browser geolocation may be stored as a default. | Requirements say geolocation first and graceful fallback, but provider/privacy preference is not durable. | `INT-014`, `INT-018` |
| Exact default Code wizard profile ordering and permission defaults beyond the current local implementation. | Preserved answers confirm wizard behavior, but not all profile policy details. | `INT-007`, `INT-023` |
| Final public release name/versioning policy. | GitHub repository name is known; semantic version and release cadence are not. | `INT-024` |

## Priority Order

Completed prerequisites: `INT-001`, `INT-002`, `INT-003`, `INT-004`, `INT-005`, `INT-006`, `INT-015`, `INT-016`, `INT-018`, `INT-020`, `INT-021`, `INT-022`, `INT-025`, and `INT-026`.

1. `INT-014` finish the remaining Create/Image visual workflow gaps.
2. `INT-017` complete detailed model hero cards.
3. `INT-019` reconcile documentation.
4. `INT-024` finish packaging, upgrade, rollback, and release checklist.
5. `INT-023` add governance, RBAC, and audit hardening.
