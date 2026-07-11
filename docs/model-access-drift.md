# Model Access Drift

Model access drift detects when a Serverless text model that previously probed
successfully for the active model access key later becomes unavailable.

The Console persists prior audit results by model id and key fingerprint in:

```text
$HOME/.cache/matts-value-set/studio/model-access-drift.json
```

Set `MATTS_MODEL_ACCESS_DRIFT_FILE=/path/to/model-access-drift.json` to use a
different runtime file.

## Drift Conditions

The drift detector records active events for:

- `forbidden`: a previously allowed model now returns 401 or 403.
- `rate_limited`: a previously allowed model now returns 429.
- `probe_failed`: a previously allowed model now fails the runtime probe.
- `repeated_probe_failure`: probe failures continue across audits.
- `removed`: DigitalOcean no longer lists a previously allowed Serverless model.
- `restored`: a previously drifted model probes successfully again.

Forbidden and removed models are disabled in the registry. Rate-limited and
probe-failed models keep their registry rows, but Serverless text routing only
offers models whose `access_status` is `ok`, so selectors and router choices
stop using unusable models until a later successful audit restores them.

## Operator Workflow

1. Run Console > LLM Management > `Audit Key`.
2. Review allowed, blocked, skipped, and access drift counts.
3. Open Console > System Operations > Provider Health for active drift findings.
4. Use `Retry access audit` after fixing key scope, provider issues, or account
   state.
5. Use `Acknowledge access drift` when the event is understood and no longer
   needs to page the operator.
6. Use `Sync Proxy` after registry changes if the proxy is not already synced.

Provider Health emits drift findings, and the Notification Center turns those
findings into persistent provider notifications until they are acknowledged or
resolved.
