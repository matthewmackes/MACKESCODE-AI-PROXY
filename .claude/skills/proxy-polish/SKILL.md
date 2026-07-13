---
name: proxy-polish
description: >-
  Iteratively refine the DO Claude Code Proxy web interface, especially Create,
  Code, Console, model cards, dark mode, and routing/cost detail surfaces. Use
  when the operator asks to polish, beautify, make the interface more alive, or
  drive the GUI to enterprise-class quality. Not for unrelated backend-only
  bugs or release publishing.
---

# proxy-polish - GUI Refinement For DO Claude Code Proxy

Invoke as `/proxy-polish`. (This is the project-scoped GUI polish loop for the
DO Claude Code Proxy web console. It is deliberately named distinctly from the
user-level `/polish` MCNF egui skill, which targets a different codebase and
must not be applied here.)

Read `GOVERNANCE.md`, `docs/requirements-ledger.md`, and
`docs/create-experience.md` before making broad UI changes. The goal is a
runtime-reachable, browser-verified interface, not static mockups.

## Surfaces

- **Create:** wallpaper-forward text/image workspace, floating chat, model
  comparison, answer reveal, weather/wallpaper fallback, and model-specific
  response treatment.
- **Code:** tmux terminal workflow, session/model setup wizard, paste dock,
  shortcuts, status, and routing model selection.
- **Console:** Carbon-inspired operations UI for Accounting & Time, Inference
  Hosting Lifecycle, LLM Management, Observability, AgentBoard, and System
  Operations.
- **Global chrome:** centered primary tabs, right-side Dark Mode/Status/Cost/
  Console controls, global alerts, and cost pills.
- **Model surfaces:** selector labels, hero cards, provider identity, origin,
  pricing, access state, use cases, alternatives, and new-model sparkle.

## Quality Axes

1. Layout and density: no excessive top whitespace, no overlapping controls, no
   horizontal overflow, stable fixed-format controls.
2. Typography: readable hierarchy, larger answer body text, smaller metadata,
   no hero-scale text inside dense tools.
3. Color and theme: global light/dark consistency, restrained operational
   palette, accessible contrast.
4. Motion and presence: subtle, purposeful animation; respect reduced motion;
   no decorative effects that block readability.
5. State honesty: loading, empty, error, disabled, budget-blocked, not-ready,
   and fallback states must be explicit and human-friendly.
6. Traceability: message detail, lifecycle detail, cost, tokens, and routing
   proof stay available without overwhelming the default view.
7. Responsiveness: desktop and mobile browser smoke must prove no overlap or
   overflow on primary workflows.

## Required Evidence

- Run focused unit/API tests for touched services.
- Run `scripts/browser-smoke.py --required` for UI changes when Playwright is
  installed.
- For tab/navigation regressions, test the live rendered page, not just template
  syntax.
- If browser smoke cannot run, document why and run the strongest available
  fallback checks.

## Hard Rules

- Do not create a landing page; the first screen remains the working app.
- Do not add controls that are visual-only or unwired.
- Do not hide raw diagnostics entirely; put them behind details where useful.
- Do not let Code/Create/Console model lists drift from `config/models.json`.
- Do not commit runtime state or generated cloud credentials while polishing.
