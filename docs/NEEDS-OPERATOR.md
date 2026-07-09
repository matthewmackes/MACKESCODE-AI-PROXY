# Needs Operator

This file tracks work that code can support but cannot honestly close without a
live resource, account permission, external service, billing state, or explicit
operator decision.

Use this when an implementation is otherwise ready but acceptance depends on
DigitalOcean account state, GPU availability, public endpoint assignment,
GitHub/release ownership, billing/prepay visibility, or a user choice that is
not recoverable from project files.

## Current Items

| Item | Needs | Status |
| --- | --- | --- |
| Dedicated Inference live capacity verification | A DigitalOcean region/GPU plan with available capacity for the selected model. | Operator/live-cloud gated. Code should surface unavailable plans and fallback options. |
| DigitalOcean billing and prepay completeness | Token/account with billing visibility and any account-specific prepaid balance API availability. | Best-effort in UI; account/API limitations should appear as human-readable lifecycle detail. |
| Final public release/version policy | Operator decision for semantic version, release cadence, and tag process. | Open decision for `RELEASE.md`/`CHANGELOG.md` once chosen. |
| GitHub repository administration | Repository settings, branch protection, required checks, and security advisory contact preferences. | Operator-owned after publish. |
| Unrecoverable survey answer mappings | Original prompts for compacted answer-only survey sequences. | Do not infer missing product requirements; wait for restatement. |

## Template

```markdown
## AREA

- **ITEM-ID: short title** - _needs:_ live resource, operator credential, billing
  condition, external account, or product decision. Include what is already
  code-complete, what remains unverifiable, and the exact evidence needed to
  close it.
```
