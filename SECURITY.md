# Security

This setup is intended for local or trusted-host use. The proxy binds to `127.0.0.1` by default and should not be exposed to untrusted networks.

## Access Key

The launcher does not ship with a default model access key. Provide a key by writing the token file below, or set `MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE=1` with `MATTS_VALUE_SET_ACCESS_KEY` for an intentional one-run override. If neither source is present, the launcher exits before starting the proxy.

The default token file is:

```text
$HOME/.mcnf-do-model-access-token
```

When the launcher writes the token file, it creates it with `0600` permissions. The Console model-access audit can also use `MODEL_ACCESS_KEY`, `DIGITALOCEAN_MODEL_ACCESS_KEY`, `MATTS_VALUE_SET_ACCESS_TOKEN`, the default token file, a project-local `.mcnf-do-model-access-token`, or `/root/.mcnf-do-model-access-token` depending on how the host is operated.

## Sensitive Data

Treat these as sensitive:

- Matts Value Set access keys
- DigitalOcean API tokens and account metadata
- Dedicated Inference public/private endpoint FQDNs, access tokens, CA certificates, VPC UUIDs, inference IDs, and raw DigitalOcean payloads
- token files
- usage logs containing prompts or output
- trace files containing routing, prompt, model, cost, or latency detail
- generated images
- project source code sent through Claude Code
- runtime model registry edits when they reveal private account access policy

## Defaults

- Proxy bind address: `127.0.0.1`
- Proxy port: `18081`
- Unified console bind address: `0.0.0.0`
- Unified console port: `18181`
- Unified console auth token file: `$HOME/.cache/matts-value-set/studio/console-auth-token`
- Unified console auth sessions file: `$HOME/.cache/matts-value-set/studio/auth-sessions.json`
- Token file: `$HOME/.mcnf-do-model-access-token`
- Usage file: `$HOME/.cache/matts-value-set/usage.jsonl`
- Budget file: `$HOME/.cache/matts-value-set/budgets.json`
- Dedicated Inference state file: `$HOME/.cache/matts-value-set/studio/dedicated-inference.json`
- Dedicated Inference publishable template: `config/dedicated-inference.example.json`
- Active model registry schema: `schema_version` `1`
- Audit log: `$HOME/.cache/matts-value-set/studio/audit.jsonl`

The repository should contain schemas, defaults, and examples. Runtime state belongs under `$HOME/.cache/matts-value-set/` or an explicit operator-provided path. Do not commit live cloud resource metadata, endpoint credentials, generated auth tokens, traces, usage logs, wallpaper cache files, or tmux session registries.

For protected project trees, run the launcher as the user that can read the project:

```bash
sudo -H /home/mm/DO-ClaudeCode-Proxy/claude-DO.sh --project-dir /path/to/protected/project
```

The unified web console includes an embedded Claude Code terminal. Keep token auth enabled for public-facing use. To rotate the console token, stop the console and remove:

```text
$HOME/.cache/matts-value-set/studio/console-auth-token
```

Model registry entries can reveal which models a key is allowed to use. Treat `access_status`, Dedicated routing state, and model audit output as operational metadata even when no raw token is present.

## Console Roles

The generated console token is an owner token. Optional scoped role tokens can be supplied with `MATTS_CONSOLE_ROLE_TOKENS_JSON`, `MATTS_CONSOLE_ROLE_TOKENS_FILE`, or the `auth.role_tokens` object in `config/console.json`.

Example role-token file:

```json
{
  "token-value-here": {"id": "operator-a", "roles": ["operator"]},
  "infra-token-here": {"id": "infra-a", "roles": ["infra_admin"]}
}
```

Built-in roles:

- `viewer`: read console, trace, and billing views
- `operator`: viewer plus model use, eval runs, and tmux control
- `model_admin`: operator plus model registry, proxy sync, and key audit
- `billing_admin`: billing views and budget updates
- `infra_admin`: operator plus Dedicated Inference and budget administration
- `owner` / `admin`: all permissions

Sensitive actions are permission-checked and appended to the audit log. This includes model registry changes, model access audits, Dedicated build/teardown/policy actions, budget updates, billing reports, eval runs, tmux control, and terminal writes.

Rotate scoped role tokens by replacing the JSON/file/config entry, restarting the console, and removing the old token from the configured role-token source.

JWT sessions are issued by `POST /api/v1/auth/session` for an already authenticated owner or scoped role token. Access tokens are short-lived; refresh tokens rotate on every refresh and are invalid after replay, expiration, revocation, or owner-token rotation. Active session metadata is stored in `auth-sessions.json` with `0600` permissions and should be treated as sensitive runtime state. Use `POST /api/v1/auth/revoke` to revoke a session and delete `auth-sessions.json` to clear all sessions during incident response.
