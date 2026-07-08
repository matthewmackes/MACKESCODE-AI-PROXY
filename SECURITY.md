# Security

This setup is intended for local or trusted-host use. The proxy binds to `127.0.0.1` by default and should not be exposed to untrusted networks.

## Access Key

This private deployment intentionally keeps a default Matts Value Set access key in the launcher code. `MATTS_VALUE_SET_ACCESS_KEY` is ignored unless `MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE=1` is also set.

At launch, the key is written to:

```text
$HOME/.mcnf-do-model-access-token
```

The token file is created with `0600` permissions.

## Sensitive Data

Treat these as sensitive:

- Matts Value Set access keys
- token files
- usage logs containing prompts or output
- generated images
- project source code sent through Claude Code

## Defaults

- Proxy bind address: `127.0.0.1`
- Proxy port: `18081`
- Unified console bind address: `0.0.0.0`
- Unified console port: `18181`
- Unified console auth token file: `$HOME/.cache/matts-value-set/studio/console-auth-token`
- Token file: `$HOME/.mcnf-do-model-access-token`
- Usage file: `$HOME/.cache/matts-value-set/usage.jsonl`
- Budget file: `$HOME/.cache/matts-value-set/budgets.json`

For protected project trees, run the launcher as the user that can read the project:

```bash
sudo -H /home/mm/DO-ClaudeCode-Proxy/claude-DO.sh --project-dir /path/to/protected/project
```

The unified web console includes an embedded Claude Code terminal. Keep token auth enabled for public-facing use. To rotate the console token, stop the console and remove:

```text
$HOME/.cache/matts-value-set/studio/console-auth-token
```
