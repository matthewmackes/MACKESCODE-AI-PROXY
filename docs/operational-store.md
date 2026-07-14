# Operational SQLite Store

The V2 console uses one SQLite file for local operational state:

```text
~/.cache/matts-value-set/studio/operational.sqlite3
```

Override it with `MATTS_OPERATIONAL_DB`. Release checks isolate it at
`$MATTS_STUDIO_DIR/operational.sqlite3`.

## Owned Data

- `operational_records`: backfilled trace, audit, usage, and event-style rows with source-path isolation.
- `runtime_state`: mirrored JSON runtime documents for restore/fallback.
- `model_registry`: active registry rows, ordered for selector/proxy parity.
- `digitalocean_snapshots`: account, balance, status, and Monitoring API snapshots.
- `analyst_runs` and `analyst_findings`: AI Performance Analyst history, finding lifecycle, and acknowledgement state.
- V2 Run and Research tables share the same database by default through `MATTS_V2_RUN_DB` and `MATTS_V2_RESEARCH_DB` falling back to `MATTS_OPERATIONAL_DB`.

## Registry Snapshot

The SQLite `model_registry` table is the runtime source of truth after seeding.
`config/models.json` is still written on every registry save, but it is an
export snapshot for git review, bootstrap, rollback, and `/v1/models` proxy
compatibility. If the snapshot becomes malformed while the SQLite registry is
healthy, status payloads report the snapshot issue without replacing the DB
rows.

## Migration And Rollback

JSONL writers remain active for traces, audit, and usage so rollback and manual
inspection keep working. Reads backfill the JSONL source into SQLite first and
then read the SQLite rows filtered by `source_path`. Runtime JSON writes still
write files atomically and mirror the same redacted payload into SQLite.

`scripts/runtime-state.py backup` includes `operational_db`. If an explicitly
configured legacy `MATTS_V2_RUN_DB` points somewhere else, it is also backed up
as `v2_run_db`.
