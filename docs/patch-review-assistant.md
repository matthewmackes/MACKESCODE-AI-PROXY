# Patch Review Assistant

The patch review assistant gives an operator a local summary of the current git
worktree before exporting, committing, or opening a PR. It is designed for
Claude Code sessions where the console needs a quick review packet without
shipping raw changes to an external service.

## Console Flow

1. Open Console > AgentBoard.
2. Select a tmux session.
3. Click `Patch Review`.
4. Review the changed files, risk notes, test suggestions, documentation impact,
   unresolved concerns, suggested commit message, and suggested PR description.
5. Run the listed tests and update the commit or PR text before publishing.

The API endpoint is `POST /api/patch-review`. The request can include:

```json
{
  "session": "claude-work",
  "project_dir": "/path/to/repo",
  "include_snapshot": false
}
```

When `project_dir` is omitted, the service uses the selected session project
directory when available, then falls back to the console project directory.

## Summary Contents

The response includes:

- changed file paths, git status, additions, deletions, area, and kind
- highest-risk classification and risk details
- changed test files and suggested verification commands
- documentation and governance impact hints
- unresolved concerns such as missing direct tests or no detected changes
- suggested commit message and PR description template
- related trace IDs for the selected session
- optional snapshot file references when snapshot generation is requested

## Privacy And Limits

Patch review is local-only. It runs git commands in the target repository and
does not commit, push, export, or call a hosted LLM. Diff excerpts are truncated
and token-like strings are redacted before returning to the browser.

The summary is heuristic. It cannot prove that all tests ran, infer every
behavioral change, or validate cloud-side effects. Operator review remains
required before publishing changes.
