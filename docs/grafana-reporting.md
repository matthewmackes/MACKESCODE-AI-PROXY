# Grafana OSS Reporting

The console exposes privacy-safe Prometheus metrics at `/metrics` and ships
Grafana OSS dashboard JSON under `config/grafana/dashboards/`.

## Metrics

The endpoint includes:

- console health, readiness, uptime, request counters, and tmux session count
- model request volume, latency histogram, token totals, and cost totals
- gateway fallback counters and provider error counters
- Dedicated lifecycle state and runtime seconds
- budget used/limit gauges
- rate-limit and quota block counters
- eval run counters and latest pass-rate gauges

Labels are bounded to model, route, status, provider, category, dataset, and
window values. Prompt text, response text, raw token values, source snippets,
endpoint credentials, and unbounded session names are excluded.

## Prometheus

Use the sample scrape config:

```bash
config/prometheus/mde-llm-proxy-console.yml
```

If Prometheus runs in Docker and the console is on the host, keep the default
`host.docker.internal:8080` target. If the console runs elsewhere, update the
target to the reachable host and port.

## Grafana

Dashboard JSON files are stored in:

```bash
config/grafana/dashboards/
```

Import them through `Grafana > Dashboards > New > Import`, or mount the
directory into a local Grafana container.

The optional compose example is:

```bash
config/grafana/docker-compose.example.yml
```

It starts Prometheus and Grafana OSS only; it does not start or modify the
console.

## Console Panel

Console > Accounting & Time includes a Reporting Integrations panel backed by
`GET /api/reporting-integrations`. It reports `/metrics` reachability, current
series count, OpenTelemetry exporter state, bundled dashboard paths, and setup
snippets.
