# Rollback Wizard

The rollback wizard in Console > System Operations discovers local rollback
targets and provides a guided runtime-state restore flow.

Supported targets:

- runtime-state archives created by `scripts/runtime-state.py`
- V2 run-profile version history, surfaced as a link-out procedure to the React
  Run workspace rollback controls
- V2 prompt-template version history, surfaced as a link-out procedure to the
  React Run workspace rollback controls

Runtime-state rollback preview shows the archive items, current file state,
whether existing files will be moved aside, and whether the archive was created
with secrets included.

Applying a runtime-state rollback requires an audit reason. The wizard creates a
pre-rollback backup under the console runtime rollback backup directory before
restoring selected archive items. Existing files are moved aside with a
`.pre-rollback-*` suffix before restored files are copied into place.

After apply, the wizard returns console health, proxy sync, current config drift
summary, and the health validation command:

```bash
python3 scripts/health-validate.py
```

Use the full release, upgrade, backup, and rollback procedure in `RELEASE.md`
when rolling back production releases or when cloud/Dedicated state may be
affected.
