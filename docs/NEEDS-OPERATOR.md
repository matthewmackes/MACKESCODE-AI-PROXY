# Needs Operator

This file tracks work that code can support but cannot honestly close without a
live resource, account permission, external service, billing state, or explicit
operator decision.

Use this when an implementation is otherwise ready but acceptance depends on
DigitalOcean account state, GPU availability, public endpoint assignment,
GitHub/release ownership, billing/prepay visibility, or a user choice that is
not recoverable from project files.

The release-candidate handoff derives gate type, owner, next action, and
evidence requirements from each row's Item/Needs/Status text. Keep those fields
specific enough for an operator to prove closure without reading implementation
history.

## Current Items

| Item | Needs | Status |
| --- | --- | --- |
| Dedicated Inference live capacity verification | A DigitalOcean region/GPU plan with available capacity for the selected model. | Operator/live-cloud gated. Evidence to close: V2 Dedicated capacity planner shows the desired model/region/plan as available, or records unavailable alternatives with a human-readable fallback. |
| DigitalOcean billing and prepay completeness | Token/account with billing visibility and any account-specific prepaid balance API availability. | Best-effort in UI. Evidence to close: Observe/Operate billing surfaces show current account billing/prepay data or a precise API/scope limitation message for the operator's account. |
| Final public release/version policy | Operator decision for semantic version, release cadence, and tag process. | Open product/release decision. Evidence to close: chosen versioning policy is written into `RELEASE.md`, `CHANGELOG.md`, and the tag/release checklist. |
| GitHub repository administration | Repository settings, branch protection, required checks, and security advisory contact preferences. | Operator-owned after publish. Evidence to close: branch protection and required release checks are configured on the hosted repository, with advisory/security contact preferences set. |
| Unrecoverable survey answer mappings | Original prompts for compacted answer-only survey sequences. | Do not infer missing product requirements. Evidence to close: operator restates the missing prompts/requirements or explicitly cancels the survey-derived work. |
| Packaged-install acceptance test (2026-07-11) | Root on a clean target host to run `install/install.sh` or build/install the RPM, then run `install/test-install.sh`. | Code-complete but host-gated. Evidence to close: `matts-v2-console.py --host 127.0.0.1 --port 18182` imports and serves `/v2/health`, `claude-do --list-models` reads the governed registry, and model edits persist to `/var/lib/matts-value-set/config/models.json` or the configured writable data path. |
| Canonical product brand name (2026-07-11) | Operator decision on one brand across UI, service identifiers, docs, and packaging. | Product decision, not a code defect. Evidence to close: operator picks the name; then update V2 frontend title/nav, launcher/service text, package metadata, README, CLAUDE, and RELEASE together. |

## Template

```markdown
## AREA

- **ITEM-ID: short title** - _needs:_ live resource, operator credential, billing
  condition, external account, or product decision. Include what is already
  code-complete, what remains unverifiable, and the exact evidence needed to
  close it.
```
