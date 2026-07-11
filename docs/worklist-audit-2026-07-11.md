# MAIN-WORKLIST COMPLETED-Claim Audit (2026-07-11)

**Finding:** PR-5.3 (Platform Review 2026-07-11) — *Audit MAIN-WORKLIST COMPLETED claims.*
**Auditor:** Claude (read-only code audit)
**Scope:** The pre-2026-07-11 "Current Interface Refactoring Work" section and the
`INT-*` task entries marked ✅ COMPLETED in `MAIN-WORKLIST.md`. The freshly-done
"Platform Review 2026-07-11 — Remediation Worklist" (`PR-*`) rows are out of scope
here — they are separately verified in the review pass.

## Method

For each significant COMPLETED claim I located the implementing code and, where
applicable, a test that exercises it, then assigned a verdict:

- **CONFIRMED** — runtime-reachable implementation exists and I can point at the
  code and/or a test that exercises it.
- **PARTIAL** — implemented but with a material gap between the claim's language
  and what the code actually does, or a checked criterion that is not
  reproducibly evidenced from the repo.
- **UNSUBSTANTIATED** — no code found backing the claim.

GOVERNANCE forbids completion claims without evidence, so "CONFIRMED" here means
I actually cite the code or test. No claim was rubber-stamped from its checkbox.

Line references are to the working tree at audit time and are indicative
(±a few lines as files change).

## Results

| Claim (task) | Status | Evidence (file:line / test) | Notes |
| --- | --- | --- | --- |
| Template extraction to `templates/` with a loader (INT-001) | CONFIRMED | `templates/{main,login,terminal}.html` exist; `src/console/handlers/template_handler.py:21` (`render`), `:29` (`_script_safe_json`); imported at `image-studio.py:29`; `tests/test_template_handler.py` | All three templates are filesystem-backed and served through `TemplateHandler`. |
| Monolith split into handler/service boundaries (INT-002) | CONFIRMED | `image-studio.py:25-34` imports 35 `src.console.*` handlers/services; `StudioHandler` (`image-studio.py:1603`) is the only remaining handler and delegates; former in-file functions are thin wrappers (`image-studio.py:390-394`, `:1053-1058`) | Extraction is genuinely wired, not just parallel modules. Caveat: `image-studio.py` is still ~1864 lines and residual `image-studio.py`/`src` duplication is acknowledged (tracked as PR-6.3); "thin orchestration" is *mostly* true, not fully. |
| Health/readiness/version/metrics endpoints (INT-006) | CONFIRMED | Route table `image-studio.py:1699-1707` (`/health`,`/ready`,`/version`,`/metrics`); `src/console/services/health.py`; `tests/test_health_service.py` | Prometheus text metrics + readiness composed in `ConsoleHealthService`. |
| WebSocket terminal polish: resize/ping-pong/cleanup (INT-007) | CONFIRMED | `src/console/services/websocket.py:41-93` (frame opcodes 8/9/10, `send_control`), `:95` (`set_pty_size` ioctl); `src/console/handlers/websocket_handler.py`; `tests/test_websocket_service.py:57` (ping/close), `tests/test_websocket_handler.py:117` (dimension clamp/fallback) | Ping/pong control frames, dimension clamps, and cleanup-reason tests all present. |
| API versioning `/api/v1/*` + deprecation/negotiation (INT-008) | CONFIRMED | `src/console/handlers/api_versioning.py:10,25,35,51` (header negotiation, v1 mapping, unsupported error); `tests/test_api_versioning.py` | Legacy `/api/*` still routes with deprecation semantics. |
| Console API rate limiting (INT-009) | CONFIRMED | `src/console/services/rate_limit.py`; `tests/test_rate_limit_service.py`; `tests/test_console_smoke.py:262` (429 + quota headers over HTTP) | Fixed-window, actor/token keyed, structured 429. |
| JWT/session auth with refresh + revoke (INT-010) | CONFIRMED | `src/console/services/auth_session.py:20-92` (HMAC-signed tokens, `create_session`, refresh jti, `revoked`); `tests/test_auth_session_service.py` | Std-lib HMAC JWT; sessions persisted and revocable. |
| Model registry as single source of truth + serverless catalog + `/v1/models?available` (INT-015) | CONFIRMED | `src/console/services/model_registry.py`, `serverless_catalog.py`; proxy filter `do-anthropic-proxy.py:1450` (`_models_payload`, `availability_filter`); `tests/test_proxy_registry_reload.py`, `test_serverless_catalog_service.py`, `test_model_registry.py` | Proxy reload + availability filtering + catalog sync all covered by tests. |
| Dedicated lifecycle: budget guard, idle teardown, keep-alive, unhealthy countdown, 30-day archive (INT-016) | CONFIRMED (code) / PARTIAL (live checkboxes) | `src/console/services/dedicated.py:269` (`budget_state`), `:306-340` (`effective_deadline`/keep-alive), `:345` (`unhealthy_policy_state`), `:173-208` (gzip archive); 15+ tests in `tests/test_dedicated_service.py` (idle, keep-alive, unhealthy, budget, archive, reconcile) | Feature code + tests are strong. But two checked criteria — "Live DO account/token/scopes verified against a real Dedicated build" and "endpoint request shape verified against the deployed model runtime" — rest on now-torn-down runtime state (build IDs in progress notes) and are not reproducible from the repo. Operator-evidence only. |
| Trace-first observability + redaction policy (INT-020) | CONFIRMED | `src/console/services/traces.py:18` (`summarize_messages`, privacy-safe preview), `:41` (`append`); `docs/trace-redaction-policy.md`; `/api/traces` at `src/console/handlers/api_handler.py:118`; `tests/test_trace_service.py` (+ chat trace tests) | Caveat: `TraceService.append` writes whatever record it is given — redaction (storing summaries, not full prompts) is enforced by *convention at each call site*, not centrally. Policy doc + summarizer exist, so the intent is realized, but there is no single choke-point guaranteeing no caller ever logs raw content. |
| AI gateway: failover, circuit breaker, cache, rate limits (INT-022) | CONFIRMED | `do-anthropic-proxy.py:1026` (rate-limit error), `:1076` (cache), `:1145` (circuit policy), `:1230-1247`/`:2100-2247` (serverless failover); `tests/test_proxy_registry_reload.py:252-417` (rate-limit, cache hit/expire, circuit open/clear, failover on/off) | All four criteria implemented and tested. Caveat: `config/gateway-policy.json` advertises a `budget` object and `retries.max_retries`/`backoff_seconds` that are never read (`do-anthropic-proxy.py:65-67` are the only occurrences). Dead advertised config — already tracked as PR-1.10. |
| Enterprise RBAC + audit logging (INT-023) | CONFIRMED | `src/console/handlers/auth_handler.py:7` (`ROLE_PERMISSIONS`), `:119` (`permission_for`), `:127` (`has_permission`); `src/console/services/audit.py:16` (`redact`), `:27` (`append`); `tests/test_auth_http_enforcement.py` (viewer→403 on sensitive routes, route-permission parity) | Scoped role tokens, permission-gated POSTs, secret-redacting JSONL audit. |
| Analytics dashboard + export (INT-013) | CONFIRMED | `src/console/services/analytics.py`; `/api/analytics` at `src/console/handlers/api_handler.py:86`; `tests/test_analytics_service.py:37` (aggregation + CSV) | Trace/usage aggregation, model table, CSV export. |
| Plugin system with lifecycle + third-party support (INT-011) | PARTIAL | `src/console/services/plugins.py:18` (docstring: "Load plugin manifests **without executing third-party code**"), `:76` (`plugins()` lists manifests only); example `plugins/example-console-panel.json`; `tests/test_plugin_service.py` | The delivered artifact is a manifest *catalog* surfaced at `/api/plugins`. Extension points are declared strings; nothing consumes them, and there is no load/activate/deactivate lifecycle or code execution. The narrower checkboxes (framework, extension points, example, docs, tests) pass, but the Description's "Plugin lifecycle management" and "Third-party plugin support" overstate what runs. |
| Comprehensive test suite / 80%+ coverage goal (INT-005) | PARTIAL | 40 test modules under `tests/`; `scripts/release-check.sh`; `scripts/coverage-report.py` | Infrastructure criteria (dir, runner, coverage report, CI, release gate, headless browser smoke) are all met and CONFIRMED. But the stated "80%+ code coverage" goal is not reached — measured coverage was 13% then floored at 45% (PR-0.9) and is ~55% (PR-3.1). Treat 80% as an unmet goal, not a delivered result. |

