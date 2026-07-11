# CI Failure Triage

CI failure triage uses the repository context connector to summarize failed GitHub checks and preload a Claude Code fix session.

## Setup

Configure the same GitHub token used by repository context import:

```bash
export GITHUB_TOKEN=github_pat_...
# or
export GH_TOKEN=ghp_...
```

The token needs read access to pull requests, checks, files, comments, and reviews for the target repository.

## Workflow

1. Open Console > System Operations > CI Failure Triage.
2. Enter a GitHub issue or pull request reference.
3. Preview the triage result.
4. Review failed checks, suspected failure category, log excerpt, and likely affected files.
5. Select Start Fix Session to preload the Code session wizard with CI context.

The launch action does not store credentials. It adds a redacted CI prompt to the visible task prompt and stores compact metadata with the session and trace.

## Failure Classification

The panel classifies failed checks through the shared failure taxonomy. Examples include malformed tool calls, context overflow, rate limits, provider outages, access failures, and local proxy issues. The category is a hint, not a guarantee; operators should still inspect logs and changed files.

## Privacy

Check output is truncated before display. Token-like strings are redacted by the repository context importer. Session records and snapshots store check names, conclusions, changed file names, and categories, not GitHub credentials or full raw API responses.

## Limitations

The current connector uses GitHub check-run summaries and output text. It does not download full GitHub Actions job logs yet. Missing tokens or API failures degrade to a limited reference-only preview.
