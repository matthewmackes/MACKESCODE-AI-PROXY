# Failure Taxonomy

The Console normalizes provider, proxy, gateway, Dedicated, eval, and session failures into one shared taxonomy. Error responses expose an actionable `failure` object while raw diagnostics stay redacted under `diagnostics`.

## Response Shape

Failed API responses include:

```json
{
  "message": "Too many requests",
  "category": "rate_limit",
  "failure": {
    "category": "rate_limit",
    "title": "Rate limit",
    "likely_cause": "The provider, gateway, or local quota policy throttled the request.",
    "suggested_fix": "Wait for the current window to reset or route through an approved fallback model.",
    "operator_actions": [
      {"label": "Gateway decisions", "target": "console:gateway-decisions"}
    ],
    "trace_id": "trace_..."
  },
  "diagnostics": {
    "redacted": true
  }
}
```

The normal UI surfaces category, likely cause, suggested fix, and trace ID. Redacted diagnostics are available only in detail drawers or JSON diagnostics views.

## Categories

| Category | Typical cause | Suggested operator action |
| --- | --- | --- |
| `auth` | Missing or invalid Console session, provider token, or model access key | Refresh the session and rerun the model access key audit |
| `access` | Operator role or provider account lacks permission for the model or action | Check RBAC and rerun model access discovery |
| `budget` | Budget policy, quota, or cost guardrail blocked the request | Review Quota Planner and cost limits |
| `rate_limit` | Provider, gateway, or local quota throttled the request | Wait for reset or use an approved fallback model |
| `provider_outage` | DigitalOcean or upstream inference provider is degraded | Check Provider Health and route through fallback |
| `context_overflow` | Prompt, retrieval payload, or history exceeds context | Reduce context or select a larger-window model |
| `malformed_tool_call` | Invalid tool JSON, schema, or arguments | Replay the trace and tighten tool schema instructions |
| `registry_drift` | Local proxy registry, catalog, or access state is stale | Sync the proxy registry and rerun discovery |
| `dedicated_not_ready` | Dedicated endpoint is building, cooling down, unhealthy, or missing setup | Open Dedicated lifecycle and use Serverless fallback |
| `local_proxy` | Local proxy is stopped, unreachable, or out of sync | Restart or sync the proxy |
| `validation` | Request is missing required fields or contains invalid values | Correct the request and retry |
| `not_found` | Requested trace, session, model, or artifact does not exist | Refresh the view and select an existing resource |
| `unknown` | No known category matched | Attach the trace to a review item with diagnostics |

## Aggregation

Failure categories feed:

- Trace records through `error_category` and `failure`
- Analytics through `failure_categories` and per-model counts
- Provider Health through model failure category counts and findings
- Review Queue automatic trace reviews
- Notifications through Provider Health findings

## Redaction

Diagnostics redact sensitive fields such as tokens, API keys, prompts, messages, raw payloads, screen output, and authorization headers. The `failure` object is designed to be safe for normal UI display and audit summaries.
