# Unified Model Card

Every LLM representation in the V2 console renders through one component: `ModelIdentityCard` (`frontend/src/components/modelCard.tsx`). Chat contacts, model dropdowns, the Models grid, and detail surfaces all show the same identity, facts, and controls, so a model looks and behaves identically everywhere (V2-081), and every list leads with the operator's favorites (V2-082).

## Anatomy

Both sizes share:

- a provider brand accent stripe and faint brand tint, colored with official simple-icons hex data (`modelBrandColor`); unbranded marks fall back to the platform blue `#0f62fe`
- an accent-tinted `ModelLogo` tile with a square national-flag badge (flag-icons, MIT, 1x1 assets; a globe glyph covers unknown nations)
- the display name, with a ✨ sparkle when the model entered the registry in the last 7 days (`is_new`)
- a "by Provider · Nation" byline (company, falling back to provider)
- a favorite star (☆/★)
- facts chips ending in the Health letter grade

Sizes:

- **Small** - facts chips: status · cost · Health. Used for chat contacts and dropdown options.
- **Big** - facts chips: status · cost · context · type · Health, plus a use-case blurb and an actions row: **Compare** (adds to the compare tray) and **Use in Chat** (jumps to Chat with the model selected). Used in the Models grid. Big degrades to Small below a ~620px viewport (`useNarrowViewport`).

The status chip shows `Routable` when the route is enabled, otherwise the readable access state, so the card never hides a forbidden or offline model behind styling.

## Health Grade

Every `/v2` model payload (chat, code, create, and models APIs, each via `ModelShowcaseService`) carries a measured health object:

```
health { grade, success_rate, p50_latency_ms, requests, measured }
```

- Grades come from `health_grade` in `src/console/services/model_scorecards.py`: **A** needs success >= 0.99 with p50 <= 1500ms, **B** needs success >= 0.97 with p50 <= 3000ms, **C** holds when success >= 0.90 or p50 <= 10000ms, otherwise **D**.
- Aggregation lives in `_HealthIndex` (`backend/v2/services/model_showcase.py`): up to 2000 recent proxy traces, cached behind a 15-second TTL keyed on the trace file's path/mtime/size signature, so a trace append invalidates immediately and unreadable trace data degrades to unmeasured instead of raising.
- Models with no measured traffic show `Health —`. Hovering the Health chip shows success rate, p50 latency, and the recent request count.

The grade is trace-derived and advisory, like the 0-100 scorecard score (`docs/model-scorecards.md`); routing still follows gateway policy and explicit operator selection.

## Data Sources

- registry model payload: `config/models.json` merged with runtime access state, served as `ModelCard` objects (`frontend/src/api/v2.ts`)
- health object: recent proxy traces, aggregated as above
- brand identity: official simple-icons hex colors and local brand SVG art (`frontend/src/brandMarkArt.ts`); the logo tile falls back from local brand SVG → brand short text → attributed same-origin public logo → generated initials
- flags: bundled flag-icons square SVGs keyed by `training_nation`

No card data is key-specific or written back to the registry; access and health stay runtime state.

## Interaction Contract

- Clicking the card body opens the global model-detail dialog: `openModelDetail` dispatches the `matts-v2-open-model-detail` window event, and `ModelDetailHost` (mounted once in `frontend/src/App.tsx`) renders the inspector; Escape closes it. Detail content is the model hero card data (`docs/model-hero-cards.md`).
- Surfaces that pass `onPrimary` (Chat contacts, dropdown options) make the body click **select** the model instead; those cards get a separate ⓘ info glyph that opens the detail dialog.
- The star toggles the shared favorites store without triggering the body action. `interactive=false` renders a passive card when a wrapping control owns the click.

## Favorites

Favorites are one shared store (`frontend/src/favorites.ts`): localStorage key `matts-v2-model-favorites`, capped at 48 IDs, migrated once from the legacy Chat sessionStorage state. Starring a model on any surface updates every other surface live, including other tabs via storage events.

Each surface leads with favorites and collapses the rest (V2-082):

- **Chat contacts** - an always-visible ⭐ **Pinned** strip holds starred contacts plus the active contact (even unstarred), above a collapsed **All contacts (N · M online)** drawer. The drawer is a flat list, route-enabled contacts first, then by name. Typing in contact search auto-expands it, starring regroups the lists immediately, and the drawer starts collapsed on every load — open state is not persisted.
- **Model dropdowns** (`ModelCardSelect`) - a card listbox with a filter input. Favorites list first; the rest sits behind a **More models (N)…** expander. Collapse only applies when at least one favorite matches and no filter text is entered, and the expander resets each time the popover opens.
- **Models grid** - when favorites exist and no filter is active, only favorite Big cards render, behind an **All models (N more)** button.

## Navigation

The Models workspace is now a tab inside Advanced. The drawer primary nav is Chat, Code, Research, and Create; Advanced opens via the drawer's Settings button, the Ctrl/Cmd+K quick switcher, or `#advanced` / `#models` URLs. Legacy `#models` links resolve race-free: the target Advanced tab is written to sessionStorage before Advanced activates, so `AdvancedPage` reads it at mount.

## Where The Pieces Live

- `frontend/src/components/modelCard.tsx` - `ModelIdentityCard`, `ModelLogo`, `ModelCardSelect`, brand color/flag data, `useNarrowViewport`
- `frontend/src/favorites.ts` - shared favorites store
- `frontend/src/pages/HeroPages.tsx` - `ModelDetailHost`, Chat contact pane grouping, Models grid and compare tray
- `frontend/src/App.tsx` - drawer nav, Settings entry, quick switcher, `#models` redirect, detail-host mount
- `backend/v2/services/model_showcase.py` - model payloads and `_HealthIndex`
- `src/console/services/model_scorecards.py` - `health_grade` thresholds and latency median
