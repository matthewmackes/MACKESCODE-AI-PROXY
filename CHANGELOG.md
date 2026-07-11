# Changelog

## Current

- Removed the old whiptail launcher interface.
- Removed old `claude-pro`, `claude-flash`, and `claude-sonnet` wrappers.
- Added wrappers for the current text models: DeepSeek V4, GLM, Mistral, and Codex.
- Replaced stale Codex references with `openai-gpt-5.3-codex`.
- Simplified the proxy model list to the current MDE LLM-PROXY models.
- Removed catalog filtering, provider fallback, and upstream Anthropic model pass-through code.
- Added `./claude-DO.sh --test-models` to smoke-test all configured current models.
- Added the pure Python `image-studio.py` unified web console with embedded Claude Code, text model chat, image studio, history, budgets, costs, and logs.
- Added `matts-console.py` as the main Python entry point for the unified web interface.
- Made the unified console headless/public-facing by default with generated token authentication.
- Replaced the raw browser PTY with tmux-backed Claude Code sessions for continuity and a readable browser view.
- Added enterprise Claude Code launch controls: autonomy profiles, permission modes, tool boundaries, context directories, run modes, output formats, budget caps, safe mode, and bare mode.
- Added a Reporting page with local model usage plus optional DigitalOcean balance, billing history, and daily spend insights.
- Added a full-screen xterm.js terminal page connected to tmux over WebSocket for a real interactive Claude Code console.
- Added global model registry management, Serverless catalog import, model access key audit, and selector labels with cost, origin, access state, and use-case context.
- Added DigitalOcean Dedicated Inference lifecycle automation with preflight, build, status, access-token creation, budget guard, idle warning, auto-teardown, and Serverless fallback routing.
- Added per-message routing detail, trace search, gateway policy visibility, model comparison/eval workflows, and model hero cards.
- Separated release config from runtime state for Dedicated lifecycle data, Serverless cache, traces, usage, wallpaper cache, budgets, and tmux sessions.
- Removed default embedded model access key behavior; the launcher now requires a token file or explicit one-run override.
- Added `RELEASE.md`, runtime-state backup/restore tooling, and post-upgrade health validation.
- Converted `matts-image` from a shell helper to a Python CLI.

### Migration Notes

- Run `scripts/runtime-state.py backup` before upgrading hosts that have local chats, usage logs, tmux sessions, or Dedicated Inference state.
- Run `scripts/health-validate.py` after restarting the proxy and Console.
- Token files are not included in runtime-state backups unless `--include-secrets` is supplied.
