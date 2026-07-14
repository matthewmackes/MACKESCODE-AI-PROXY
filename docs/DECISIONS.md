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

## ADR-0005 - Redact Sensitive Operational Metadata At Registry Write Time (2026-07-13)

- **Symptom:** Platform review P2 (2026-07-11), tracked as INT-170: the model
  access key audit wrote raw probe error bodies (up to ~1000 chars of upstream
  HTTP response) into each model's `last_error`, and Dedicated registration
  wrote the live `inference_id` plus public/private endpoint FQDNs into the
  registry entry (top-level `inference_id` survived `normalize()`, and the
  nested `dedicated.server_id`/`dedicated.endpoint` were preserved wholesale
  into git-tracked `config/models.json`). GOVERNANCE classifies endpoint FQDNs,
  inference ids, raw DigitalOcean payloads, and model-access audit results as
  sensitive operational metadata that must never be committed — in direct
  tension with `config/models.json` being the registry source of truth. The
  review offered (a) defaulting `MATTS_MODEL_CONFIG_FILE` to a runtime copy
  seeded from the committed file, or (b) redacting at write time.
- **Decision:** Option (b) — redact at write time. The committed registry
  stores only non-sensitive summaries; full detail stays in runtime state under
  `$HOME/.cache/matts-value-set/`:
  - Probe failures are collapsed to a short error category (`http_403_forbidden`,
    `http_429_rate_limited`, `timeout`, `connection_error`, `http_5xx`,
    `http_4xx`, `http_401_unauthorized`, `invalid_response`; always <= 64 chars,
    derived only from the status/exception) everywhere a probe outcome is
    persisted or overlaid: model `last_error`, the access-state file, and drift
    events. `last_error` remains a plain string, so registry consumers keep
    working. Full probe forensics (ts, model id, status, category, truncated raw
    body, key fingerprint) append to the runtime JSONL
    `.../studio/model-access-probes.jsonl` (0600), resolved next to the
    model-access-state file.
  - The Dedicated registry entry keeps only non-sensitive routing facts
    (`dedicated.managed/state/region/model_slug/accelerator_slug/scale/hourly_usd`);
    `endpoint`, `inference_id`, and `server_id` are dropped. The live
    identifiers already live solely in the runtime Dedicated config
    (`dedicated-inference.json` under the cache dir, `MATTS_DEDICATED_CONFIG_FILE`),
    which chat routing and the proxy (`_dedicated_route`) already read —
    referenced, not duplicated.
  - `ModelRegistryService.normalize()` no longer carries `inference_id` and
    scrubs identifier keys from a nested `dedicated` dict, so a stale committed
    registry self-heals on its next load/save cycle.
  - Option (a) was rejected: forking the registry into a runtime copy leaves
    the committed seed stale and creates a second source of truth, reopening
    the source-of-truth lock.
- **Affected files:** `src/console/services/serverless_catalog.py`,
  `src/console/services/dedicated.py`, `src/console/services/model_registry.py`,
  `tests/test_serverless_catalog_service.py`, `tests/test_dedicated_service.py`.
- **Consequences:** The committed `config/models.json` is identifier-free and
  raw-body-free by construction, not just by the save-time strip; probe
  forensics live in the runtime JSONL (bounded-growth policy for runtime JSONLs
  is INT-171). Operators inspect full probe bodies via
  `~/.cache/matts-value-set/studio/model-access-probes.jsonl` (path also
  surfaced in the key-audit payload as `probe_log_file`).
- **Verification:** Unit tests assert the audit writes categorized
  `last_error` with no raw-body substring anywhere in registry or access/drift
  state, that full probe detail lands in the runtime JSONL, and that
  `register_model` entries contain no `endpoint`/`inference_id`/`server_id`
  keys while routing still resolves identifiers from runtime state.

## ADR-0006 - Operational SQLite Store Is Runtime Source Of Truth (2026-07-14)

- **Symptom:** The V2 console had several durable runtime ledgers with related
  operational meaning but separate persistence paths: trace/audit/usage JSONL,
  V2 run and research SQLite databases, runtime JSON state files, DigitalOcean
  health snapshots, and the model registry JSON file. `config/models.json` also
  carried source-of-truth duties even though ADR-0005 moved sensitive live
  access and Dedicated identifiers out of committed config. That left selectors,
  `/v1/models`, proxy sync, research/run history, analyst state, and rollback
  tooling with too many persistence boundaries.
- **Decision:** Introduce one operational SQLite store
  (`MATTS_OPERATIONAL_DB`, default
  `~/.cache/matts-value-set/studio/operational.sqlite3`) as the runtime source
  of truth for operational records, runtime JSON mirrors, model registry rows,
  DigitalOcean snapshots, V2 run/research tables, and AI Performance Analyst
  runs/findings. `config/models.json` remains a git-tracked export snapshot for
  code review, bootstrap, rollback, and proxy compatibility, not the live
  authority once the SQLite registry has been seeded. JSONL writers remain in
  place as the rollback/export seam while reads hard-cut to SQLite after
  backfill.
- **Affected:** `src/console/services/operational_store.py`,
  `src/console/store/*`, `src/console/services/model_registry.py`,
  `src/console/services/usage.py`, V2 run/research stores, release/runtime
  backup scripts, DigitalOcean health, provider health, `/v2/analyst`, V2
  Models UI, and generated OpenAPI artifacts.
- **Consequences:** Runtime backup/restore must include `operational_db`.
  `MATTS_V2_RUN_DB` and `MATTS_V2_RESEARCH_DB` default to the operational DB
  unless explicitly overridden for a legacy/diagnostic split. Corrupt or stale
  `config/models.json` snapshots are reported as snapshot issues but do not
  replace a healthy SQLite registry for the same path. Existing proxy consumers
  continue to read the export snapshot.
- **Verification:** Backfill parity tests cover JSONL-to-SQLite trace/usage
  rows and source-path isolation; registry tests cover ordered DB round trips
  and export-snapshot fallback behavior; analyst tests cover model selection,
  unchanged-fingerprint skipping, caps, lifecycle, and API permissions; Digital
  Ocean tests cover monitoring degradation and metric parsing; release checks
  must run the operational DB, OpenAPI, React build, bundle/audit, brand-art,
  and browser-smoke gates.
