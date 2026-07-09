# Trace Redaction Policy

Trace records are operational metadata, not chat transcripts.

## Stored By Default

- Trace ID, timestamp, action, status, HTTP status, latency, provider, endpoint mode, and routing reason.
- Requested model and routed model.
- Token usage and cost metadata returned by the provider or local estimator.
- Upstream request ID when available.
- A privacy-safe message summary: message count, the last user message character count, and a short whitespace-normalized preview.

## Not Stored By Default

- Full prompt or full assistant response content.
- Access tokens, API keys, endpoint credentials, or Dedicated access tokens.
- Raw Dedicated private endpoint credentials or CA certificate material.
- Full upstream payloads unless a future operator-only diagnostic mode explicitly adds a redacted pointer.

## UI Rules

- Message Show Detail may display trace IDs and routing metadata.
- Raw trace diagnostics may show the redacted trace record, but should not reconstruct the full user prompt.
- If a future feature needs full-prompt tracing, it must be opt-in, visibly marked, and stored separately from the default trace log.
