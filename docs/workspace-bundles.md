# Workspace Bundles

Workspace bundles are operator-created JSON exports for moving local Console
workspace artifacts between machines or preserving a point-in-time working set.
They are stored outside release-owned config by default:

```text
$HOME/.cache/matts-value-set/studio/workspace-bundles/
```

Set `MATTS_WORKSPACE_BUNDLES_DIR=/path/to/bundles` to use another runtime
directory.

## Bundle Contents

Bundles use manifest schema version `1` and include:

- manifest id, creation time, source app version, selected sections, checksums,
  and redaction status
- model registry snapshots
- gateway policy
- eval datasets
- comparison reports
- release-readiness reports
- V2 prompt templates
- V2 run profiles

Export applies strict redaction before writing the bundle. Secret-bearing keys
such as tokens, passwords, API keys, authorization headers, private keys, and
certificates are replaced with `[redacted]`. Known token-shaped strings are also
redacted, and long strings are truncated.

## Safe Sharing

Before sharing a bundle, inspect the manifest `redaction` block and run an
import preview on the target machine. The import preview validates:

- schema compatibility
- section checksums
- unredacted secret-risk values
- conflicting eval dataset, prompt template, or run profile IDs
- missing run-profile prompt template dependencies

Secret-risk, checksum, schema, and dependency issues block import. Existing ID
conflicts are warnings so an operator can intentionally replace local artifacts.

## Migration Workflow

1. Open Console > System Operations > Workspace Bundles.
2. Select the sections to export.
3. Click `Export`.
4. Inspect the generated bundle JSON and redaction status.
5. Move the JSON to the target machine.
6. Paste it into `Import Bundle JSON`.
7. Select the sections to restore.
8. Click `Preview Import`.
9. If there are no blocking issues, click `Import`.

The import path is dry-run first. Nothing is written until the operator
explicitly runs import with selected sections.
