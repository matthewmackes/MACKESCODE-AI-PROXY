# Session Resource Monitor

The console collects local resource metrics for live Claude/tmux sessions and shows them in session cards and AgentBoard. The monitor is local-only and degrades gracefully when tmux, `ps`, or disk statistics are unavailable.

## Metrics

For each live session, the monitor reports:

- tmux pane count and pane PIDs
- process-tree CPU percentage summed from pane root processes and children
- resident memory in MB summed from the same process tree
- maximum process age in seconds
- child process count
- command names only, without command arguments
- workspace filesystem usage
- generated-artifact size estimate for common local output folders

Common generated-artifact folders include `build`, `dist`, `frontend/dist`, `images`, and `.cache`.

## Warnings

Warnings are advisory and do not stop sessions:

- `runaway_cpu`: process tree CPU is at or above 250 percent
- `high_memory`: process tree RSS is at or above 2048 MB
- `stale_session`: session idle time is at or above four hours
- `low_disk_space`: workspace filesystem is at or above 90 percent used
- `large_artifacts`: generated artifacts are at or above 512 MB

## Platform Support

The monitor expects tmux and a POSIX-like `ps` command supporting:

```bash
ps -eo pid=,ppid=,pcpu=,rss=,etimes=,comm=
```

If a platform utility is unavailable, the payload includes `available: false` plus an `errors` list for the missing source. Other metrics continue to render when possible.

## Privacy

The monitor intentionally avoids command arguments because they can include prompts, file paths, tokens, or shell secrets. It reports command names such as `bash`, `python`, or `node`, aggregate metrics, PIDs, and workspace-level disk totals.

## Limits

CPU values are samples from `ps`, not time-series averages. Child process attribution follows the local parent PID tree at collection time and can miss short-lived processes. Disk usage is filesystem-level, while generated-artifact size is a bounded directory scan that may be marked truncated.
