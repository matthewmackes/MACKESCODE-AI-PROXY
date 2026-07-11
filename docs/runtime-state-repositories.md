# Runtime State Repositories

Runtime state repositories live under `src/console/store/` and provide shared file primitives for local console state.

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

Repositories are local file abstractions. They do not decide policy, call providers, or emit events.

## Migrated State

The first migrated repositories are:

- `TraceRepository`: backs `TraceService` append/read operations for `traces.jsonl`.
- `AuditRepository`: backs `AuditService` append operations for `audit.jsonl`.

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
