# Automation Rules

The Console automation rules service lets operators match local operational events
and run bounded actions. Rules are stored as runtime state, not release-owned
configuration, because they can contain site-specific webhook destinations and
secrets.

## Runtime Files

By default, automation state is stored under the Console app cache:

- `automation-rules.json` contains enabled rules and webhook settings.
- `automation-executions.jsonl` contains redacted execution records.

The paths can be overridden with:

- `MATTS_AUTOMATION_RULES_FILE`
- `MATTS_AUTOMATION_EXECUTION_LOG_FILE`

## Rule Shape

Rules are managed from Console > System Operations > Automation Rules as JSON:

```json
{
  "rules": [
    {
      "id": "eval-failure-review",
      "name": "Eval failure review",
      "enabled": true,
      "trigger": {
        "event": "eval_failure",
        "source": "eval",
        "min_severity": "high",
        "field_equals": {
          "model": "deepseek-3.2"
        }
      },
      "actions": [
        {
          "type": "create_review",
          "severity": "high",
          "reason": "eval_failure"
        },
        {
          "type": "audit_event",
          "action": "automation.eval_failure"
        },
        {
          "type": "webhook",
          "url": "https://example.invalid/matts-webhook",
          "secret": "replace-with-shared-secret",
          "max_retries": 2,
          "timeout_seconds": 5
        }
      ]
    }
  ]
}
```

Supported trigger fields:

- `event`: exact event name, or `*` for any event.
- `source`: optional exact source match.
- `min_severity`: `low`, `medium`, `high`, or `critical`.
- `field_equals`: dotted event-field equality checks.
- `schedule`: optional interval metadata for operator-triggered scheduled
  dispatch. Use `interval_seconds`, plus optional `event`, `source`, and
  `severity`.

Recommended event names:

- `eval_failure`
- `budget_threshold`
- `dedicated_idle`
- `dedicated_unhealthy`
- `provider_outage`
- `model_access_change`
- `review_created`
- `release_check_failure`

## Actions

Supported action types:

- `create_review`: creates a human review item with redacted event evidence.
- `audit_event`: writes a named audit event.
- `session_snapshot`: writes a one-click AgentBoard session snapshot when the
  event includes a session identifier.
- `dedicated_event`: writes a Dedicated lifecycle event.
- `webhook`: sends a signed, redacted JSON payload to an HTTP(S) endpoint.
- `run_eval`: dispatches an eval run with `dataset_id`, `models`, and optional
  payload fields.

Scheduled evals use the same rule/action shape as event-driven evals:

```json
{
  "id": "scheduled-smoke-eval",
  "enabled": true,
  "trigger": {
    "event": "eval.scheduled",
    "source": "schedule",
    "schedule": {
      "interval_seconds": 3600,
      "event": "eval.scheduled",
      "source": "schedule"
    }
  },
  "actions": [
    {
      "type": "run_eval",
      "dataset_id": "smoke",
      "models": ["deepseek-3.2"]
    }
  ]
}
```

Use the Test Event button before Run Event. Test mode records the matching result
and planned actions without creating reviews, snapshots, Dedicated events, or
webhook calls.

## Webhook Security

Webhook delivery sends JSON with:

- `execution_id`
- redacted `event`
- `rule_action` metadata with the webhook URL

The request includes:

- `x-matts-event`
- `x-matts-timestamp`
- `x-matts-signature`

The signature is `sha256=` plus an HMAC-SHA256 digest over:

```text
<timestamp>.<json-body>
```

Use the webhook action `secret` as the HMAC key. The Console redacts webhook
secrets when rules are displayed and preserves the stored secret if a redacted
placeholder is saved back unchanged. Rotate a secret by replacing the placeholder
with the new value.

Webhook payloads redact fields whose keys include token, secret, password,
authorization, api_key, access_key, messages, prompt, screen, raw, or output.
Long strings are truncated in logs. Treat redaction as a guardrail, not a reason
to send unnecessary sensitive data.

## Permissions And Audit

Automation management is guarded by the `automation_admin` permission. Rule
saves, test runs, and real runs are written to audit logs. Execution records are
visible in the Console and redacted before storage.

Keep rules small and explicit:

- Prefer narrow event names and source matches.
- Use `min_severity` for noisy signals.
- Keep webhook retries low.
- Use human review actions for irreversible or expensive operations.
- Use Test Event after every rule edit.
