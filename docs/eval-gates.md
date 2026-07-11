# Eval-On-Change Gates

Eval gates protect risky prompt, model, and routing changes by recommending targeted datasets and, when policy requires it, blocking activation until recent eval evidence passes.

## Surfaces

The gate service supports these surfaces:

- `model_registry`: model enablement, access, pricing, route, or default-selection changes.
- `gateway_policy`: routing, failover, cache, rate-limit, SLO, and budget policy changes.
- `prompt_template`: prompt body, variables, examples, owner notes, and tags.
- `run_profile`: model, template, settings, tools, budget, gateway policy, and activation state.
- `eval_baseline`: baseline or dataset changes used by regression checks.

## Dataset Recommendation

`EvalGateService` compares canonical before/after payloads, hashes the changed state, and ranks datasets by surface keywords, changed field names, dataset metadata, and the `smoke` fallback dataset. The preview API returns the change summary, recommended datasets, required policy, and any matching evidence.

Legacy console:

- `GET /api/eval-gates?surface=model_registry`
- `POST /api/eval-gates`

V2 Run API:

- `POST /v2/run/eval-gates/preview`
- `GET /v2/run/eval-gates?target_id=...`

## Required Gates

Policy is permissive by default:

```json
{
  "require_pass": false,
  "min_pass_rate": 0.8,
  "max_failure_rate": 0.2,
  "max_age_seconds": 604800,
  "max_datasets": 3
}
```

Set `eval_gate.policy.require_pass` to `true` to require fresh passing evidence before a protected change is accepted. Evidence can match by explicit run id, recommended dataset id, or `change_gate.change_hash` written into an eval run.

Eval runs can link to a change:

```json
{
  "dataset_id": "gateway-routing",
  "models": ["deepseek-3.2"],
  "change_gate": {
    "surface": "gateway_policy",
    "change_hash": "sha256-from-preview",
    "target_id": "gateway-policy",
    "target_version": 1
  }
}
```

## Overrides

Overrides are accepted only when both an actor id and reason are present:

```json
{
  "eval_gate": {
    "policy": {"require_pass": true},
    "override": {
      "actor": {"id": "operator@example.com"},
      "reason": "Emergency failover repair"
    }
  }
}
```

Legacy model-registry saves write an audit record for allowed, denied, and override outcomes. V2 prompt-template and run-profile changes write `eval_gate_records` linked to the changed target id and version.
