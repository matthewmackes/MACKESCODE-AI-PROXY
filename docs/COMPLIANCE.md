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
- `config/models.json` remains the single selectable model source of truth.
- Code/Create/Console selectors, proxy `/v1/models`, and model hero cards agree
  on enabled/access state.
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
