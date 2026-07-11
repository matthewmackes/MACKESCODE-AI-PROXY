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
