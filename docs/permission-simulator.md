# Tool Permission Simulator

The Claude Code session wizard includes a permission simulator before tmux launch. It previews the effective launch policy from the selected permission mode, allowed tools, denied tools, extra context directories, project directory, profile, run mode, and raw extra arguments.

## What It Shows

The simulator reports:

- risk level: `low`, `medium`, `high`, `critical`, or `unknown`
- allowed, denied, risky, and unknown tool entries
- project and `--add-dir` path scope, including outside-project, home-directory, and root-directory warnings
- warnings for broad Bash access, bypass-style modes, edit tools without deny lists, Bash without destructive-command denies, and dangerous raw extra args
- a suggested safer preset

The preview is available in the Permissions step and repeated in the Review step. Launch is not blocked by simulator findings; expert override remains available.

## Launch Records

`POST /api/tmux/start` recalculates the permission summary server-side and attaches it to the launch request as `permission_summary`. The tmux session registry stores that enriched request data with the session metadata. The audited `tmux.start` request body also includes the summary.

`POST /api/tmux/permissions` returns a preview without starting tmux:

```json
{
  "permission_mode": "bypassPermissions",
  "allowed_tools": "Bash(*) Edit Write Read",
  "disallowed_tools": "Bash(rm -rf *)",
  "project_dir": "/home/me/project"
}
```

Response:

```json
{
  "permission_summary": {
    "mode": "bypassPermissions",
    "risk_level": "critical",
    "warnings": [{"code": "permission_bypass", "severity": "critical"}],
    "override_allowed": true
  }
}
```

## Limits

This is a static launch preview. It does not replace Claude Code's own runtime permission prompts, provider behavior, local shell permissions, filesystem ACLs, or operator review. Tool syntax can evolve, so unknown entries are surfaced instead of treated as proof of safety.
