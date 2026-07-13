# Runtime JSONL Retention

The three append-per-request runtime logs — `usage.jsonl` (cost file), `traces.jsonl`, and the proxy request log — have bounded growth via size-based rotation (`src/console/services/retention.py`).

## Policy

- Trigger: a file exceeding **32 MB** is rewritten to its last **8 MB**, aligned to a line boundary so every retained row is complete.
- Archive: the trimmed head is gzip-compressed to a sibling `<name>.1.jsonl.gz` (for example `usage.1.jsonl.gz`). The archive is **single generation** — each rotation overwrites the previous one.
- Replacement is atomic (temp file + `os.replace`), preserving file permissions; readers always see a complete old or new file.

## Where it runs

The V2 console's headless background worker (`dedicated_policy_worker` in `image-studio.py`) sweeps at most once every 10 minutes; between sweeps and rotations the cost is one timestamp check plus cheap `stat` calls. File paths come from the same runtime-config resolvers the console already uses (`cost_file`, `trace_file`, `log_file`), so config or env path overrides are honored. The proxy needs no writer-side hook: it reopens the log path on every append and covers the shared files through the console-side sweep.

## Operator knobs

| Env | Default | Meaning |
| --- | --- | --- |
| `MATTS_RETENTION_MAX_BYTES` | `33554432` (32 MB) | Size that triggers rotation |
| `MATTS_RETENTION_KEEP_BYTES` | `8388608` (8 MB) | Line-aligned tail kept in the live file |

Invalid or non-positive values fall back to defaults; a keep size at or above the trigger is clamped to a quarter of it.

## Correctness across rotation

- The proxy's incremental budget aggregator detects the inode change from `os.replace` and re-seeds from the rotated file; console usage/analytics caches key on `(mtime, size)` and invalidate naturally. Covered by `tests/test_retention_service.py`.
- Console-side writers (traces, audit) are serialized with rotation through the shared sidecar `<name>.lock` flock. The proxy appends without that lock, so a handful of rows appended during the instant of rotation can be lost — an accepted tradeoff for an operator-local log (documented in the module docstring).
- After rotation, "all time" and old-window totals computed from the live file reflect only the retained ~8 MB window (roughly tens of thousands of requests); daily and monthly budget enforcement is unaffected as long as the kept window covers the period. Trimmed history remains inspectable in the `.1.jsonl.gz` archive.