**Totals:** 14 claims audited — **12 CONFIRMED**, **2 PARTIAL**, **0 UNSUBSTANTIATED**.
(INT-016 is CONFIRMED for code/tests with a PARTIAL caveat on its two live-DO
verification checkboxes; counted as CONFIRMED above.)

## Re-open / evidence list (`FINISH` / `REMOVE` / `ACCEPTED` per `docs/COMPLIANCE.md`)

- **INT-011 Plugin system — FINISH or downgrade the claim.** The code is a
  read-only manifest registry, not a functioning plugin runtime. Either implement
  extension-point invocation/lifecycle, or rewrite the task Description to match
  the delivered "manifest catalog" scope so the COMPLETED claim stops implying
  executable third-party plugins. (`src/console/services/plugins.py`)
- **INT-005 80% coverage goal — FINISH (raise coverage) or REMOVE the number.**
  Keep the CONFIRMED test infrastructure, but the "80%+ code coverage" goal is
  unmet (~55%). Either drive coverage up or restate the target to the real,
  gated floor (45%) so the worklist is not implicitly claiming 80%.
- **INT-016 live-DigitalOcean verification — ACCEPTED (as operator-gated).** The
  two "verified against a real Dedicated build/runtime" checkboxes cannot be
  reproduced from the repo (state is runtime/cache, servers torn down). This is
  legitimately live-resource work; record it under `docs/NEEDS-OPERATOR.md` as
  operator-attested rather than repo-reproducible, and rely on the code+tests as
  the standing evidence.
- **INT-022 advertised-but-dead gateway config — REMOVE (or wire).** The
  `budget` object and `retries.max_retries`/`backoff_seconds` keys in
  `config/gateway-policy.json` are advertised but never consumed
  (`do-anthropic-proxy.py:65-67`). This is already captured as PR-1.10; noting
  it here for traceability from the COMPLETED claim.
- **INT-020 trace redaction — ACCEPTED with a follow-up note.** Redaction is
  correct but enforced by convention at call sites, not a central choke-point.
  Acceptable for the current trust model; a single redacting entry point would
  be a defense-in-depth FINISH item if traces ever gain full-content modes.

## Bottom line

The older `INT-*` COMPLETED claims held up well against the code: nothing was
UNSUBSTANTIATED, and the two PARTIAL items (INT-011 plugins, INT-005 coverage
goal) are over-statements of scope rather than missing features. The most
defensible gap for GOVERNANCE purposes is INT-011, whose COMPLETED language
implies a running plugin system that does not exist.
