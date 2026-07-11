# Audit Explorer

The Audit Explorer searches local console audit records from the runtime JSONL audit log. It is intended for operator triage, permission-denial review, release evidence, and incident reconstruction.

## Location

Open System Operations, then Audit Explorer.

The explorer reads:

```text
$HOME/.cache/matts-value-set/studio/audit.jsonl
```

The audit log is runtime state. It is not release-owned and should not be committed.

## Filters

Supported filters include:

- actor id
- actor role
- action
- permission
- outcome
- status
- session id
- request path
- free-text search
- result limit

API callers can also provide `source`, `model`, `trace_id`, `review_id`, `start_ts`, `end_ts`, `limit`, and `scan_limit`.

The service scans a bounded recent window instead of loading arbitrary log volume. Defaults are `limit=100` and `scan_limit=1000`; `scan_limit` is capped at `10000`.

## Related Links

Records include relationship hints when fields are available:

- trace ids link to traces
- session ids link to session/AgentBoard context
- review ids and review actions link to the review queue
- config drift actions link to config drift
- rollback actions link to rollback
- cost anomaly actions link to cost anomalies
- request paths are retained as path evidence

Links are metadata hints only. They do not imply that the related record still exists.

## Export

Use the JSON and CSV buttons to export the current filter result.

JSON export includes the same payload as the explorer. CSV export includes compact columns for timestamp, actor, action, permission, outcome, status, request path, and related links.

## Redaction

Audit records are already redacted at write time by `AuditService`. The explorer redacts sensitive keys again when reading older or externally written records. Keys containing token, access token, authorization, api key, password, or secret are replaced with `[redacted]`.

Malformed JSONL lines are skipped and counted in the summary.

## Retention

The explorer does not compact or delete audit records. Retention is controlled by the operator’s runtime-state policy for the audit JSONL file.
