# Cost Anomaly Detection

The console detects local cost and usage spikes from recent trace, eval, and Dedicated Inference telemetry. It is an operator warning system, not a billing authority.

## Signals

The detector compares the most recent 24-hour window against the previous seven daily windows. It checks:

- spend in USD
- token volume
- request count
- image-generation request count
- eval run count
- Dedicated runtime seconds
- Dedicated estimated runtime cost

Trace-based anomalies include the top attributed model, session, actor, route, and action when the trace contains those fields. Missing fields are reported as `unknown` rather than inferred from prompts or raw payloads.

## Thresholds

Default thresholds require the current window to exceed both a fixed minimum and three times the recent daily baseline. Fixed minimums avoid noise when the baseline is near zero:

- spend: `1.00` USD
- tokens: `20000`
- requests: `50`
- image requests: `10`
- eval runs: `5`
- Dedicated runtime: `3600` seconds
- Dedicated cost: `10.00` USD

When no baseline exists, the fixed minimum still applies. That makes first-day spikes visible while avoiding alerts for tiny usage.

## Operator Workflow

Open System Operations, then Cost Anomalies.

Use:

- `Acknowledge` when the spike is understood and should remain visible with notes.
- `Suppress` when the spike is accepted risk and should no longer appear as active.
- `Resolve` when the underlying cause has been fixed or the spike has ended.
- `Review` to convert the anomaly into a human review queue item with evidence.

Every acknowledgement, suppression, resolution, and review conversion appends an audit record. Active anomalies also feed the Notification Center as cost notifications with evidence links.

## Limitations

The detector uses local telemetry only. It can miss provider-side charges that did not pass through this console, and it can under-attribute older traces that lack actor, route, session, or cost fields. Dedicated cost is estimated from local runtime state and configured hourly rates, not from a live invoice.

## Runtime State

Operator anomaly decisions are stored in:

```text
$HOME/.cache/matts-value-set/studio/cost-anomalies.json
```

The file stores acknowledgement, suppression, resolution, notes, actor metadata, and update timestamps. It is runtime state and should not be release-owned.
