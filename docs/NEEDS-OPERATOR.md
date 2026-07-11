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
| Dedicated Inference live capacity verification | A DigitalOcean region/GPU plan with available capacity for the selected model. | Operator/live-cloud gated. Code should surface unavailable plans and fallback options. |
| DigitalOcean billing and prepay completeness | Token/account with billing visibility and any account-specific prepaid balance API availability. | Best-effort in UI; account/API limitations should appear as human-readable lifecycle detail. |
| Final public release/version policy | Operator decision for semantic version, release cadence, and tag process. | Open decision for `RELEASE.md`/`CHANGELOG.md` once chosen. |
| GitHub repository administration | Repository settings, branch protection, required checks, and security advisory contact preferences. | Operator-owned after publish. |
| Unrecoverable survey answer mappings | Original prompts for compacted answer-only survey sequences. | Do not infer missing product requirements; wait for restatement. |
| Packaged-install acceptance test (2026-07-11) | Root on a clean target host to run `install/install.sh` (or build the RPM) and then `install/test-install.sh`. | Code-complete: `install.sh`, the RPM spec, `environment.conf`, and `test-install.sh` now ship `src/`/`templates/`/`config/` and seed a writable registry under `/var/lib`. Cannot be closed here (needs root + a clean host). Evidence to close: `matts-console` imports and serves `/health`, `claude-do --list-models` reads the governed registry, and Console model edits persist to `/var/lib/matts-value-set/config/models.json`. |
| Canonical product brand name (2026-07-11) | Operator decision on one brand: UI shows "Mackes Code", the service id is `matts-unified-console`, docs say "Matts Value Set". | Code is internally consistent (`/health` and `/version` agree). Choosing one public brand and applying it to the UI title, service id, and docs is a product decision, not a defect. Evidence to close: operator picks the name; then update `templates/*.html`, `image-studio.py` service strings, and README/CLAUDE together. |
| UI visual-polish items needing rendered evidence (2026-07-11) | A browser-smoke environment (Playwright is not installed here). | Worklist PR-2.3 (lazy per-tab loading), PR-4.1 (build-confirm cost dialog), PR-4.2 (keep-alive control), PR-4.3 (dark-mode wallpaper), PR-4.4 (interactive Code terminal), PR-4.5 (accessibility) change `templates/main.html`. GOVERNANCE requires rendered browser evidence for UI changes; implementing them blind and unverifiable would violate the definition of done. Evidence to close: run `scripts/browser-smoke.py` with Playwright installed, or capture rendered screenshots per change. |

## Template

```markdown
## AREA

- **ITEM-ID: short title** - _needs:_ live resource, operator credential, billing
  condition, external account, or product decision. Include what is already
  code-complete, what remains unverifiable, and the exact evidence needed to
  close it.
```
