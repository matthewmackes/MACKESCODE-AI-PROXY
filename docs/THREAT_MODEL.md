# Threat Model

Scope: the local proxy, web console, embedded tmux terminal, model registry,
DigitalOcean Serverless/Dedicated integrations, traces, usage/cost logs, and
runtime state.

This is a living security contract. If a change alters authentication,
authorization, terminal exposure, model routing, trace contents, cloud resource
lifecycle, or token handling, update this file and `SECURITY.md`.

## Trust Boundaries

| Component | Trust | Notes |
| --- | --- | --- |
| `do-anthropic-proxy.py` | Trusted local service | Translates Anthropic-style requests to OpenAI-compatible upstream calls and records usage. |
| `image-studio.py` / Console | Trusted operator UI | Exposes model management, terminal control, Dedicated lifecycle, billing, traces, and chat/image workflows. |
| Browser session | Partially trusted | Must authenticate with owner/scoped token or JWT. Browser scripts can be affected by local cache/extensions. |
| Embedded tmux terminal | High risk trusted action | Sends operator input to local shell/Claude Code sessions. Treat as command execution. |
| DigitalOcean APIs | External privileged service | Can create/destroy paid cloud resources and reveal account/billing metadata. |
| LLM providers/models | External inference boundary | Prompts, code, and outputs cross the provider boundary according to selected route. |
| Runtime cache/log files | Sensitive local state | May contain prompts, usage, traces, cloud identifiers, generated assets, and session metadata. |

## Attack Surface

- Unauthenticated or over-exposed console/proxy ports.
- Console token leakage through URLs, logs, screenshots, browser history, or
  shared terminals.
- Scoped role mistakes that allow model registry, billing, terminal, or
  Dedicated actions to a viewer.
- Embedded terminal writes and tmux session controls.
- Malicious or malformed upstream responses from model endpoints or
  DigitalOcean APIs.
- Cost abuse through repeated Serverless calls or orphaned Dedicated Inference
  resources.
- Trace/log leakage of prompts, source code, routing metadata, endpoint ids, or
  billing/account data.
- Registry drift where Code/Create selectors offer models the proxy cannot
  route or the key cannot access.
- Browser JavaScript failure that leaves controls stale or misleading.

## Controls

- Proxy binds to `127.0.0.1` by default.
- Console uses generated owner token authentication by default, optional scoped
  role tokens, and short-lived JWT sessions with rotating refresh tokens.
- Sensitive actions are permission checked and written to the audit log.
- Runtime state is separated from release-owned config and should not be
  committed.
- Model access audit marks allowed/forbidden/probe-failed states in the global
  registry.
- Registry/proxy sync checks prevent newly selected stale models from being
  silently routed.
- Dedicated builds are budget guarded, audit logged, and surfaced with
  human-readable lifecycle state.
- Idle/unhealthy teardown policies limit cost exposure.
- Default traces avoid full prompts and full assistant responses; see
  `docs/trace-redaction-policy.md`.
- Release checks include unit tests, syntax checks, template JavaScript checks,
  and browser smoke when Playwright is available.

## Accepted Residual Risks

- This is a private-operator tool. A local user with shell access can usually
  read runtime state, tmux sessions, and token files owned by that user.
- The console binds to `0.0.0.0` by default for headless access; token auth is
  therefore mandatory for any non-local network.
- URLs may contain console tokens for convenience. Prefer headers/JWT sessions
  for shared or monitored environments.
- LLM prompts and code sent to external providers follow the chosen model route.
  The platform can show routing proof, but it cannot make external inference
  private after the request is sent.
- DigitalOcean API shape and capacity availability can change. The platform
  should fail human-readably and avoid hiding cloud-side uncertainty.
- Billing/prepay details may be incomplete if the token lacks scope or the API
  omits account-specific fields.

## Security Review Triggers

Run a focused security review for changes that touch:

- auth token or JWT session lifecycle
- role permissions or audit logging
- terminal/tmux send, attach, stop, or launch behavior
- DigitalOcean token discovery, Dedicated build/teardown, or access-token
  creation
- model registry source-of-truth behavior
- trace payload shape or log retention
- browser-visible routing/cost/detail panels
