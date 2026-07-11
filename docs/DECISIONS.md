# Decision Log

Append-only log for durable product and architecture decisions. Record changes
to `GOVERNANCE.md`, reopened design locks, source-of-truth policy, security
posture, release gates, or cloud-lifecycle behavior.

For each entry include:

- date
- symptom or pressure that justified the decision
- superseding decision
- affected files or workflows
- verification or follow-up required

Do not edit old entries except to fix typos. Supersede them with a newer entry.

## ADR-0001 - Adopt Governance Import From magic-mesh (2026-07-09)

- **Symptom:** The project had strong feature documentation, release scripts,
  and security notes, but governance was spread across `CLAUDE.md`,
  `AI-WORK-PROTOCOL.md`, `MAIN-WORKLIST.md`, `SECURITY.md`, and chat history.
  The operator requested review of `magic-mesh` governance, skills, and
  directives and importing as many as apply.
- **Decision:** Add `GOVERNANCE.md` as the project rulebook and import the
  portable governance patterns: architectural locks, runtime reachability as the
  definition of done, operator-needed tracking, ADR-style decision logging,
  threat modeling, compliance sweeps, and an adapted UI polish skill.
- **Scope:** This does not import `magic-mesh` product locks for Nebula,
  egui/DRM, Fedora boot images, Rust workspace gates, or build-farm topology.
- **Verification:** Documentation links and release checks should treat
  `GOVERNANCE.md` as the first stop for future AI-assisted work.

## ADR-0002 - Create Is Image-Only; TMux Console Belongs To Code (2026-07-11)

- **Symptom:** Operator bug reports on 2026-07-11: "The TMux Console, and
  session controls listed under Advanced should be moved to Code" and "Create
  Page is solely for Image Creation" (clarified: retire non-image creation
  from Create entirely, no relocation; text conversations remain on their own
  Chat surface).
- **Decision:** The TMux/TUI console and its session controls live in the
  Code experience, not under an Advanced/owner-tools area. Create is solely
  an image-creation studio.
- **Affected:** Implemented first on the V1 console (worktree branch
  `worktree-bright-elm-9x73`), then re-implemented on the V2 React SPA
  (INT-160) after ADR-0003. Supersedes requirements-ledger entries describing
  Create as a conversational/text surface.
- **Verification:** Release gate plus rendered browser evidence on both
  implementations.

## ADR-0003 - V2 React Console Is Current; V1 Console UI Removed (2026-07-11)

- **Symptom:** Operator reviewed rendered evidence of the ADR-0002 fixes and
  said "That looks like V1" then "V1 should be removed. V2 (React) is the
  current version." The V2 platform (backend/v2 FastAPI + frontend React SPA,
  port 18182) existed only as uncommitted work in the main checkout; the
  committed baseline rendered the V1 console.
- **Decision:** V2 (React) is the current product surface. The live V2
  working state was snapshotted non-invasively (branch `v2-snapshot`) and
  then committed as the canonical baseline on `main` (`b371b91f`) under
  operator authority over all sessions, with `frontend/node_modules`
  gitignored. The V1 console UI is removed (INT-161) while preserving the
  module-level services `backend/v2/services/legacy_console.py` imports.
  ADR-0002's directives are re-implemented on V2 (INT-160).
- **Affected:** `main` history, `.gitignore`, release-gate scope,
  README/CLAUDE.md/SECURITY.md console descriptions, V1 templates and
  entrypoint, GOVERNANCE.md interface rules.
- **Verification:** Extended release gate (V2 tests, OpenAPI drift, React
  build, bundle/audit checks, V2 browser smoke) green on `main`; V2 verified
  operating without V1.

## ADR-0004 - Platform Review Hardening: registry integrity, authz, packaging, cost safety (2026-07-11)

- **Symptom:** A full architecture/UX review (see
  `docs/PLATFORM-REVIEW-2026-07-11.md`) found the governance-locked model
  registry written non-atomically on hot read paths (torn read → silent reset to
  bundled defaults), cost-bearing and terminal-exposing console surfaces
  under-authorized on the `0.0.0.0`-bound console, a Dedicated build that was not
  idempotent (double build orphans a billing GPU), a proxy image endpoint that
  bypassed budget + allowlist, request threads that crashed on malformed
  JSON/upstream, a packaged install that never shipped `src/`/`templates/`/
  `config/`, and a decorative coverage gate (`--fail-under 1`).
- **Decision:** Treat these as governance-lock reinforcements, not features:
  (1) all `config/models.json` writes are atomic (temp + fsync + `os.replace`)
  and serialized; (2) the WebSocket terminal bridge, cost-bearing routes, and
  live-terminal-read routes are permission-checked and audit-logged like other
  sensitive actions; (3) Dedicated `build()` refuses a second server unless
  `rebuild=true`, and the background worker reconciles live DigitalOcean state +
  applies idle/unhealthy policy headlessly (no browser-poll dependency);
  (4) the release coverage gate stays a real floor with
  `MATTS_COVERAGE_FLOOR` override while the V2 baseline continues to raise
  measured coverage;
  (5) the packaged install ships the full runtime tree and keeps the writable
  registry under the data dir, not the read-only prefix.
- **Scope:** Reinforces existing GOVERNANCE locks (source-of-truth integrity,
  permission-checked + audit-logged sensitive actions, cost safety, definition of
  done). No lock was reopened or weakened.
- **Affected files:** `src/console/services/model_registry.py`,
  `src/console/services/dedicated.py`, `src/console/handlers/auth_handler.py`,
  `image-studio.py`, `do-anthropic-proxy.py`, `claude-DO.sh`,
  `scripts/coverage-report.py`, `scripts/release-check.sh`, `install/*`,
  `SECURITY.md`, `CHANGELOG.md`.
- **Verification:** The original Claude worktree passed `scripts/release-check.sh`
  at 55.53% coverage before porting. The V2-main port must pass the current
  release gate before push. The packaged-install fix needs a real root install
  acceptance test — recorded in `docs/NEEDS-OPERATOR.md`.
