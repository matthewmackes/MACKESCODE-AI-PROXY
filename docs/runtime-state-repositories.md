# Runtime State Repositories

Runtime state repositories live under `src/console/store/` and provide shared file primitives for local console state.

The operational SQLite store (`src/console/services/operational_store.py`) is
the runtime source of truth for typed operational reads. JSON/JSONL files remain
as append/export rollback seams and are backfilled into SQLite before reads.

## Base Repository

`RuntimeStateRepository` owns the common behavior:

- atomic JSON writes through temp-file, fsync, chmod, and replace
- locked JSONL appends using sidecar `.lock` files
- bounded JSONL reads with malformed-row tolerance
- recursive redaction for configured sensitive keys
- schema version and retention metadata
- SHA-256 source fingerprints
- backup and archive candidate discovery
- migration hooks for JSON reads
- SQLite runtime-state mirroring for JSON documents

Repositories are local file abstractions. They do not decide policy, call providers, or emit events.

## Migrated State

The migrated repositories are:

- `TraceRepository`: writes `traces.jsonl`, mirrors to `operational_records(kind='traces')`, backfills existing JSONL rows, and reads from SQLite with source-path filters.
- `AuditRepository`: writes `audit.jsonl`, mirrors to `operational_records(kind='audit')`, backfills existing JSONL rows, and reads from SQLite with source-path filters.
- `UsageService`: backfills the proxy cost JSONL into `operational_records(kind='usage')` before local usage reports and 24-hour cost estimates.
- Runtime JSON repositories: write the file and mirror the redacted payload into `runtime_state` so a missing file can be restored from SQLite.

The shared console `tail_jsonl` helper now uses the same bounded JSONL reader, so existing read-only services get consistent malformed-line handling while they await full typed repository migration.

## Ownership

Services still own domain normalization:

- `TraceService` assigns trace IDs, timestamps, and `TraceRecord` validation.
- `AuditService` builds actor/action/outcome records and applies audit-specific truncation.
- Repositories own persistence mechanics, redaction-at-write, metadata, and file safety.

## Backup Metadata

`metadata()` returns:

- `name`
- `schema_version`
- `path`
- `retention`
- `fingerprint`
- `backups`

Backup discovery looks for common adjacent files such as `.bak`, `.backup`, `*-backup*`, and `*-archive*` variants. Rollback and bundle services can consume this metadata without knowing service-specific file naming details.
