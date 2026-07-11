# Provider Health Dashboard

The Provider Health dashboard in Console > Ops combines provider status, local telemetry, account checks, model access state, proxy sync, and Dedicated lifecycle state.

## Signals

Sources include:

- DigitalOcean public status and unresolved incidents.
- DigitalOcean account and prepay balance checks when a token is configured.
- Model access-key configuration and Serverless access status from runtime model-access state merged with the model registry.
- Local trace telemetry: failures, rate-limit decisions, latency, and last successful request by model.
- Dedicated Inference lifecycle state, endpoint readiness, and token readiness.
- Local proxy listening and registry-sync state.

## Classification

Findings are classified as:

- `provider_outage`: DigitalOcean public status or incident impact.
- `auth_account_issue`: missing token, inactive account, unverified or unavailable access key, or Dedicated token readiness issue.
- `billing_issue`: prepay/balance status indicates payment attention.
- `model_access_issue`: merged model access state marks a model forbidden or unauthorized.
- `local_proxy_issue`: local proxy is offline or registry sync is stale.
- `rate_limit`: local traces show provider or gateway rate-limit decisions.
- `dedicated_endpoint_issue`: Dedicated endpoint failed, unhealthy, or not ready.

## Limits

Provider status is public, but account, model, trace, and Dedicated details require authenticated Console access. Local telemetry only reflects traffic routed through this proxy and can be stale when the proxy has not seen recent traffic for a model.

## Operator Actions

Findings link to the relevant operator action: retry key audit, sync registry, open Dedicated lifecycle, inspect DigitalOcean status, open billing reporting, or select a fallback route.
