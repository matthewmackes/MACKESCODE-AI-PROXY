# Golden Path Onboarding

The golden path checklist appears in Console > System Operations. It is intended
for first-run setup and for catching incomplete host configuration after an
upgrade or restore.

## What It Checks

- model access token file or configured model access source
- optional DigitalOcean token paths for billing, Serverless catalog refresh, and
  Dedicated Inference actions
- local proxy reachability and registry sync
- model access audit evidence from available text models
- budget limits
- console auth and scoped role-token setup
- release-check and browser-smoke command readiness
- runtime-state backup availability
- Dedicated Inference state
- Serverless catalog or selectable model readiness

Each row includes a status, redacted evidence, and a guided action. Token values
are never returned to the browser; only configured/missing state and candidate
paths are shown.

## Completion State

Operators can mark checklist rows done after completing external or manual
steps. Completion state is stored in the console runtime cache:

```text
$HOME/.cache/matts-value-set/studio/onboarding.json
```

The state file is runtime-owned data. Do not commit it. Set
`MATTS_ONBOARDING_STATE_FILE` when a headless host needs a different runtime
location.

## Headless Host Flow

1. Write the model access key to `$HOME/.mcnf-do-model-access-token`, or set
   `MATTS_VALUE_SET_ACCESS_KEY` for a deliberate one-time setup.
2. Start the console with `./matts-console.py --no-open`.
3. Open the printed token-protected URL from a workstation browser.
4. Open System Operations and refresh Golden Path Onboarding.
5. Run model access audit, configure budgets, add scoped role tokens, run
   `./scripts/release-check.sh`, and create a runtime-state backup.
6. Mark rows done only after the action has been completed or consciously
   deferred.

The checklist is advisory. It does not run destructive actions, write token
files, start cloud resources, or perform commits.
