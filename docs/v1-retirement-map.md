# V1 Retirement Map

**Date:** 2026-07-11
**Worklist:** INT-161
**Decision:** ADR-0003 makes the React/FastAPI V2 console the current product
surface. The V1 console UI is retired while preserving service functions that
V2 imports from the Python composition layer.

## Keep

| Artifact | Why it remains |
| --- | --- |
| `image-studio.py` | V2 imports it through `backend/v2/services/legacy_console.py` as a service-adapter composition module for model registry, tmux, operate, observe, run, chat, image, audit, release, and runtime-state functions. It is no longer documented as the standalone console UI. |
| `src/console/**` | Shared service and handler modules used by `image-studio.py`, V2 adapters, tests, install packaging, and proxy/runtime workflows. |
| `backend/v2/**` and `frontend/**` | Current console API and React UI. |
| `matts-v2-console.py` | Current console launcher. |

## Retire

| Artifact | Retirement reason |
| --- | --- |
| `matts-console.py` | Thin V1 entrypoint that only runs `image-studio.py` as a standalone UI. Current console launch is `matts-v2-console.py`. |
| `templates/main.html`, `templates/login.html`, `templates/terminal.html` | V1 browser UI templates. Current UI is the built React frontend served by `backend/v2/app.py`. |
| `scripts/browser-smoke.py` | Legacy V1 browser smoke harness. Current browser evidence is `scripts/v2-browser-smoke.py`. |
| Release gate template-JavaScript check | It only validates V1 inline template scripts. V2 JavaScript is validated by TypeScript/Vite build, bundle boundary check, production audit, and V2 browser smoke. |
| Release gate legacy browser smoke | It starts and renders V1. V2-only release scope keeps Python unit/smoke tests, OpenAPI drift, React build, bundle/audit checks, and V2 browser smoke. |

## V2 Adapter Dependencies On `image-studio.py`

`backend/v2/services/legacy_console.py` lazily imports `image-studio.py` and
uses these categories of functions:

- Code/TUI: `tmux_session_items`, `tmux_start`, `tmux_capture`,
  `tmux_send_text`, `tmux_send_key`, `tmux_rename_session`, `tmux_stop`,
  `permission_simulation`, and `command_palette_payload`.
- Chat/Create/Research: `chat_completion`, `generate_images`,
  `wallpaper_payload`, and model defaults such as `TEXT_MODELS` and
  `default_text_model`.
- Observe: `console_status`, `cost_summary_payload`, `analytics_payload`,
  `provider_health_payload`, `read_traces`, `audit_explorer_payload`,
  `reporting_export_status`, and `reporting_integration_payload`.
- Operate: release candidate, rollback, config drift, automation, quota,
  synthetic load, CI triage, offline mode, model deprecation, eval gate,
  repository context, review queue, and audit helpers.
- Run: replay, workspace bundle, context-window, prompt/eval, and reporting
  export helpers.

Deleting or splitting `image-studio.py` requires replacing this adapter surface
first. Removing V1 UI files does not remove those service functions.

## Acceptance

- V1 templates and V1 entrypoint are absent from the release-owned UI surface.
- Release checks no longer compile or run legacy browser smoke.
- V2 tests, generated OpenAPI drift check, React build, bundle/audit checks, and
  V2 browser smoke remain the release evidence.
- Operator docs describe V2 as the console and describe `image-studio.py` only
  as an internal compatibility/composition layer.
