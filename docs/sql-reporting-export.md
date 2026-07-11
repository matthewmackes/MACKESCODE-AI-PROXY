# SQL Reporting Export

The console can export redacted runtime data into a local reporting database for
Metabase, DuckDB, SQLite, or local SQL tools.

## Export

Use Console > Accounting & Time > Reporting Integrations > `Export DB`, or call:

```bash
curl -X POST http://127.0.0.1:8080/api/reporting-export \
  -H 'content-type: application/json' \
  -d '{"format":"duckdb"}'
```

When DuckDB is not installed in the Python environment, the exporter writes a
SQLite fallback at:

```bash
build/reporting/mde-llm-proxy-reporting.sqlite
```

If DuckDB is available, the preferred output is:

```bash
build/reporting/mde-llm-proxy-reporting.duckdb
```

`GET /api/reporting-export` returns the current export status and discovered
database files.

## Tables

Schema version 1 includes:

- `metadata`
- `source_fingerprints`
- `trace_events`
- `usage_events`
- `eval_runs`
- `eval_results`
- `comparison_reports`
- `dedicated_lifecycle_events`
- `audit_events_redacted`
- `review_items`
- `release_checks`

Each source fingerprint records the source path, SHA-256 digest, and byte count
where the source exists.

## Redaction

The export excludes or redacts fields commonly containing prompts, responses,
raw terminal screens, message arrays, tokens, API keys, passwords, and raw
provider payloads. Redacted payload copies are still included as JSON columns for
audit context.

## Metabase

For SQLite, use the Metabase SQLite driver and point it at
`build/reporting/mde-llm-proxy-reporting.sqlite`.

For DuckDB, use a Metabase DuckDB-compatible driver or inspect the file with the
DuckDB CLI:

```bash
duckdb build/reporting/mde-llm-proxy-reporting.duckdb
```

The export is explicit and local. It does not start Metabase, Grafana,
Prometheus, or any cloud resource.
