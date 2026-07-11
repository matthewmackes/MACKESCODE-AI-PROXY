# Operational Command Palette

The console includes a searchable operational command palette for common
operator actions. Open it from the header `Command` button or with
`Ctrl+K` / `Command+K`.

## Default Commands

| Command | Permission | Context |
| --- | --- | --- |
| Start Claude Code Session | `tmux_control` | None |
| Focus Current Terminal | `tmux_control` | None |
| Create Selected Session Snapshot | `tmux_control` | Selected session |
| Review Selected Session Patch | `tmux_control` | Selected session |
| Open Selected Agent Session | `tmux_control` | Selected session |
| Run Eval | `eval_run` | None |
| Audit Model Access Key | `model_admin` | None |
| Refresh DigitalOcean Catalog | `model_admin` | None |
| Sync Proxy | `model_admin` | None |
| Open Traces | `view_traces` | None |
| Replay Selected Trace | `replay_run` | Selected trace |
| Open Release Dashboard | `view_console` | None |
| Open Rollback Wizard | `rollback_admin` | None |
| Search Project Docs | `view_console` | None |
| Open Selected Model Detail | `view_console` | Selected model |

## Behavior

- `GET /api/commands` returns searchable command metadata and availability.
- `POST /api/commands/dispatch` validates the actor permission before returning
  the client-side action to run.
- Contextual commands are disabled until the browser can provide the selected
  session, model, or trace identifier.
- Dispatch attempts write `command_palette.dispatch` audit records with the
  command id, permission, actor, and selected context.

The palette does not execute shell commands directly. It dispatches to existing
console controls and API-backed workflows so RBAC, validation, and audit logging
stay on the same paths as manual button clicks.
