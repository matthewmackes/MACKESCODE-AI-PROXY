# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is MDE LLM-PROXY - a private Claude Code launcher and Anthropic-compatible local proxy for curated LLM-PROXY models. The system provides a local proxy server that translates Anthropic API calls to OpenAI-compatible endpoints for various LLM models.

## Governance

Read `GOVERNANCE.md` before broad changes. It is the project rulebook for
architecture, security, cost safety, runtime-state boundaries, definition of
done, and AI-assisted work. Durable product decisions live in
`docs/requirements-ledger.md`; architecture/policy changes live in
`docs/DECISIONS.md`; live-resource blockers live in `docs/NEEDS-OPERATOR.md`.

The most important locks:

- `config/models.json` is the selectable model source of truth.
- Runtime state and cloud credentials are not release-owned files.
- Done means runtime-reachable, observably working, documented, and verified.
- Sensitive actions must be permission checked and audit logged.
- UI changes need rendered browser evidence when feasible.

## Key Components

### Core Launcher (`claude-DO.sh`)
- Main bash script that starts the proxy and launches Claude Code
- Accepts model selection via `--model` flag or shortcut wrappers
- Provides operational commands: `--doctor`, `--list-models`, `--costs`, `--budget`, `--restart`, `--test-models`
- Manages proxy lifecycle (starts/stops proxy in tmux session)
- Sets environment variables for Claude Code to route through local proxy

### Proxy Server (`do-anthropic-proxy.py`)
- HTTP server that translates Anthropic Messages API to OpenAI chat completions format
- Listens on `127.0.0.1:18081` by default
- Provides endpoints:
  - `/v1/models` - List available models
  - `/v1/messages` - Main chat endpoint
  - `/v1/images/generations` - Image generation endpoint
  - `/v1/claude-do/costs` - Cost information
  - `/v1/claude-do/capabilities` - Proxy capabilities
  - `/v1/claude-do/budget` - Budget information
- Tracks usage costs and enforces budget limits
- Logs to JSONL files in `~/.cache/matts-value-set/`

### React V2 Console (`matts-v2-console.py`)
- Primary web interface accessible at `0.0.0.0:18182` with token authentication
- Provides:
  - Chat workspace for direct model conversations and transcript handoff
  - Code workspace for Claude Code/tmux sessions, the TMux/TUI console, terminal command history, and image review
  - Research workspace for source-backed search, citations, and multi-model synthesis
  - Create workspace for image generation only
  - Models workspace for registry health, pricing, access state, and model hero cards
  - Advanced workspaces for Console, Run, Observe, and Operate workflows
- Manages tmux sessions for persistent Claude Code instances through the V2 API
- Authentication via generated token in `~/.cache/matts-value-set/studio/console-auth-token`
- `image-studio.py` remains the service-adapter composition module imported by V2; it is not the supported standalone V1 UI.

### Model Shortcuts
- `claude-deepseek`, `claude-deepseek-v4`, `claude-glm`, `claude-mistral`, `claude-codex`, `claude-sd35` - Wrapper scripts for each model
- Resolve to `claude-DO.sh --model <model>` calls

### Image Generator (`matts-image`)
- Python CLI for one-shot image generation using Stable Diffusion 3.5
- Takes prompt and outputs image file

## Available Models

Available models are loaded from `config/models.json`, overlaid with runtime model-access audit state from `$HOME/.cache/matts-value-set/studio/model-access-state.json`, filtered by enabled state and access status, and exposed consistently through `./claude-DO.sh --list-models`, `/v1/models`, Code/Create selectors, Console LLM Management, and model hero cards. `config/default-models.json` is only the bootstrap fallback.

Use Console > LLM Management > key audit to verify which Serverless text models the configured key can access. Forbidden, rate-limited, probe-failed, disabled, and Dedicated-offline states are visible in model metadata and selector labels without writing key-specific audit results into `config/models.json`.

## Common Development Tasks

### Testing Proxy Changes
```bash
# Start proxy with specific model
python3 do-anthropic-proxy.py --host 127.0.0.1 --port 18081 --default-model deepseek-3.2

# Test proxy endpoint
curl -v "http://127.0.0.1:18081/v1/models"
curl -v "http://127.0.0.1:18081/v1/claude-do/capabilities"
```

### Running Web Console Locally
```bash
# Start React V2 console (binds to 0.0.0.0:18182)
python3 matts-v2-console.py --build-frontend
```

### Testing Model Smoke Tests
```bash
# Test all configured models
./claude-DO.sh --test-models

# Test specific endpoint
curl -X POST "http://127.0.0.1:18081/v1/messages" \
  -H "Content-Type: application/json" \
  -d '{"model": "deepseek-3.2", "messages": [{"role": "user", "content": "test"}], "max_tokens": 10}'
```

