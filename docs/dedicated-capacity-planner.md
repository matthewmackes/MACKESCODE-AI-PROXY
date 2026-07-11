# Dedicated Capacity Planner

The Dedicated capacity planner estimates whether a DigitalOcean Dedicated Inference build is worth creating before the console sends the build request.

## Inputs

The planner combines:

- Dedicated build fields from the Console lifecycle form: region, model slug, accelerator slug, scale, hourly price, daily budget, idle teardown window, and fallback model.
- Local Serverless usage from the last 24 hours, unless the request provides `projected_serverless_daily_usd`.
- DigitalOcean Dedicated discovery endpoints for available sizes and GPU/model configuration when `DIGITALOCEAN_TOKEN` is configured.
- Provider health data for account, billing/prepay, platform, and incident signals.
- Current model registry state through the existing Dedicated lifecycle payload.

## Cost Model

Dedicated cost is calculated from the configured `price_per_hour`.

- Hourly: configured hourly price.
- Daily: hourly price multiplied by 24.
- 30-day estimate: hourly price multiplied by 720.
- Idle teardown exposure: hourly price multiplied by the configured teardown window.
- Break-even point: Dedicated daily cost compared with projected daily Serverless spend.

The planner does not fetch a committed invoice price for a future Dedicated build. Operators should treat the hourly price as an estimate until DigitalOcean accepts the build and billing data settles.

## Recommendations

The planner returns one of four recommendations:

- `build`: preflight passes, live capacity/model fit is visible, pricing is present, and Dedicated is projected to be cheaper than Serverless.
- `prefer_serverless`: Dedicated is more expensive than projected Serverless usage.
- `review`: the build is not blocked, but pricing, capacity, fit, or billing confidence needs operator review.
- `blocked`: preflight fails or the DigitalOcean token is missing.

The Console renders the planner before Dedicated build confirmation. The build request also carries the rendered plan in `capacity_plan` for operator context.

## Uncertainty

Capacity can be uncertain when:

- `DIGITALOCEAN_TOKEN` is missing.
- Dedicated sizes or GPU/model config discovery fails.
- The selected accelerator or model slug is not present in the discovery payload.
- The selected region is outside the currently documented Dedicated Inference regions: `atl1`, `nyc2`, and `tor1`.
- Account, prepay, or platform health signals indicate risk.

DigitalOcean can still reject or delay capacity after a plan looks valid. The planner is a pre-build decision aid, not a reservation system.

## API

`POST /api/dedicated/capacity-plan` accepts the same form fields as Dedicated build/preflight plus optional `projected_serverless_daily_usd`.

The response includes:

- `recommendation`
- `cost`
- `serverless_comparison`
- `capacity`
- `readiness`
- `fallback`
- `uncertainty_notes`
- `live_discovery`

The route requires the `dedicated_admin` permission.
