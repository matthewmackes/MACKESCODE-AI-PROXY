# PolicyService Boundary

`src.console.policy.PolicyService` is the console-side policy facade for decisions that handlers and services need to explain, audit, and report.

## Decision Shape

Every policy adapter returns a `PolicyDecision` with:

- `domain`: policy area, such as `rbac`, `quota`, `dedicated`, or `gateway`.
- `action`: selected action, denial, fallback, warning, or lifecycle outcome.
- `allowed`: whether the caller may continue without changing route or behavior.
- `reason`: stable machine-readable reason.
- `actor`: actor identity when available.
- `subject`: resource or route being evaluated.
- `matched_policy`: the policy rows, checks, thresholds, or metadata that drove the result.
- `inputs`: bounded request inputs used for the decision.
- `effects`: side effects the caller may perform, such as audit action names or teardown intent.
- `overrides`: explicit operator overrides and reason metadata.

`PolicyDecision.to_dict()` is JSON-safe and is the shape expected by traces, audit records, Explain views, reporting export, and future event projectors.

## Boundaries

Policy modules are pure decision code. They do not write files, call providers, mutate runtime state, append audit records, or emit events.

Services keep side effects:

- HTTP handlers enforce RBAC decisions and write audit records.
- `QuotaPlannerService` evaluates usage, records ledger entries, and includes a `policy_decision` on every quota result.
- `DedicatedInferenceService` owns lifecycle state changes and provider calls, while `PolicyService` classifies budget, keep-alive, idle, and unhealthy decisions.
- Gateway metadata remains produced by the proxy path, and the facade can normalize it for Explain/reporting without changing routing internals.

## Precedence

RBAC route policy preserves the existing sensitive route maps. Unmapped routes are allowed by policy and still require a valid console identity when auth is enabled.

Quota precedence remains:

1. default policy
2. actor role policies
3. action policy
4. model policy, including wildcard model policy
5. project policy

Any hard block denies the request. Warnings are allowed and recorded.

Dedicated lifecycle precedence is:

1. inactive servers produce a no-op decision
2. unhealthy teardown due
3. idle teardown due
4. idle warning
5. within policy

Budget-critical Dedicated build decisions deny unless the service receives an explicit budget override, which is recorded in the decision `overrides` field.
