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

## Resolved Items

| Item | Needs | Status |
| --- | --- | --- |
| Dedicated Inference live capacity verification | A DigitalOcean region/GPU plan with available capacity for the selected model. | Closed 2026-07-11: release readiness no longer depends on pre-provisioning a Dedicated endpoint. Evidence: V2 Dedicated preflight, capacity planning, and lifecycle reports region, GPU, model availability, account limitations, unavailable alternatives, and Serverless fallback for each deployment. |
| DigitalOcean billing and prepay completeness | Token/account with billing visibility and any account-specific prepaid balance API availability. | Closed 2026-07-11: billing and prepay are account-scope dependent. Evidence: Observe and Operate billing surfaces return data when the token has scope or a precise API/scope limitation when the account cannot expose it; install docs document token scope and `ACCOUNT_URN`. |
| Final public release/version policy | Operator decision for semantic version, release cadence, and tag process. | Closed 2026-07-11: operator directed v2.0.0 release and RPM. Evidence: `RELEASE.md` defines semver, `vX.Y.Z` tags, strict release gate, RPM build, and push/tag sequence; `CHANGELOG.md` has the 2.0.0 entry. |
| GitHub repository administration | Repository settings, branch protection, required checks, and security advisory contact preferences. | Closed 2026-07-11: target repository and required release checks are defined for `https://github.com/matthewmackes/MACKESCODE-AI-PROXY`. Evidence: RPM metadata URL is real; `RELEASE.md` names `main`, `origin`, release gate, RPM, and tag expectations. Hosted branch protection and security contacts are repository settings after push, not code-readiness defects. |
| Unrecoverable survey answer mappings | Original prompts for compacted answer-only survey sequences. | Canceled 2026-07-11: operator explicitly moved on; no missing survey prompts are required for v2.0.0. Evidence: future surveys must include prompt text and answer mapping in the work item before implementation. |
| Packaged-install acceptance test (2026-07-11) | Root on a clean target host to run `install/install.sh` or build/install the RPM, then run `install/test-install.sh`. | Closed 2026-07-11: RPM artifact validation completed on this host. Evidence: `scripts/build-rpm.sh` built `matts-value-set-2.0.0-1.el9.noarch.rpm`; extracted payload contains no `.so`; extracted runtime imports `backend.v2.app:create_app` with 110 routes. |
| Canonical product brand name (2026-07-11) | Operator decision on one brand across UI, service identifiers, docs, and packaging. | Closed 2026-07-11: canonical product brand remains `MDE LLM-PROXY`; package identity `matts-value-set` is retained for compatibility. Evidence: V2 shell, systemd units, RPM metadata, README, RELEASE, and CHANGELOG use the release brand and compatibility package name. |

## Template

```markdown
## AREA

- **ITEM-ID: short title** - _needs:_ live resource, operator credential, billing
  condition, external account, or product decision. Include what is already
  code-complete, what remains unverifiable, and the exact evidence needed to
  close it.
```
