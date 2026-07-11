# Contributing

Read `GOVERNANCE.md` before changing load-bearing behavior. It defines the
source-of-truth model registry, runtime-state boundaries, security/cost locks,
and definition of done.

The standard release gate is:

```bash
scripts/release-check.sh
```

It runs unit/smoke tests, coverage reporting, Python syntax checks, template
JavaScript syntax checks when `node` is installed, and browser smoke when
Playwright is available. CI requires browser smoke.

For proxy changes, verify:

- `/v1/models` exposes only the current MDE LLM-PROXY models and aliases.
- `/v1/messages` translates Claude Code requests to DigitalOcean chat completions.
- `/v1/images/generations` still routes Stable Diffusion requests.
- cost and budget endpoints keep returning valid JSON.

For UI changes, verify the rendered interface with browser smoke or a focused
Playwright check. Template syntax alone is not enough for tab/navigation work.

For security, governance, cost, routing, release, or live-cloud lifecycle
changes, update the relevant document:

- `docs/DECISIONS.md` for durable architecture/policy decisions
- `docs/NEEDS-OPERATOR.md` for live-resource or operator-decision blockers
- `docs/THREAT_MODEL.md` and `SECURITY.md` for security posture changes
- `docs/COMPLIANCE.md` for integrity sweeps and FINISH/REMOVE findings

Do not commit runtime state, model access keys, DigitalOcean tokens, console
tokens, traces, usage logs, live Dedicated endpoint metadata, generated images,
or tmux session registries.
