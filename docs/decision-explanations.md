# Decision Explanations

Decision explanations convert existing console metadata into a standard operator
view for automated choices. The feature is available from `Explain` buttons in
chat details, traces, gateway decisions, Dedicated lifecycle events, quota,
notifications, reviews, and eval response rows.

## Supported Decision Types

- `gateway_routing`: routing, fallback, circuit breaker, cache, SLO, and model
  selection records
- `quota`: request and spend limits matched against actor, role, action, model,
  and project policies
- `budget`: forecast and budget guard decisions
- `eval_gate`: changed surface, recommended datasets, recent evidence, and
  override state
- `dedicated_lifecycle`: Dedicated endpoint state, budget, idle, unhealthy, and
  fallback policy
- `model_access`: merged runtime access status, registry deprecation, and availability policy
- `generic`: notification, review, audit, and other records with partial
  decision metadata

Each explanation includes the selected action, concise reason, policy inputs,
matched policy, candidate options, rejected alternatives, confidence, and
evidence links such as trace IDs and policy files.

## API

Use `POST /api/explain-decision` with either a trace ID:

```json
{"trace_id": "trace-123"}
```

or a redacted/local record:

```json
{"type": "quota", "record": {"action": "chat", "blocks": []}}
```

Trace lookup reads local trace records only. The endpoint does not call a hosted
LLM and does not mutate state.

## Privacy

Prompts, responses, raw output, messages, token fields, authorization headers,
API keys, and secret-like strings are redacted before display. Explanations are
metadata summaries, not forensic proof. When a record lacks detailed candidate
or rejection data, the view marks the explanation as inferred or lower
confidence.
