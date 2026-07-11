# Security

This setup is intended for local or trusted-host use. The proxy binds to `127.0.0.1` by default and should not be exposed to untrusted networks.

The project threat model is maintained in `docs/THREAT_MODEL.md`. Governance
locks for secrets, runtime state, cost safety, and definition of done are in
`GOVERNANCE.md`.

## Reporting A Vulnerability

Do not open a public issue containing access keys, DigitalOcean tokens, console
URLs with tokens, Dedicated endpoint credentials, trace logs, billing payloads,
or private source code.

Report privately through the repository's GitHub security advisory flow when it
is enabled, or contact the repository owner directly. Include the affected
component, commit/version, impact, and reproduction steps. Redact credentials
and account-specific identifiers.

## Access Key

The launcher does not ship with a default model access key. Provide a key by writing the token file below, or set `MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE=1` with `MATTS_VALUE_SET_ACCESS_KEY` for an intentional one-run override. If neither source is present, the launcher exits before starting the proxy.

The default token file is:

```text
$HOME/.mcnf-do-model-access-token
```

When the launcher writes the token file, it creates it with `0600` permissions. The Console model-access audit can also use `MODEL_ACCESS_KEY`, `DIGITALOCEAN_MODEL_ACCESS_KEY`, `MATTS_VALUE_SET_ACCESS_TOKEN`, the default token file, a project-local `.mcnf-do-model-access-token`, or `/root/.mcnf-do-model-access-token` depending on how the host is operated.

## Sensitive Data

Treat these as sensitive:

- MDE LLM-PROXY access keys
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
- V2 FastAPI/React console default bind address: `127.0.0.1`
- V2 FastAPI/React console default port: `18182`
- V2 run workspace database: `$HOME/.cache/matts-value-set/studio/v2-run.sqlite3`
- V2 Console TUI audit file: `$HOME/.cache/matts-value-set/studio/tui-audit.jsonl`
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

The unified web console includes an embedded Claude Code terminal. The interactive terminal WebSocket (`GET /ws/tmux`) requires the `tmux_control` permission, the same scope as the REST tmux and terminal routes: owner/admin tokens and the `operator`, `model_admin`, and `infra_admin` roles qualify, while tokens without `tmux_control` (for example `viewer` or `billing_admin`) are rejected with HTTP 403 before the WebSocket upgrade and before any PTY is attached. Terminal attach, denied attach, and detach events are appended to the audit log as `tmux.ws_attach` / `tmux.ws_detach` records containing the tmux session name, actor identity, and close reason; keystrokes and screen content are never written to the audit log. Keep token auth enabled for public-facing use. To rotate the console token, stop the console and remove:

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

Sensitive actions are permission-checked and appended to the audit log. This includes model registry changes, model access audits, Dedicated build/teardown/policy actions, budget updates, billing reports, eval runs, tmux control, terminal writes, and interactive terminal WebSocket attach/detach on `/ws/tmux`.

The V2 React console uses the same role/capability model for `/v2/*` routes. The standing Console TUI bridge is read-only unless the actor has `tui.control`; control leases and denied writes are written to the TUI audit log. Operate actions such as automation dispatch, rollback apply, CI launch, review updates, and model deprecation migrations are capability-gated before reaching the legacy service adapter.

Rotate scoped role tokens by replacing the JSON/file/config entry, restarting the console, and removing the old token from the configured role-token source.

JWT sessions are issued by `POST /api/v1/auth/session` for an already authenticated owner or scoped role token. Access tokens are short-lived; refresh tokens rotate on every refresh and are invalid after replay, expiration, revocation, or owner-token rotation. Active session metadata is stored in `auth-sessions.json` with `0600` permissions and should be treated as sensitive runtime state. Use `POST /api/v1/auth/revoke` to revoke a session and delete `auth-sessions.json` to clear all sessions during incident response.

## Frontend Dependency Audit

Clean V2 frontend installs are lockfile-reproducible: the launcher, V2 browser smoke, and release gate use `npm ci --no-audit` when `frontend/package-lock.json` exists and `frontend/node_modules` is missing. Plain `npm install --no-audit` is reserved for trees without a lockfile. Install steps skip npm's implicit audit output because the release gate enforces the explicit production audit check below.

The release gate enforces shipped React dependency hygiene with `npm audit --omit=dev` through `scripts/check-v2-frontend-audit.py`. Current production dependencies are expected to audit clean.

A full frontend `npm audit` can report Vite/esbuild development-server advisories while the host uses the current Node 16 toolchain. The first Vite line that clears those development-only findings requires Node 18+ or Node 20+, so treat the Vite dev server as a local trusted tool and serve production operators only through `matts-v2-console.py` and the built `frontend/dist` assets until the Node baseline is upgraded.
