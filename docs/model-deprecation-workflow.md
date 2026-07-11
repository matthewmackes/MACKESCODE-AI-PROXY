# Model Deprecation Workflow

The model deprecation workflow helps move local artifacts away from models that should no longer be used.

## Deprecation States

A model is flagged when it is:

- `removed`: the provider catalog no longer lists it.
- `forbidden` or `unauthorized`: the active model access key cannot use it.
- `rate_limited`, `probe_failed`, or `repeated_probe_failed`: access is unstable and needs review.
- `superseded`: the registry points to a replacement model.
- `high_cost`: configured pricing exceeds the workflow threshold.
- explicitly marked with a `deprecation` object in the model registry.

Deprecated registry entries remain visible in Global Models, but route enablement blocks models with explicit deprecation states.

## Workflow

Use Console > Models > Deprecation Workflow:

1. Refresh the deprecation list.
2. Select a deprecated model and optional replacement.
3. Preview affected artifacts and recommendations.
4. Run a focused eval for critical routes when the preview recommends it.
5. Apply the migration.
6. Roll back by migration id if the replacement performs poorly.

## Affected Artifacts

The preview scans structured local data for model-id references:

- model registry
- gateway policy
- saved chats
- eval datasets and recent eval runs
- comparison reports
- v2 prompt templates and run profiles

Apply replaces structured references in mutable artifacts and marks the old registry entry disabled with deprecation metadata.

## Recommendations

Replacement recommendations use the model registry, route/access status, model type, scorecards, context window, and configured pricing. Measured scorecards are preferred, then lower listed cost.

## Rollback

Apply writes a migration record to:

`$HOME/.cache/matts-value-set/studio/model-deprecations.json`

The record includes backups of the registry and mutable affected artifacts. Rollback restores those backups and syncs the proxy registry.

## Limitations

The workflow replaces exact model-id text in structured JSON. It does not guarantee semantic equivalence, provider capacity, or identical output style. Operators should run evals for critical profiles before applying a migration to default routes.
