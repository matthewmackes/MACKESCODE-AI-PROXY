# AI Performance Analyst

The AI Performance Analyst is a V2 operational loop for proxy and model health.
It combines local telemetry, model scorecards, provider health, DigitalOcean
status/Monitoring context, and a bounded public research sweep into one
persistent assessment.

## Behavior

- API: `GET /v2/analyst`, `POST /v2/analyst/run`, and
  `POST /v2/analyst/findings/{id}/ack`.
- UI: Advanced > Models shows the analyst pulse, proxy grade, per-model grades,
  finding lifecycle actions, and a compact high-finding trend.
- Worker: `backend/v2/app.py` starts a daemon loop unless
  `MATTS_ANALYST_WORKER_ENABLED=0`.
- Model policy: choose the cheapest route-enabled grade-A text model; fall back
  to grade B/C/unmeasured only when no A model is available.
- Cost cap: `MATTS_ANALYST_DAILY_CAP_USD` defaults to `0.25`. When exceeded,
  the analyst records a deterministic paused run instead of spending a model
  call.
- Cache: unchanged operational telemetry fingerprints skip a new run. The
  fingerprint excludes the analyst's own history so persisted runs do not cause
  self-triggered churn.
- Fallback: if the public sweep or LLM call fails, deterministic SRE-style
  findings are still produced from local telemetry.

## Persistence

Analyst runs and findings live in the operational SQLite store:

```text
~/.cache/matts-value-set/studio/operational.sqlite3
```

Findings keep lifecycle state across runs: `new`, `ongoing`, `resolved`, and
acknowledged metadata. High-severity findings emit an automation event so
external notification bridges can push operator alerts.

## Security

The analyst prompt is built from redacted telemetry and must not include raw
prompts, responses, provider secrets, or token values. Viewing requires
`view_console`; forcing a run requires `model_use`; acknowledging a finding
requires `view_console`.
