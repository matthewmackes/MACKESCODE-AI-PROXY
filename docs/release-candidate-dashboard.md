# Release Candidate Dashboard

The Release Candidate dashboard in Console aggregates local readiness evidence
into blocking and advisory checks.

Blocking checks include:

- release-check artifacts and coverage threshold
- missing config-drift baseline or active medium/high/critical config drift
- high or critical open review items
- recent failed traces
- recent eval failures
- required governance/release documents

Advisory checks include:

- low-risk runtime drift, such as the tmux session registry changing during live Console/TUI validation
- operator-needed items from `docs/NEEDS-OPERATOR.md`
- remaining worklist scope

The payload and saved report also include `operator_handoff`, a structured
summary of open `docs/NEEDS-OPERATOR.md` rows. It keeps those items advisory so
code-complete readiness can stay green, while making live-cloud/account/release
decisions explicit for the human release review.

The dashboard does not run `scripts/release-check.sh` inside the web request.
Run the command from a shell, then refresh the dashboard so it can read coverage
artifacts and current local state:

```bash
scripts/release-check.sh
```

Generate Report writes a JSON snapshot under the console runtime release
candidate reports directory. Use the generated report with `RELEASE.md`,
`CHANGELOG.md`, and `docs/NEEDS-OPERATOR.md` during release review.
