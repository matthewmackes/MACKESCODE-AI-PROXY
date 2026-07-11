# Config Drift Detector

The config drift detector compares active runtime and governance state against a
local last-known-good baseline. The baseline is stored under the console runtime
directory as `config-drift-baseline.json` by default, or at
`MATTS_CONFIG_DRIFT_BASELINE_FILE` when that environment variable is set.

Tracked surfaces:

- active model registry
- gateway policy
- console config
- Dedicated Inference state
- budget limits
- quota ledger
- auth session state
- tmux session registry
- role-token policy summary

Role-token drift records a redacted summary only: source, profile ids, role
names, and permission counts. It does not store role token values.

## Baselines

Mark a new baseline only after a successful release check, health validation, or
explicit operator review. Baseline changes are written to the audit log with the
actor, reason, label, and tracked item names.

Acknowledging drift does not update the baseline. It records that the current
fingerprint for one or more changed items has been reviewed, while the drift
remains visible in the Console.

Release-candidate readiness uses drift risk when deciding whether to block:
missing baselines and active medium/high/critical drift remain blocking, while
only-low-risk runtime drift is reported as an advisory. This keeps expected
state churn such as tmux session registry updates visible without making an
otherwise healthy live validation look unreleasable.

## Rollback

Use runtime-state archives for restore operations:

```bash
python3 scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz
python3 scripts/runtime-state.py restore <archive>
```

Inspect the archive manifest before restoring. The restore command moves
existing files aside unless `--overwrite` is used.
