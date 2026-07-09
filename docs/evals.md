# Evaluation Workflows

Local eval datasets live in `evals/*.json`. Eval run history is written to the local studio state directory under `eval-runs/`.

## Dataset Format

```json
{
  "schema_version": 1,
  "id": "smoke",
  "name": "Smoke Eval",
  "description": "Short routing and answer-quality checks.",
  "examples": [
    {
      "id": "reply-ok",
      "input": "Reply only with the word ok.",
      "expected": "ok",
      "tags": ["smoke", "format"]
    }
  ]
}
```

Each example needs an `id` and `input`. `expected` is optional; when present, the runner scores exact matches as `1.0`, contained answers as `0.75`, and misses as `0.0`.

## Running Evals

Open Console > AgentBoard > Evals, select a dataset, select one or more available text models, optionally choose a baseline run, and run the eval.

Results include:

- per-model cost, average latency, failure count, and pass rate
- per-example answers for each model
- selected answer per example
- trace IDs when the underlying chat request emitted one
- baseline deltas for cost, latency, failures, and pass rate when a baseline run is selected

The API equivalent is:

```bash
curl -X POST http://127.0.0.1:18181/api/evals/run \
  -H 'content-type: application/json' \
  -d '{"dataset_id":"smoke","models":["qwen3-coder-flash"],"max_examples":2}'
```

## Create Comparisons

Create > Advanced Settings includes a multi-model comparison selector. It supports one to five available text models. The platform rejects unavailable models before routing any request, then saves the full comparison as one chat history entry.