### Debugging Proxy Issues
```bash
# Check proxy status
curl -s "http://127.0.0.1:18081/v1/claude-do/capabilities" | python3 -m json.tool

# View recent logs
tail -f /tmp/matts-value-set-proxy.jsonl

# Inspect routing proof in the GUI
# Create > chat message > Show Detail
# Console > Observability > Trace search

# Check tmux sessions
tmux list-sessions | grep matts-
```

## Architecture Notes

### Proxy Translation Layer
The proxy converts Anthropic API format to OpenAI format because the upstream inference service (DigitalOcean) uses OpenAI-compatible endpoints. Key transformations:
- Anthropic `messages` format → OpenAI `chat.completions` format
- Tool use syntax conversion (`tool_use` ↔ `function` calls)
- Streaming response format translation
- Cost tracking per model with different input/output rates

### Tmux Session Management
The web console creates tmux sessions prefixed with `matts-` for persistent Claude Code instances. Sessions survive browser refreshes and can be reattached. The console provides both:
1. Embedded browser view (captures tmux screen)
2. Full xterm.js terminal via WebSocket

### Authentication Flow
1. Console generates random token on first run
2. Token saved to `~/.cache/matts-value-set/studio/console-auth-token`
3. All API calls require token in URL (`?token=...`) or headers
4. WebSocket connections also require token validation

### Model Registry And Routing Proof
`config/models.json` is the active source of truth for model IDs, aliases, type, pricing, enablement policy, and Dedicated metadata. Serverless catalog sync can add new DigitalOcean models. Key audit updates runtime access state, which the console and proxy merge at read time. Chat responses include routing metadata; the GUI exposes it through each message's `Show Detail` button and through Console trace search.

### Cost Tracking System
- Usage logged to `~/.cache/matts-value-set/usage.jsonl`
- Budget limits in `~/.cache/matts-value-set/budgets.json`
- Costs per million tokens come from the active model registry
- Image generation has separate per-image pricing

### Environment Configuration
Key environment variables:
- `MATTS_VALUE_SET_ACCESS_KEY` - One-run model access key override when explicitly enabled
- `MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE=1` - Permit the one-run key override
- `MATTS_VALUE_SET_BASE_URL` - Upstream inference endpoint
- `MATTS_VALUE_SET_PROXY_HOST/PORT` - Proxy binding
- `MATTS_VALUE_SET_TOKEN_FILE` - Token file location
- `MATTS_MODEL_CONFIG_FILE` - Active model registry override
- `DIGITALOCEAN_TOKEN` - For billing reporting
- `DIGITALOCEAN_ACCOUNT_URN` - For billing reporting

## Work Tracking and AI Coordination

### Work Tracking System
All development work must be tracked in `MAIN-WORKLIST.md` using the standardized task format. This document serves as the single source of truth for work status, priorities, and dependencies.

**Key Documents:**
- `GOVERNANCE.md` - Architectural locks, definition of done, source-of-truth policy, and safety rules
- `MAIN-WORKLIST.md` - Central work tracking with tasks, status, and dependencies
- `AI-WORK-PROTOCOL.md` - Quick reference for AI work procedures
- `CLAUDE.md` - Project instructions and development workflow
- `docs/DECISIONS.md` - Append-only durable decision log
- `docs/NEEDS-OPERATOR.md` - Operator/live-resource gated items
- `docs/THREAT_MODEL.md` - Security model for proxy, console, terminal, cloud integrations, and traces
- `docs/COMPLIANCE.md` - Integrity sweep checklist and findings log

**Before starting any work:**
1. Read `GOVERNANCE.md` and relevant current task/spec docs.
2. Check `MAIN-WORKLIST.md` and `docs/NEEDS-OPERATOR.md`.
3. Follow the protocol in `AI-WORK-PROTOCOL.md`.
4. Document progress and decisions during work.
5. Update status, docs, and verification evidence after completion.

### Current Work Focus
Use `MAIN-WORKLIST.md` as the current task ledger. Do not rely on stale priority
lists in older docs; when work is blocked on live cloud resources or an operator
choice, move the blocker to `docs/NEEDS-OPERATOR.md` instead of pretending it is
code-complete.

### Quality Standards
- All code changes must include tests
- Documentation must be updated when behavior, operator workflows, security posture, release process, or runtime-state boundaries change
- Backward compatibility must be maintained
- Security considerations must be addressed
- Performance impact must be evaluated
- `scripts/release-check.sh` is the standard release gate

## File Structure

- `claude-DO.sh` - Main launcher script
- `do-anthropic-proxy.py` - Core proxy server
- `matts-v2-console.py` - React V2 console launcher
- `image-studio.py` - V2 service-adapter composition module
- `matts-image` - Image generator CLI
- `claude-*` - Model-specific wrapper scripts
- `README.md` - User documentation
- `CHANGELOG.md` - Version history
