# Provider Health Dashboard

The Provider Health dashboard in Console > Ops combines provider status, local telemetry, account checks, model access state, proxy sync, and Dedicated lifecycle state.

## Signals

Sources include:

- DigitalOcean public status and unresolved incidents.
- DigitalOcean account and prepay balance checks when a token is configured.
- DigitalOcean Monitoring API droplet metrics for the configured Dedicated host
  when a host/server id is available: CPU, memory available, load, and
  bandwidth over the last hour.
- DigitalOcean billed last-24-hour spend compared with the local proxy plus
  Dedicated runtime estimate when billing insights are available.
- Model access-key configuration and Serverless access status from runtime model-access state merged with the model registry.
- Local trace telemetry: failures, rate-limit decisions, latency, and last successful request by model.
- Dedicated Inference lifecycle state, endpoint readiness, and token readiness.
- Local proxy listening and registry-sync state.

## Classification

Findings are classified as:

- `provider_outage`: DigitalOcean public status or incident impact.
- `auth_account_issue`: missing token, inactive account, unverified or unavailable access key, or Dedicated token readiness issue.
- `billing_issue`: prepay/balance status indicates payment attention.
- `digitalocean_monitoring_gap`: Monitoring API data is unavailable or no host
  id is configured.
- `digitalocean_cpu_pressure`: recent Dedicated host CPU average is high.
- `model_access_issue`: merged model access state marks a model forbidden or unauthorized.
- `local_proxy_issue`: local proxy is offline or registry sync is stale.
- `rate_limit`: local traces show provider or gateway rate-limit decisions.
- `dedicated_endpoint_issue`: Dedicated endpoint failed, unhealthy, or not ready.

## Limits

Provider status is public, but account, model, trace, Monitoring API, billing,
and Dedicated details require authenticated Console access. Local telemetry only
reflects traffic routed through this proxy and can be stale when the proxy has
not seen recent traffic for a model. DigitalOcean billing can include charges
that did not pass through the proxy, so divergence is a triage signal rather
than proof of a local accounting error.

## Operator Actions

Findings link to the relevant operator action: retry key audit, sync registry, open Dedicated lifecycle, inspect DigitalOcean status, open billing reporting, or select a fallback route.
