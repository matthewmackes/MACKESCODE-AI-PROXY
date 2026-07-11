# Quota Planner

The console quota planner adds persistent quota accounting on top of the existing fixed-window API rate limiter and cost budget guards.

## Configuration

Quotas live in `config/console.json` under `rate_limits.quotas`:

```json
{
  "enabled": true,
  "warn_fraction": 0.8,
  "default_policy": {
    "daily": {"requests": 1000, "usd": 25},
    "monthly": {"requests": 20000, "usd": 500}
  },
  "roles": {
    "viewer": {"daily": {"requests": 100, "usd": 2}}
  },
  "actions": {
    "chat": {"daily": {"requests": 600, "usd": 12}},
    "eval": {"daily": {"requests": 40, "usd": 10}}
  },
  "models": {},
  "projects": {}
}
```

Supported windows are `daily` and `monthly`. Supported metrics are `requests` and `usd`. Usage is stored as JSONL at the configured `paths.quota_file`.

## Enforcement

Managed actions are checked before provider-facing work starts:

- `/api/chat` as `chat`
- `/api/chat/compare` as `comparison`
- `/api/evals/run` as `eval`
- `/api/generate` as `image`
- `/api/dedicated/build` and `/api/dedicated/resume` as `dedicated`
- `/api/test-models` as `smoke_test`

Every matching policy is evaluated independently. A request is blocked if any applicable default, role, action, model, or project quota would be exceeded. A request is allowed with `status: "warning"` when projected usage is at or above `warn_fraction` of a configured limit.

## Precedence With Budgets And Rate Limits

Rate limits still run first and protect the console from short bursts. Quotas run after auth and permission checks, but before expensive provider calls. Cost budgets remain separate spend controls and can still block downstream actions when a quota allows the request.

In practice:

1. API fixed-window rate limit blocks burst traffic with `rate_limit_exceeded`.
2. Quota planner blocks daily or monthly actor/action/model/project overuse with `quota_exceeded`.
3. Budget guards block provider spend when cost policy requires it.

## UI And Audit Trail

`GET /api/quotas` reports remaining quota rows and recent usage for the current actor fingerprint. `POST /api/quota-planner` previews a planned action without consuming quota.

The Console Ops panel shows remaining quota. Existing cost confirmation dialogs also preview quota before image generation, model comparison, eval runs, and Dedicated builds.

Consumed quota decisions append:

- a quota ledger row for allowed requests
- an audit record with `quota.allowed`, `quota.warning`, or `quota.blocked`
- a trace record with `action: "quota.decision"`
