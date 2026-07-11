# Notification Center

The Console notification center provides a persistent operational inbox for
events that already exist elsewhere in the platform. It derives notifications
from source evidence on each load, then stores only operator state changes such
as acknowledged, resolved, notes, and actor metadata.

## Sources

Notifications are derived from:

- Open human review items.
- Provider health findings and model access issues.
- Failed release-candidate checks.
- Eval runs with failures.
- Automation rule executions and failed automation actions.
- Dedicated lifecycle warnings and failures.
- Dedicated budget threshold state and quota thresholds.
- Audit/security records such as denied or failed sensitive actions.

The source systems remain the source of truth. Resolving a notification closes
the inbox item, but it does not close the related review, fix a provider issue,
or change a release check.

## Schema

Each notification includes:

- `id`: deterministic source-derived identifier.
- `severity`: `low`, `medium`, `high`, or `critical`.
- `category`: review, provider, release, quality, automation, dedicated, cost,
  or security.
- `source`: compact source metadata.
- `status`: `new`, `acknowledged`, or `resolved`.
- `created_at`, `acknowledged_at`, and `resolved_at` timestamps.
- `actor`: the operator that last changed notification state.
- `evidence`: redacted supporting data.
- `links`: Console targets or source identifiers.

## Runtime State

The default state file is:

```text
$HOME/.cache/matts-value-set/studio/notifications.json
```

Override it with:

```bash
MATTS_NOTIFICATION_STATE_FILE=/path/to/notifications.json
```

The file stores state overrides and manual notification rows. Derived source
payloads are not copied into long-lived notification state.

## Retention

Resolved notification state is retained for 30 days by default. Old resolved
state is compacted during normal payload generation. New and acknowledged state
is retained so active operator triage is not lost.

## Redaction

Notification evidence redacts fields whose keys include token, secret,
password, authorization, api_key, access_key, messages, prompt, screen, raw, or
output. Long strings are truncated in displayed and stored notification data.

## Operator Workflow

Use Console > System Operations > Notification Center.

1. Filter by status, severity, or category.
2. Acknowledge an item when a human has accepted ownership.
3. Resolve an item only after the source issue is handled or intentionally
   closed elsewhere.
4. Reopen resolved items when a source issue still needs work.

High and critical notifications are also summarized in the Console overview
card.
