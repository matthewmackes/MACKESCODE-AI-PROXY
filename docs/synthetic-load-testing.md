# Synthetic Load Testing

Synthetic load testing sends bounded, real requests through the existing chat route to measure operational behavior before heavier use.

## What It Measures

Each run records:

- request count
- success and error counts
- error rate and error categories
- latency min, average, p50, p95, and max
- total estimated cost from returned payloads
- requests per second
- route and failover distribution
- trace ids when returned by the route

Runs are stored as runtime state:

```text
$HOME/.cache/matts-value-set/studio/synthetic-load-runs.jsonl
```

## Safety Limits

The local runner is intentionally sequential.

Hard limits:

- max requests: `50`
- max concurrency: `1`
- max duration: `120` seconds
- max budget cap: `5.00` USD

The preview step estimates cost with the existing forecast service and checks quota policy before any provider request is sent. A run is blocked if the selected model is unavailable, the request exceeds hard limits, quota policy denies it, or the forecast exceeds the run budget cap.

## Workflow

Open System Operations, then Synthetic Load Tester.

Use:

- `Preview` to validate model availability, limits, forecast, and quota impact.
- `Run Load Test` to send the bounded sequence after explicit confirmation.
- `Refresh Runs` to reload recent run history.

## Provider Risk

Synthetic load tests consume real provider capacity, quota, and budget. They can also trigger upstream rate limits or skew short-term provider-health metrics. Keep request counts low, run against a narrow model set, and prefer off-peak windows when testing expensive or unstable routes.

## Audit and Trace Evidence

Every completed run writes:

- a synthetic load run record
- an audit record with actor, request shape, and run id
- a compact trace summary with aggregate cost and error category data

Raw prompt content is limited to the local run request and should be kept generic. Do not use sensitive prompts for load testing.
