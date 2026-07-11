# Model Quality Scorecards

Model scorecards combine static registry facts with recent runtime evidence so
operators can compare models without reading raw traces or eval run files.

## Sources

Scorecards use:

- model registry metadata: type, provider, route, context window, max output
  tokens, tool support, pricing, enabled state, and access status
- trace records: request count, error rate, cost, average latency, p95 latency,
  and cost per successful request
- eval run summaries: pass rate, failure rate, average latency, request count,
  and eval cost
- local usage summaries: recent local spend by model

The `/api/model-scorecards` endpoint returns scorecards for enabled and disabled
registry models. The same scorecard map is included in `/api/models` so model
selection and LLM Management can display score and confidence without hidden
state.

## Confidence

Each scorecard has a `confidence` field:

- `measured`: recent trace or eval samples are available
- `stale`: samples exist but the latest measurement is older than the stale
  threshold, currently seven days
- `unavailable`: no trace or eval evidence was found in the requested window

The UI keeps these states visible. A low or unavailable score should be treated
as a prompt to run a smoke test or eval, not as proof that the model is bad.

## Score

The score is a bounded 0-100 operational quality indicator. Eval pass rate has
the largest effect when eval data exists. Trace error rate, latency, and low
sample count adjust the score. Models with no samples score `0` and show
`unavailable` confidence.

Scorecards are advisory. Gateway policy and explicit operator model selection
remain the source of truth for routing decisions.
