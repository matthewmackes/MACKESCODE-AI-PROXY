# Session Snapshots

AgentBoard can create a local diagnostic snapshot for a selected tmux session. The snapshot is written as both JSON and Markdown under the configured console runtime directory, defaulting to `session-snapshots` below the app cache.

## Contents

Snapshots include:

- session registry metadata
- AgentBoard status, prompt summary, and resource metrics
- recent trace records for the session
- matching audit records
- a capped tmux screen excerpt
- cost summary
- console health/status
- model registry and gateway policy fingerprints

The JSON artifact is for local automation. The Markdown artifact is for operator review and safe sharing after human inspection.

## Redaction

Snapshots redact common token patterns, bearer tokens, and secret-like fields such as token, secret, password, authorization, and API key. Long scalar text is truncated. Tmux output is capped to a short excerpt.

This is a guardrail, not a guarantee. Operators should review Markdown before sharing outside the trusted environment.

## API

Create a snapshot:

```bash
curl -X POST /api/v1/session-snapshots \
  -d '{"session":"matts-claude"}'
```

The response includes the snapshot payload and local file paths:

```json
{
  "files": {
    "json": ".../session-snapshots/matts-claude-snapshot_1000.json",
    "markdown": ".../session-snapshots/matts-claude-snapshot_1000.md"
  }
}
```

The route requires `tmux_control` permission.
