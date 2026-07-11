# Reporting Tool Integration Design

Purpose: define how this platform should leverage open-source reporting tools
without turning the Console into a full BI product. The Console remains the
operator workflow surface; external reporting tools provide richer dashboards,
alerts, and long-horizon analysis.

## Recommendation

Use Grafana OSS as the primary reporting and observability target.

Use a SQL export path for Metabase or DuckDB-backed reporting as an optional
secondary path for business-style reports.

Do not start with Apache Superset. It is powerful, but heavier than this
private-operator proxy/console needs right now.

## 1. Grafana OSS Reporting Path

### Fit

Grafana fits the platform because the key questions are operational:

- Which models are failing?
- Which routes are slow?
- What is the current cost burn?
- Is Dedicated Inference healthy or idle?
- Are budgets, quotas, and rate limits close to enforcement?
- Did a gateway policy change alter fallback behavior?

The repo already exposes Prometheus text metrics at `/metrics`, so Grafana can
be useful with a small integration layer.

### Target Architecture

Data flow:

```text
Console/proxy runtime
  -> /metrics Prometheus scrape
  -> optional OpenTelemetry collector
  -> Grafana dashboards and alerts
```

Optional full observability stack:

```text
Prometheus or Grafana Mimir  -> metrics
Loki                         -> structured logs / JSONL-derived logs
Tempo                        -> traces
Grafana                      -> dashboards and alerts
```

### Exported Metrics

Minimum metrics:

- `matts_console_requests_total{method,path,status}`
- `matts_model_requests_total{model,route,status}`
- `matts_model_latency_ms_bucket{model,route}`
- `matts_model_tokens_total{model,type}`
- `matts_model_cost_usd_total{model,route}`
- `matts_gateway_fallbacks_total{reason,from_model,to_model}`
- `matts_provider_errors_total{provider,model,category}`
- `matts_dedicated_state{model,state}`
- `matts_dedicated_runtime_seconds_total{model}`
- `matts_budget_used_usd{window}`
- `matts_budget_limit_usd{window}`
- `matts_rate_limit_blocks_total{path,actor_type}`
- `matts_eval_runs_total{dataset,status}`
- `matts_eval_pass_rate{dataset,model}`

### Dashboard Bundle

Add versioned Grafana dashboard JSON under:

```text
config/grafana/dashboards/
```

Recommended dashboards:

- `mde-llm-proxy-overview.json` - service health, request volume, error rate, spend.
- `mde-llm-proxy-models.json` - model latency, cost, failures, tokens, access state.
- `mde-llm-proxy-gateway.json` - routing decisions, fallbacks, budget/rate-limit blocks.
- `mde-llm-proxy-dedicated.json` - Dedicated lifecycle, runtime, idle teardown, spend.
- `mde-llm-proxy-evals.json` - eval pass rate, failures, baseline deltas, cost.

### Console Integration

Add a Console > Reporting Integrations panel:

- Shows whether `/metrics` is enabled and reachable.
- Shows recommended Prometheus scrape config.
- Links to dashboard JSON files.
- Shows current exporter health.
- Offers copyable local Docker Compose snippets when appropriate.

### Privacy And Security

Grafana metrics must not contain prompts, responses, raw tokens, endpoint
credentials, or source snippets. Labels should avoid high-cardinality raw
session names unless explicitly hashed or bounded.

## 2. SQL Reporting Path For Metabase/DuckDB

### Fit

Metabase is useful for ad hoc business-style reporting over tables:

- Daily/monthly spend by model.
- Eval pass rates over time.
- Comparison reports and selected winners.
- Dedicated cost versus Serverless cost.
- Review queue throughput.
- Release readiness history.

DuckDB is a good local file-backed target for this repo because it supports
analytics without requiring a database server.

### Target Architecture

Data flow:

```text
JSONL/runtime files
  -> scheduled/manual export job
  -> build/reporting/mde-llm-proxy-reporting.duckdb or SQLite
  -> Metabase or local SQL tools
```

Recommended first target: DuckDB file export.

Optional secondary target: SQLite for simpler portability if DuckDB is not
available.

### Exported Tables

Initial tables:

- `usage_events`
- `trace_events`
- `model_requests`
- `model_cost_daily`
- `eval_runs`
- `eval_results`
- `comparison_reports`
- `dedicated_lifecycle_events`
- `audit_events_redacted`
- `review_items`
- `release_checks`

### Export Rules

- Export is explicit/manual first; scheduled export can come later.
- Raw prompts and assistant responses are excluded by default.
- Secret-like fields are redacted before table write.
- Each export records source file fingerprints and export timestamp.
- Schema version is stored in a metadata table.

### Console Integration

Add a Console action:

```text
Export Reporting DB
```

It should show:

- Output path.
- Included tables.
- Source file fingerprints.
- Redaction mode.
- Warnings for missing or malformed source files.

## 3. Implementation Phases

### Phase 1 - Grafana Metrics And Dashboards

1. Expand `/metrics` with model, gateway, Dedicated, eval, and cost metrics.
2. Add bundled Grafana dashboard JSON.
3. Add docs and sample Prometheus scrape config.
4. Add tests for metric text output and label redaction.

### Phase 2 - OpenTelemetry Alignment

1. Reuse INT-029 OpenTelemetry export design.
2. Map traces and spans to Grafana Tempo-compatible OTel payloads.
3. Keep exporter optional and non-blocking.

### Phase 3 - SQL Reporting Export

1. Add reporting export service.
2. Generate DuckDB or SQLite tables from runtime JSON/JSONL files.
3. Add Metabase setup docs.
4. Add redaction and source-fingerprint tests.

### Phase 4 - Reporting Integration Panel

1. Add Console UI for exporter health and setup snippets.
2. Link dashboard files and reporting DB exports.
3. Surface last export/check status.

## Done Criteria

- Grafana can visualize platform metrics without custom scraping scripts.
- Dashboard JSON ships with the repo.
- Optional SQL export supports Metabase-style reporting.
- Exports preserve the project's trace redaction and secret-handling rules.
- Reporting integration is optional and does not change local-first operation.
