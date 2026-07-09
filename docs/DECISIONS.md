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
