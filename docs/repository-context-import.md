# Repository Context Import

Repository context import lets an operator preview a GitHub issue or pull request and add the bounded, redacted context to a Claude Code session prompt.

## Connector Setup

Set one of these environment variables before starting the Console:

```bash
export GITHUB_TOKEN=github_pat_...
# or
export GH_TOKEN=ghp_...
```

The token needs read access to the target repository. Public issues and pull requests still require a token for the current connector so API errors and rate limits are explicit.

## Supported References

The importer accepts:

- `https://github.com/owner/repo/issues/123`
- `https://github.com/owner/repo/pull/123`
- `owner/repo#123`

When a token is missing or GitHub cannot be reached, the preview degrades to parsed reference metadata and a warning. It does not block normal Code sessions.

## Preview And Import Flow

1. Open the Code session wizard.
2. Enter an issue or PR reference in Repository Context.
3. Select Preview Context.
4. Review the exact prompt text that will be added.
5. Select Import To Prompt.
6. Start the session in print, JSON, stream JSON, or background mode when you want the imported context sent as the initial task prompt.

Import also attaches compact metadata to the tmux session record and trace:

- provider, owner, repo, number, title, URL
- PR head SHA when available
- changed file names and status
- check names and conclusions
- linked worklist lines

## Included Context

For pull requests, the preview includes title, body summary, labels, assignees, base/head branch, changed files, check runs, issue comments, reviews, review comments, links, and matching worklist lines.

For issues, the preview includes title, body summary, labels, assignees, comments, links, and matching worklist lines.

## Privacy Boundaries

The importer never stores GitHub credentials in session metadata, traces, or snapshots. Token-like strings in bodies, comments, patches, and diagnostics are redacted. Long text is truncated before it is added to the prompt preview.

Session snapshots include imported repository metadata in JSON and Markdown, but not the full credential-bearing connector response.
