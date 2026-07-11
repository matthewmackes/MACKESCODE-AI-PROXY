# Policy as Code

Policy as Code gives operators a single validated bundle for local governance policy. It covers RBAC, gateway routing, budgets, quotas, automation rules, and eval-gate defaults.

## Runtime Files

The policy bundle and history are runtime state:

```text
$HOME/.cache/matts-value-set/studio/policies.json
$HOME/.cache/matts-value-set/studio/policy-history.jsonl
```

The bundle can include every policy section. Active application is intentionally limited to file-backed sections that already have stable runtime ownership:

- `gateway` writes the gateway policy file.
- `budgets` writes the budget file.
- `automation` writes the automation rules file.

`rbac`, `quotas`, and `eval_gates` are exported, validated, fingerprinted, and stored in the bundle for governance review. They are not hot-applied to code-owned defaults or console startup configuration.

## Bundle Shape

```json
{
  "schema_version": 1,
  "policies": {
    "gateway": {"schema_version": 1},
    "budgets": {"daily_usd": 10, "monthly_usd": 100},
    "quotas": {"default_policy": {"daily": {"requests": 100}}},
    "automation": {"schema_version": 1, "rules": []},
    "rbac": {"schema_version": 1, "roles": {"viewer": ["view_console"]}},
    "eval_gates": {"schema_version": 1, "default_policy": {"require_pass": false}}
  }
}
```

## Workflow

Open System Operations, then Policy as Code.

Use:

- `Refresh Policies` to load the current bundle, current active policies, and recent history.
- `Preview` to validate JSON and compare section fingerprints before applying.
- `Apply` to store the bundle, write active file-backed sections, append history, and audit the change.
- `Rollback` to restore the previous bundle from policy history and reapply selected active sections.

## Validation

Validation blocks:

- unsupported bundle schema versions
- non-object policy sections
- non-numeric or negative budget values
- invalid automation rule container shape
- invalid RBAC role-permission shape
- secret-like keys in any policy section

Secret-like keys include token, secret, password, authorization, api_key, and access_key. Policy files should use env/file references for credentials, not inline secret values.

## Audit and Rollback

Each apply and rollback writes:

- policy bundle fingerprints
- changed section fingerprints
- policy history entries
- audit records with actor, sections, and target version

Existing config drift and rollback tooling can back up and restore the active files. The policy history file gives an additional bundle-level rollback path.
