# Release, Upgrade, And Rollback

This project separates release-owned files from runtime state. A release should be testable from a clean checkout, upgradeable on an existing host, and rollback-safe when Dedicated Inference or local runtime data exists.

## Release Gate

Run this before tagging, packaging, or pushing a release branch:

```bash
scripts/release-check.sh
```

The gate runs:

- Python unit and smoke tests
- line-hit coverage report
- Python syntax checks
- template JavaScript syntax check when `node` is available
- headless browser smoke when Playwright is installed

For CI or strict local validation:

```bash
MATTS_BROWSER_SMOKE_REQUIRED=1 scripts/release-check.sh
```

## Clean Checkout Verification

From a fresh clone:

```bash
./claude-DO.sh --list-models
python3 -m unittest tests.test_console_smoke.TemplateSmokeTests
```

`--list-models` must return the active route-enabled model registry without requiring a model access token.

## Runtime-State Backup

Before upgrade or rollback, stop write-heavy activity and create a backup:

```bash
scripts/runtime-state.py backup --output build/runtime-state-$(date +%Y%m%d-%H%M%S).tar.gz
```

The default archive includes:

- active model registry
- gateway policy
- Dedicated Inference runtime state and lifecycle events
- audit log
- Serverless catalog cache
- trace log
- tmux session registry
- image history, generated images, and saved chats
- eval runs
- usage logs and budgets
- wallpaper cache

Token files are excluded by default. To include secrets for a controlled host migration:

```bash
scripts/runtime-state.py backup --include-secrets --output secure-runtime-state.tar.gz
```

Store secret-bearing archives outside the repository.

## Upgrade Procedure

1. Run `scripts/release-check.sh` on the target release.
2. Create a runtime-state backup.
3. Stop local Console and proxy services or tmux sessions.
4. Update the working tree or installed package.
5. Preserve runtime paths:
   - `config/models.json` or `MATTS_MODEL_CONFIG_FILE`
   - `$HOME/.cache/matts-value-set/studio/dedicated-inference.json`
   - `$HOME/.cache/matts-value-set/studio/tmux-sessions.json`
   - `$HOME/.cache/matts-value-set/usage.jsonl`
   - `$HOME/.cache/matts-value-set/budgets.json`
6. Start the proxy and Console.
7. Run health validation:

```bash
scripts/health-validate.py
```

If Console is up but proxy is intentionally offline:

```bash
scripts/health-validate.py --allow-degraded-console
```

8. Open Console > LLM Management and confirm registry/proxy sync.
9. Open Console > Inference Hosting Lifecycle and confirm Dedicated state, idle policy, and cost counters.

## Rollback Procedure

1. If Dedicated Inference is active and the rollback cannot serve it safely, tear it down from Console or the DigitalOcean control plane before reverting.
2. Stop services.
3. Restore the previous release checkout or package.
4. Restore runtime state:

```bash
scripts/runtime-state.py restore build/runtime-state-YYYYMMDD-HHMMSS.tar.gz
```

Existing files are moved aside with a `.pre-restore-<timestamp>` suffix unless `--overwrite` is supplied.

5. Restart services.
6. Run `scripts/health-validate.py`.
7. Send a small chat request and inspect `Show Detail` to verify requested model, routed model, backend, trace ID, and cost metadata.

## Release Notes Template

Use this structure in `CHANGELOG.md` for release entries:

```markdown
## vX.Y.Z - YYYY-MM-DD

### Added
- 

### Changed
- 

### Fixed
- 

### Migration Notes
- Runtime state impact:
- Config changes:
- Dedicated Inference impact:
- Rollback note:

### Verification
- `scripts/release-check.sh`
- clean checkout `./claude-DO.sh --list-models`
- `scripts/health-validate.py`
```
