# Compliance And Integrity Sweeps

This document records release-readiness and integrity sweeps. A sweep asks
whether the platform is honest, reachable, secure enough for its trust model,
and documented accurately.

Findings should use one of these verdicts:

- **FINISH** - the feature or claim is valuable but incomplete, unwired, poorly
  verified, or under-documented.
- **REMOVE** - the feature, control, doc claim, or UI surface is dead, misleading,
  or not worth carrying.
- **ACCEPTED** - the risk or limitation is deliberate and documented.

## Sweep Checklist

- No untracked secrets, endpoint credentials, generated auth tokens, live cloud
  identifiers, traces, usage logs, or runtime cache files are committed.
- `config/models.json` remains the single selectable model config source, with
  runtime model-access audit state kept under the app cache.
- Code/Create/Console selectors, proxy `/v1/models`, and model hero cards agree
  on merged enabled/access state.
- Dedicated lifecycle UI, proxy errors, and trace records explain build,
  budget, idle, unhealthy, fallback, and teardown decisions.
- Every sensitive action is permission checked and audit logged.
- Trace records follow `docs/trace-redaction-policy.md`.
- Console tab navigation, dark mode, status/cost pills, and Create/Code primary
  workflows work in browser smoke.
- Documentation examples match actual commands and paths.
- `scripts/release-check.sh` passes before release or publish.

## Sweep 2026-07-09 - Governance Import

| Area | Finding | Verdict |
| --- | --- | --- |
| Governance | Rulebook was spread across multiple docs and chat history. | **FINISH** - added `GOVERNANCE.md`, ADR log, operator-needed tracker, threat model, compliance sweep doc, and polish skill. |
| Source import | `magic-mesh` contained useful governance patterns but many product-specific locks. | **ACCEPTED** - imported only portable governance patterns and explicitly excluded irrelevant Nebula/egui/Rust/build-farm locks. |
| Release gate | Existing release check is the correct local gate for this Python/web-console project. | **ACCEPTED** - keep `scripts/release-check.sh` as primary gate; consider stronger coverage and screenshot artifacts later. |

## Sweep 2026-07-11 - Post-Drain Verification Sweep (Coordination Branch)

Five parallel audits verified the then-current worklist "all COMPLETED" claim
against the sweep checklist; the release gate passed (incl. browser smoke)
before the sweep began. Findings were drained the same day and their fixes
now live on `main` (see INT-154..161).

| Area | Finding | Verdict |
| --- | --- | --- |
| Secrets/runtime state | Three live DigitalOcean Dedicated build UUIDs were committed in worklist progress notes. Everything else clean: no tokens, empty embedded fallback keys, runtime writes under the app cache, no runtime state tracked. | **REMOVE** - redacted 2026-07-11. |
| Registry source of truth | Live/runtime path fully derives from `config/models.json`; but proxy/CLI/`matts-image` carried divergent hardcoded bootstrap tables and never read `config/default-models.json`. | **FINISH** - INT-154, landed on `main`. |
| Feature reachability | Recent features verified runtime-reachable and tested; plugin registry extension points had zero consumers. | **FINISH** - INT-156 (V1); V2 disposition under INT-161. |
| Security surfaces | Sensitive REST actions permission-checked and audit-logged; gap: V1 `/ws/tmux` accepted any authenticated permission with no audit records. | **FINISH** - INT-155, upgraded to audited 403 flow and ported into V2 policy architecture. |
| Trace redaction | Trace/usage writers store operational metadata plus a bounded preview only; no full prompts/responses persisted by default. | **ACCEPTED** - compliant. |
| Docs accuracy | Commands/paths/endpoints matched code at audit time; proxy argparse port default divergence folded into INT-154. Post-ADR-0003, V1-centric docs are re-scoped under INT-161. | **FINISH** (minor) - INT-154/INT-161. |
