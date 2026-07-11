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
- generated V2 OpenAPI/client freshness checks
- React frontend build when `npm` is available, using `npm ci --no-audit` if `frontend/package-lock.json` is present and dependencies are missing
- V2 frontend bundle-boundary and production dependency audit checks
- V2 health validation and headless browser smoke when Playwright is installed, including the V2 Console TUI bridge

The V2 launcher, V2 browser smoke, and release gate treat `frontend/package-lock.json` as authoritative. On clean hosts, missing `frontend/node_modules` is restored with `npm ci --no-audit`; plain `npm install --no-audit` is only a no-lockfile fallback. Install steps intentionally skip npm's implicit audit output because the release gate runs the explicit production audit check below.

The frontend audit gate intentionally checks shipped dependencies with `npm audit --omit=dev`. A full `npm audit` can still report Vite/esbuild development-server advisories on hosts using the current Node 16 toolchain; the first Vite releases that clear those advisories require Node 18+ or Node 20+. Treat the Vite dev server as a trusted local development tool until the project baseline moves to a newer Node runtime, and do not expose it as production infrastructure.

For CI or strict local validation:

```bash
MATTS_BROWSER_SMOKE_REQUIRED=1 scripts/release-check.sh
```

## Clean Checkout Verification

From a fresh clone:

```bash
./claude-DO.sh --list-models
python3 -m unittest tests.test_v2_app_launcher tests.test_v2_openapi_generation
```

`--list-models` must return the active route-enabled model registry without requiring a model access token; the V2 launcher/OpenAPI checks must prove the current console can start from the checkout.

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
- auth sessions
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
6. Start the proxy and V2 Console.
   - Proxy: use the existing `claude-DO.sh` path or run `do-anthropic-proxy.py` directly on `127.0.0.1:18081`.
   - V2 console: run `python3 matts-v2-console.py --host 127.0.0.1 --port 18182`; add `--build-frontend` to force a React rebuild before FastAPI starts.
7. Run health validation:

```bash
scripts/health-validate.py
```

The default validator checks the React/FastAPI V2 console (`/v2/health` and the
React shell on port `18182`) and the proxy. Use `--v2-only` when validating a V2
endpoint in isolation.

If Console is up but proxy is intentionally offline:

```bash
scripts/health-validate.py --allow-degraded-console
```

8. Open Console > LLM Management and confirm registry/proxy sync.
9. Open Console > Inference Hosting Lifecycle and confirm Dedicated state, idle policy, and cost counters.
10. Review the Release Candidate dashboard. Missing drift baselines and active
    medium/high/critical config drift block readiness; only-low-risk runtime
    drift, such as tmux session registry churn from live Console/TUI validation,
    is advisory and should be reviewed rather than treated as an automatic
    release stop.

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
