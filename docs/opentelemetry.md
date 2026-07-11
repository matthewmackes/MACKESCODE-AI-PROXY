# OpenTelemetry Export

The console can optionally export privacy-safe trace and metrics data to an
OpenTelemetry Collector over OTLP/HTTP JSON.

OpenTelemetry is disabled by default. Local JSONL traces and Prometheus text
metrics continue to work without a collector.

## Configuration

Set `observability.opentelemetry` in `config/console.json`:

```json
{
  "observability": {
    "opentelemetry": {
      "enabled": true,
      "endpoint": "http://127.0.0.1:4318",
      "service_name": "mde-llm-proxy-console",
      "timeout_seconds": 3,
      "headers": {}
    }
  }
}
```

The console also honors common OTLP environment variables:

- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_SERVICE_NAME`
- `OTEL_EXPORTER_OTLP_TIMEOUT` in milliseconds
- `OTEL_EXPORTER_OTLP_HEADERS` as comma-separated `key=value` pairs

When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, OpenTelemetry export is enabled and
signal-specific `/v1/traces` and `/v1/metrics` paths are appended to the
endpoint unless the endpoint already ends with a signal path.

## Exported Data

Trace spans include operational metadata only:

- trace ID, action, status, latency, cost, and error category
- requested/routed model
- backend and routing reason
- gateway decision
- session/chat/tmux identifier when present
- message count and last-user character count

The exporter does not send prompt text, response text, full message payloads, or
the local `last_user_preview` field.

Metrics include console readiness, uptime, proxy socket readiness, tmux session
count, and request counters by HTTP method.

## Failure Behavior

Exporter failures are best-effort and non-blocking. If a collector is down,
trace writes and `/metrics` responses still complete. The exporter records the
last local error string for tests and diagnostics but does not surface collector
failures to operator requests.

## Collector Notes

Use an OTLP/HTTP receiver on port `4318` in your collector configuration. The
OpenTelemetry OTLP exporter configuration docs describe the same endpoint and
environment-variable conventions:

```text
https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/
```
