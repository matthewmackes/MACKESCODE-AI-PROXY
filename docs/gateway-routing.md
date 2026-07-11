# Gateway Routing Policy

The proxy gateway policy lives in `config/gateway-policy.json` and is loaded by
`do-anthropic-proxy.py`. If the file is missing or invalid, the proxy falls back
to built-in defaults and reports the policy state through
`/v1/claude-do/gateway-policy`.

The Console System Operations area shows the current policy and recent gateway
decisions from trace records.

## Policy Precedence

Request handling applies policy in this order:

1. Resolve model aliases.
2. Apply SLO routing when the request selects a router model or carries SLO
   metadata.
3. Apply gateway rate limits.
4. Apply configured budget blocks.
5. Reject unavailable or inaccessible models.
6. Check Dedicated lifecycle readiness.
7. Check cache and circuit-breaker state.
8. Call the provider and optionally fail over on configured retry statuses.

Explicit model requests remain explicit by default. SLO constraints are enforced
for explicit models only when `slo_routing.enforce_explicit_constraints` is true
or the request carries SLO metadata.

## SLO Router Models

The default router aliases are:

- `router:slo` uses `slo_routing.default_goal`
- `router:cheapest` chooses the lowest estimated request cost
- `router:fastest` chooses the lowest observed or configured latency
- `router:quality` chooses the highest configured quality score
- `router:context` chooses the largest context window that satisfies constraints

The selected provider model is written into `claude_do.upstream_model`.

## Constraints

`slo_routing.constraints` can set:

- `modality`
- `min_context_window`
- `max_estimated_cost_usd`
- `max_input_cost_per_mtok`
- `max_output_cost_per_mtok`
- `max_latency_ms`
- `require_tools`

The proxy estimates input tokens from reviewed request text and output tokens
from `max_tokens`. Cost checks use registry pricing. Context, modality, max
output, and tool support come from the model registry when available.

If no candidate satisfies the constraints, the proxy returns `409` before any
provider call.

## Routing Proof

SLO routing records an auditable proof containing the selected model, goal,
constraints, accepted/rejected candidates, rejection reasons, estimated cost,
context window, latency, error rate, and quality score.

Proof appears in:

- response `claude_do.slo_routing`
- local proxy logs
- trace `gateway_policy`
- Console chat Show Detail
- Console Gateway Decisions

Prompt and response text are not required for the proof.
