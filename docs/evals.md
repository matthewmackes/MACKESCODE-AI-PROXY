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
      "tags": ["smoke", "format"],
      "metadata": {
        "source_type": "manual"
      }
    }
  ]
}
```

Each example needs an `id` and `input`. `expected` is optional; when present, the runner scores exact matches as `1.0`, contained answers as `0.75`, and misses as `0.0`.

Dataset and example `metadata` objects are optional. Builder-created examples use
metadata to preserve reviewed source context such as source type, trace ID, chat
ID, requested/routed model, routing reason, and cost. Metadata is not sent to
models during eval runs; only `input` is used as the user prompt.

## Dataset Builder

Operators can create or edit datasets through the dataset APIs. Manual examples
can be saved directly:

```bash
curl -X POST http://127.0.0.1:18182/v2/operate/evals/datasets \
  -H 'content-type: application/json' \
  -d '{"id":"manual","name":"Manual","examples":[{"input":"Reply ok","expected":"ok"}]}'
```

Runtime-derived examples from traces, saved chats, and comparison runs must pass
an explicit redaction review before saving:

```bash
curl -X POST http://127.0.0.1:18182/v2/operate/evals/datasets/build \
  -H 'content-type: application/json' \
  -d '{
    "id": "from-trace",
    "name": "From Trace",
    "operator_notes": "Reviewed and redacted by operator",
    "examples": [{
      "source_type": "trace",
      "redaction_reviewed": true,
      "input": "Redacted user goal",
      "expected": "Expected behavior",
      "trace": {
        "trace_id": "trace_123",
        "requested_model": "deepseek-3.2",
        "routed_model": "deepseek-3.2",
        "routing_reason": "selected",
        "cost_usd": 0.002
      },
      "tags": ["trace", "regression"]
    }]
  }'
```

The builder rejects `trace`, `chat`, and `comparison` examples unless
`redaction_reviewed` is true. The reviewed `input` should be a sanitized prompt
that keeps the behavior under test while removing secrets, customer data, and
irrelevant transcript detail.

Builder-created datasets are still plain `evals/*.json` files and can be run by
the existing eval runner without a separate conversion step.

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
curl -X POST http://127.0.0.1:18182/v2/operate/evals/run \
  -H 'content-type: application/json' \
  -d '{"dataset_id":"smoke","models":["qwen3-coder-flash"],"max_examples":2}'
```

## Create Comparisons

Create > Advanced Settings includes a multi-model comparison selector. It supports one to five available text models. The platform rejects unavailable models before routing any request, then saves the full comparison as one chat history entry.
