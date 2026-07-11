# Domain Model Conventions

The console now has standard-library dataclass records under
`src/console/domain/` for high-risk data shapes.

## Rules

- Domain records expose `from_dict()` and `to_dict()` so existing JSON API
  payloads remain compatible.
- Required identifiers raise `ValueError` when missing.
- Optional fields normalize to stable empty values instead of repeating
  ad hoc defaults across services.
- Services may use domain objects internally but should keep public API payloads
  as dictionaries until a versioned response migration is planned.
- Sensitive payload-bearing records should keep prompt, response, raw provider,
  and terminal content out of typed fields unless a redaction rule is explicit.

## Current Records

- `auth.ActorIdentity`
- `auth.PermissionDecision`
- `traces.MessageSummary`
- `traces.TraceRecord`
- `gateway.GatewayDecision`
- `dedicated.DedicatedConfig`
- `dedicated.LifecycleEvent`
- `models.ModelRecord`
- `models.ModelPricing`
- `results.ErrorInfo`

`AuthHandler` normalizes identities through `ActorIdentity`. `TraceService`
normalizes trace append/read records through `TraceRecord` and uses
`MessageSummary` for message summaries.
