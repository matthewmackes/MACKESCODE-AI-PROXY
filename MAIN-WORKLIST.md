# MAIN-WORKLIST

**Purpose:** Central tracking document for all development work in the Matts Value Set Claude Code Proxy project. All AI assistants should document planned work here before execution and update status during/after completion.

**Created:** 2026-07-07
**Last Updated:** 2026-07-08

## Work Tracking System

### Status Tags:
- 📋 `TODO` - Work not yet started
- 🔄 `IN_PROGRESS` - Actively being worked on
- ✅ `COMPLETED` - Work finished and verified
- 🚧 `BLOCKED` - Work blocked by dependencies
- 📝 `NEEDS_REVIEW` - Work complete but needs review
- ❌ `CANCELLED` - Work abandoned or no longer needed

### Priority Levels:
- **P0** - Critical/urgent (blocks everything)
- **P1** - High priority (should be done soon)
- **P2** - Medium priority (nice to have)
- **P3** - Low priority (future enhancements)

---

## Current Interface Refactoring Work

### Overview
The interface refactoring work consolidates previously separate components into a unified web console (`image-studio.py`) that provides:
- Image generation studio
- Claude Code terminal interface via tmux
- Text model chat interface
- Bing-like Image and Text interfaces with a public-wallpaper-style background
- Status dashboard with proxy health, costs, budgets, logs
- Reporting page for local usage and DigitalOcean billing
- Full-screen xterm.js terminal over WebSocket

### Current Status: 📋 `TODO`

### Tasks to Complete:

## Active Tasks

### Task ID: INT-001
**Title:** Clean up HTML template separation
**Status:** ✅ `COMPLETED`
**Priority:** P1
**Assigned To:** Codex
**Start Time:** 2026-07-07
**Estimated Duration:** 2 hours
**Completion Time:** 2026-07-07

**Progress Notes:**
- 2026-07-07: Extracted embedded login, terminal, and main console HTML into `templates/`.
- 2026-07-07: Added template loading/rendering helpers and updated `StudioHandler` to serve templates from files.
- 2026-07-07: Verified `/`, `/terminal`, `/health`, and `/version` render from extracted templates with `200 OK` responses.
- 2026-07-07: Tightened the Coding console command bar in `templates/main.html` to remove excess top whitespace above the embedded terminal.

**Description:** Move large HTML strings from `image-studio.py` to separate template files. The current file contains multiple large HTML strings (main interface, terminal interface, login page) embedded in Python code.

**Files to Modify:**
- `image-studio.py` - Remove HTML strings
- Create `templates/main.html` - Main interface template
- Create `templates/terminal.html` - Terminal interface template
- Create `templates/login.html` - Login page template
- Create `templates/` directory structure

**Implementation Steps:**
1. Extract HTML strings from `image-studio.py`
2. Create template loading function
3. Update `StudioHandler` to use templates
4. Test template rendering
5. Update documentation

**Completion Criteria:**
- [x] All HTML moved to template files
- [x] Template loading system working
- [x] All endpoints render correctly
- [x] Tests pass
- [x] Documentation updated

**Dependencies:** None
**Blocks:** INT-002 (Refactor HTTP handler class)

---

### Task ID: INT-002
**Title:** Refactor HTTP handler class
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 3 hours

**Progress Notes:**
- 2026-07-08: Product/platform review reaffirmed this as the top release-readiness task. `image-studio.py` is still a large monolith and should be split into explicit console, routing, lifecycle, persistence, and UI service boundaries before major new features.

**Description:** Break monolithic `StudioHandler` class into smaller, focused handler classes with separation of concerns.

**Target Structure:**
- `AuthHandler` - Authentication and token management
- `ApiHandler` - REST API endpoints (chat, tmux, terminal, status)
- `WebSocketHandler` - Terminal WebSocket connections
- `StaticHandler` - Static file serving
- `TemplateHandler` - HTML template rendering
- `DedicatedInferenceService` - DigitalOcean Dedicated lifecycle operations
- `ModelRegistryService` - global model source of truth, access status, pricing, and metadata
- `SessionService` - tmux lifecycle, display names, history, and activity attribution
- `UsageService` - cost, token, request, trace, and reporting persistence

**Files to Create/Modify:**
- Create `src/console/handlers/` directory
- Create handler classes in separate files
- Update `image-studio.py` to use new handlers
- Update server initialization

**Completion Criteria:**
- [ ] Handler classes created
- [ ] All endpoints migrated
- [ ] Backward compatibility maintained
- [ ] Dedicated, model registry, tmux session, and usage logic extracted from `image-studio.py`
- [ ] Console routes remain thin orchestration layers
- [ ] Tests pass
- [ ] Performance comparable or better

**Dependencies:** INT-001 (Template separation)
**Blocks:** INT-003 (Error handling improvements)

---

### Task ID: INT-003
**Title:** Improve error handling
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 1.5 hours

**Progress Notes:**
- 2026-07-08: Product/platform review reaffirmed standardized errors as a prerequisite for trace-first observability, evals, release diagnostics, and user-friendly lifecycle feedback.

**Description:** Standardize error responses across all endpoints and add comprehensive error logging.

**Files to Modify:**
- Create `src/console/utils/errors.py`
- Update all handler classes
- Add error logging configuration
- Update `image-studio.py`

**Key Improvements:**
1. Standard error response format
2. Comprehensive logging
3. Error categorization (client, server, auth, etc.)
4. Graceful degradation
5. User-friendly error messages

**Completion Criteria:**
- [ ] Error utility functions created
- [ ] All endpoints use standardized errors
- [ ] Error logging implemented
- [ ] Tests for error scenarios
- [ ] Documentation updated

**Dependencies:** INT-002 (Handler refactoring)
**Blocks:** INT-004 (Configuration system)

---

### Task ID: INT-004
**Title:** Add configuration system
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 2 hours

**Progress Notes:**
- 2026-07-08: Product/platform review reaffirmed this as prerequisite for separating release config, runtime state, secrets, gateway policy, and trace/eval settings.

**Description:** Move hardcoded constants to configuration file with environment variable support.

**Files to Create/Modify:**
- Create `config/console.yaml` or `config/console.json`
- Create configuration loading module
- Update all hardcoded values
- Add configuration validation

**Configuration Items:**
- Server host/port
- Model lists and costs
- Authentication settings
- Template paths
- Logging configuration
- Rate limiting settings

**Completion Criteria:**
- [ ] Configuration file created
- [ ] Configuration loader implemented
- [ ] All hardcoded values replaced
- [ ] Environment variable support
- [ ] Configuration validation
- [ ] Tests pass

**Dependencies:** INT-003 (Error handling improvements)
**Blocks:** INT-005 (Test suite creation)

---

### Task ID: INT-005
**Title:** Create comprehensive test suite
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 3 hours

**Progress Notes:**
- 2026-07-08: Platform review expanded this from handler tests into a release-gating suite covering routing, cost math, model registry sync, Dedicated state transitions, chat persistence, auth, proxy translation, and browser UI smoke tests.
- 2026-07-08: Created initial standard-library `unittest` smoke suite under `tests/` covering template loading/rendering, console health status, degraded status, and Prometheus metrics formatting. Documented `python3 -m unittest discover -s tests -v` in README.
- 2026-07-08: Added model-registry tests covering default-enable threshold behavior, route gating for serverless access audits, registry save/load filtering, disabled managed Dedicated selector visibility, and enriched model labels/status.

**Description:** Create unit and integration tests for the console interface.

**Files to Create:**
- Create `tests/` directory
- `tests/test_handlers.py` - Handler unit tests
- `tests/test_api.py` - API integration tests
- `tests/test_websocket.py` - WebSocket tests
- `tests/test_templates.py` - Template rendering tests
- `tests/conftest.py` - Test fixtures

**Test Coverage Goals:**
- 80%+ code coverage
- All handler classes tested
- API endpoints tested
- WebSocket connections tested
- Error scenarios covered
- Routing provenance and fallback behavior tested
- Cost, token, and budget calculations tested
- Dedicated lifecycle state transitions tested with fixtures
- Browser smoke tests for Code, Create, Console, and terminal workflows

**Completion Criteria:**
- [x] Test directory structure created
- [x] Core tests implemented
- [x] Test runner configured
- [ ] Coverage reports working
- [ ] CI integration ready
- [ ] Release check command documented and repeatable
- [ ] Browser smoke tests can run headlessly

**Dependencies:** INT-004 (Configuration system)
**Blocks:** None

---

### Task ID: INT-006
**Title:** Add health check endpoints
**Status:** ✅ `COMPLETED`
**Priority:** P1
**Assigned To:** Codex
**Start Time:** 2026-07-07
**Estimated Duration:** 1 hour
**Completion Time:** 2026-07-07

**Progress Notes:**
- 2026-07-07: Added `/health`, `/ready`, `/version`, and `/metrics` endpoints to `image-studio.py`.
- 2026-07-07: Added console health helpers, basic request counters, Prometheus text metrics, and README operations documentation.
- 2026-07-08: Re-verified `/health`, `/ready`, `/version`, and `/metrics` on local runtime; all returned `200 OK`, readiness reported proxy listening, and metrics emitted Prometheus counters/gauges.

**Description:** Add early health monitoring endpoints for operational visibility. Basic health and version endpoints should be implemented before the larger refactor chain so smoke tests and deployment checks are available while refactoring proceeds.

**Endpoints to Add:**
- `/health` - Basic service health
- `/ready` - Readiness for traffic
- `/metrics` - Prometheus metrics
- `/version` - Service version info

**Files to Modify:**
- Add to current `StudioHandler` route table, then move into `ApiHandler` during INT-002
- Create health check utility functions
- Add metrics collection

**Completion Criteria:**
- [x] Health endpoints implemented
- [x] Metrics collection working
- [x] Integration with monitoring
- [x] Documentation updated

**Dependencies:** None
**Blocks:** None

---

### Task ID: INT-014
**Title:** Redesign Image and Text interfaces with Bing-like layout
**Status:** 🔄 `IN_PROGRESS`
**Priority:** P1
**Assigned To:** Codex
**Start Time:** 2026-07-07
**Estimated Duration:** 3 hours

**Progress Notes:**
- 2026-07-07: Added exhaustive GLM-5 build artifact: `BING-UPDATE-SPEC.md`.
- 2026-07-07: Started first visible slice: three-tab navigation, cinematic Create shell, shared prompt, Text/Image mode toggle, and Console grouping.
- 2026-07-07: Added rich text response cards with answering model, original question, posed time, estimated cost, token metadata, answer body, model-specific glyphs, motion accents, and lightweight Markdown rendering.
- 2026-07-07: Fixed Create response scrolling so long chats grow the document normally, and added a hard top-level tab gate so Console content cannot bleed under other tabs.
- 2026-07-08: Reorganized the Console tab into Carbon-style operational areas for Inference Hosting Lifecycle, LLM Management, Accounting & Time, AgentBoard, and System Operations.
- 2026-07-08: Moved scroll restoration control into the document head and added load/pageshow top-pinning so the Console opens at the top instead of halfway down the page.
- 2026-07-08: Added Bing public wallpaper loading through `/api/wallpaper`, same-origin cached image proxying, Create wallpaper crossfade rotation, manual refresh, attribution caption, subtle cinematic sweep/grid effects, parallax, and reduced-motion handling.
- 2026-07-08: Requirements survey clarified the Create target: prioritize atmosphere first, then conversational presence, then creative workflow. The Create chat should feel alive over the wallpaper with subtle always-on desktop effects, mobile effects disabled, model-specific motion accents, progressive answer reveal, and text-model comparison inside the same conversation.
- 2026-07-08: Added Create chat pending model cards with model identity, routing stage, elapsed timer, routing-change notice, model-colored reply ripple, word-by-word answer reveal, click-to-skip reveal, and clean chat-history saves that persist final answer text only.
- 2026-07-08: Disabled the Create atmospheric effect layer on mobile/coarse-pointer devices and reduced wallpaper transition work there for better small-device performance.

**Specification:** `BING-UPDATE-SPEC.md`

**Description:** Redesign the Image Studio and Text Chat tabs to closely follow the Bing search/chat visual language: prominent centered input, clean translucent controls, large scenic background treatment, compact result surfaces, and a calm wallpaper-forward first view. The background should match the feel of Bing public wallpaper imagery without bundling copyrighted wallpaper assets directly.

**Design Requirements:**
1. Image and Text tabs should feel like sibling experiences with a shared Bing-like layout.
2. Use a public-wallpaper-style scenic background, preferably through a configurable remote Bing image endpoint or locally generated/approved fallback asset.
3. Keep controls readable over the background with accessible contrast.
4. Preserve all current Image Studio and Text Chat capabilities.
5. Avoid copying Microsoft/Bing logos, brand marks, proprietary text, or exact protected UI assets.
6. Chat bubbles should float over the wallpaper instead of blocking it with large opaque panels.
7. Add subtle always-on desktop atmosphere: foreground particles/light motes, time/weather-aware mood, and cursor-reactive light, with mobile atmospheric effects disabled.
8. Particles should pass behind chat bubbles, drift around bubble edges, and react to new messages with a noticeable assistant-reply sparkle/ripple.
9. Provider/model family styling should use curated overrides with automatic fallback styles; newly discovered DigitalOcean models should immediately receive generated style and 7-day global "new" sparkle.
10. Assistant replies should reveal word-by-word for newly received answers, save only final text, skip to full text when the message is clicked, and not replay animation for previous chats.
11. Waiting state should show model badge, routing stage, and elapsed time; fallback/routing changes should add a small notice above the reply and remain as a compact badge.
12. Add Create text-model comparison for up to five models: stacked result cards, no automatic scoring, compact chips plus Show Detail cost/latency table, and one saved comparison entry in chat history.
13. Comparison mode should be strict by default: selected unavailable models render an error card rather than silently falling back, while disabled Dedicated models may offer "Build again" with multi-model cost warnings.

**Files to Modify:**
- `image-studio.py` or extracted templates from INT-001
- Template/CSS files created by INT-001
- Documentation screenshots or usage notes if the interface changes materially

**Completion Criteria:**
- [ ] Image tab redesigned around a Bing-like centered prompt/search experience
- [ ] Text tab redesigned around a Bing-like chat/search experience
- [x] Background uses Bing public wallpaper-style imagery or configurable Bing image source with fallback
- [ ] Existing image generation, history, iteration, chat, save/load, and model controls still work
- [x] Create chat bubbles float over the wallpaper without a blocking white conversation panel
- [ ] Desktop atmosphere includes subtle particles/light motes, time/weather mood, and cursor light
- [x] Mobile disables atmospheric effects for performance
- [x] New assistant replies trigger model-specific sparkle/ripple motion
- [ ] Newly discovered models use generated styles and 7-day global sparkle
- [x] New assistant replies progressively reveal word-by-word and can be skipped by clicking the message
- [x] Waiting state shows model identity, routing stage, elapsed time, and fallback notice when routing changes
- [ ] Create supports text-model comparison for up to five selected models
- [ ] Comparison entries save as one chat-history entry and support "continue with this model"
- [ ] Mobile and desktop layouts verified visually
- [ ] Documentation updated if workflows or screenshots change

**Dependencies:** INT-001 (Template separation recommended; can be done in current HTML if prioritized)
**Blocks:** INT-012 (Theming system)

---

### Task ID: INT-015
**Title:** Add Digital Ocean Serverless Inference model catalog
**Status:** 🔄 `IN_PROGRESS`
**Priority:** P1
**Assigned To:** Codex
**Start Time:** 2026-07-07
**Estimated Duration:** 3 hours

**Progress Notes:**
- 2026-07-07: Added `config/models.json` as the persistent global model registry with enabled state, aliases, type, display name, provider, pricing, and context metadata.
- 2026-07-07: Added Console > Models control pane with add/remove/edit/save/reload controls and `/api/models` GET/POST endpoints.
- 2026-07-07: Updated `claude-DO.sh` to load model IDs, aliases, text/image test sets, validation, and proxy `--models` from the shared registry.
- 2026-07-07: Added Console > Inference split for Serverless Inference and Dedicated Inference, with Serverless remaining the fallback/control baseline.
- 2026-07-08: Requirements survey clarified `config/models.json` as the private-operator source of truth for model availability, metadata, access probe results, and enabled policy. Proxy sync should use both explicit Console sync and file modification polling, with visible stale/sync-failed states.
- 2026-07-08: Added unittest coverage for model route gating, registry persistence/filtering, managed Dedicated selector visibility, and enriched model labels/status.
- 2026-07-08: Hardened model-registry normalization so endpoint/token/credential fields are excluded from saved model entries; verified checked-in `config/models.json` has no explicit token or endpoint credential keys.
- 2026-07-08: Updated Serverless catalog sync to retain models missing from the latest DigitalOcean catalog as disabled `access_status=removed` entries with an explanatory error, keeping them visible in Console but out of active routing/selectors.

**Specification:** `DIGITALOCEAN-MODELS-SPEC.md`

**Description:** Fetch full catalog of Digital Ocean Serverless Inference models dynamically from Digital Ocean API and make them available in the API with selective visibility.

**Key Features:**
1. **Dynamic model fetching**: Get models from Digital Ocean API at startup
2. **Model filtering**: Use `?available=true/false` parameter on `/v1/models` endpoint
3. **Admin interface**: Web console admin panel to toggle model visibility
4. **Cost auto-detection**: Fetch cost rates from Digital Ocean API
5. **Caching**: Fall back to cached list if API fails
6. **Replace hardcoded**: Replace current hardcoded model list with dynamic Digital Ocean list
7. **Single source of truth**: Treat checked-in `config/models.json` as the operator's intended global model policy, excluding only tokens and endpoint credentials.
8. **Automatic catalog additions**: New DigitalOcean catalog models should be added to `config/models.json` with generated metadata and default enabled policy.
9. **Removed model handling**: Models missing from the DigitalOcean catalog should remain in the registry marked unavailable/removed, hidden from normal Code/Create selectors, and visible in Console management.
10. **Proxy sync reliability**: Proxy reload should use both explicit sync after registry saves and automatic `config/models.json` modification-time polling.
11. **Stale route protection**: If proxy registry reload fails, show a global registry sync failed alert, keep old routing active, and block sends only for newly selected stale models.
12. **Routing transparency**: Every routed request should expose requested model, routed model, fallback reason, provider, endpoint mode, and trace ID in Show Detail; mismatches should show a visible badge while details stay collapsed by default.

**Files to Create/Modify:**
- `do-anthropic-proxy.py` - Add Digital Ocean API client and model caching
- `image-studio.py` - Add admin interface for model selection
- Configuration system - Add model visibility settings
- Add model metadata cache file

**Implementation Steps:**
1. Create Digital Ocean API client to fetch available models
2. Add model caching with fallback to last-known list
3. Update `/v1/models` endpoint with `?available=true/false` parameter
4. Add admin panel in web console for model selection
5. Auto-detect cost rates from Digital Ocean pricing
6. Replace hardcoded `MATTS_VALUE_SET_MODELS` with dynamic list
7. Add tests for model fetching and filtering
8. Add generated metadata path for newly discovered DigitalOcean models
9. Mark catalog-removed models unavailable without deleting registry history
10. Add proxy registry mtime polling in addition to explicit Console sync
11. Add global stale/sync-failed UI state and stale-model send blocking
12. Add compact routing facts to request Show Detail surfaces

**Completion Criteria:**
- [ ] Digital Ocean API integration working
- [ ] Model filtering via endpoint parameter
- [ ] Admin interface for model selection
- [ ] Cost rate auto-detection
- [ ] Caching and fallback working
- [ ] Hardcoded models replaced
- [x] `config/models.json` remains the global source of truth for safe model policy, metadata, access state, and enabled state
- [x] Tokens and endpoint credentials are excluded from checked-in model registry data
- [ ] New catalog models are added automatically with generated metadata and default enabled policy
- [x] Removed catalog models are retained as unavailable and hidden from normal selectors
- [ ] Proxy reloads model registry changes by both explicit sync and file modification polling
- [ ] Registry sync failures trigger a global alert and block sends only for newly selected stale models
- [ ] Show Detail exposes compact routing facts for every routed request
- [ ] Model mismatch/fallback shows a visible badge while full details remain collapsed by default
- [ ] Tests for all new functionality

**Dependencies:** INT-004 (Configuration system) - for model visibility settings
**Blocks:** None - can work in parallel with other tasks

---

### Task ID: INT-016
**Title:** Add DigitalOcean Dedicated Inference lifecycle manager
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** Codex
**Start Time:** 2026-07-07
**Completion Time:** *Reopened 2026-07-08 for cost-governance scope*
**Estimated Duration:** 1 pass

**Progress Notes:**
- 2026-07-07: Added persistent Dedicated Inference config and event log files.
- 2026-07-07: Added DigitalOcean Dedicated API helpers for discovery, create, status polling, token creation, and delete.
- 2026-07-07: Added `/api/dedicated/*` Console endpoints for preflight, build, teardown, policy, status, events, sizes, and GPU/model config.
- 2026-07-07: Added Dedicated model registration/removal in the global model registry.
- 2026-07-07: Added chat routing support for Dedicated models with Serverless fallback provenance.
- 2026-07-07: Added Console > Inference panel with Serverless and Dedicated side-by-side controls, global cost meter, build sequence, discovery output, and activity timeline.
- 2026-07-07: Saved live Qwen3 Coder Dedicated config and launched DigitalOcean Dedicated Inference build `b4d236be-1bc2-41d3-b9b4-75630d64b137`; first selected GPU plan was unavailable in-region.
- 2026-07-08: Reconfigured Dedicated Inference to `Qwen/Qwen3-32B` on `gpu-mi300x1-192gb` in `atl1`; live build `7b259fa9-b984-4279-b89a-186d5a5a4b02` is currently `provisioning`.
- 2026-07-08: Added top-header dark mode toggle with persisted theme selection.
- 2026-07-08: Added global model defaulting rule: models without an explicit `enabled` flag auto-enable only when every configured price is below `$0.50`.
- 2026-07-08: Dedicated builds now register immediately as disabled managed model entries while provisioning, so they are visible in global model management before endpoint readiness.
- 2026-07-08: Direct requests to a Dedicated model that is not ready now return a human-friendly lifecycle error with state, server id, region, accelerator, endpoint readiness, and next step.
- 2026-07-08: Added GUI sparkle treatment for newly discovered model ids and managed Dedicated server entries.
- 2026-07-08: Added `selectable_text_models` so managed Dedicated models appear in Chat/Create selectors while active launcher/fallback selections remain limited to ready models.
- 2026-07-08: Hardened top-level tab hiding and navigation scroll reset so Console no longer remains visible beneath Coding/Create or starts halfway down the page.
- 2026-07-08: Improved Dedicated chat lifecycle feedback so the UI shows a compact user-friendly status card instead of raw JSON, with diagnostics tucked behind a details toggle.
- 2026-07-08: Added DigitalOcean account status, masked account identity, prepay/balance status, month-to-date usage, build age, and last-status age to Dedicated lifecycle feedback.
- 2026-07-08: Added nested Dedicated accelerator failure detection; current Qwen3-32B build is marked `failed` because DigitalOcean reported `gpu-mi300x1-192gb` as invalid for the model.
- 2026-07-08: Tore down failed `atl1` MI300X Dedicated build after DO reported invalid accelerator state.
- 2026-07-08: Rebuilt Qwen3-32B Dedicated in `tor1` on `gpu-mi325x1-256gb`; new build `a7e947fa-73fa-40f4-a26e-ee8d46344acf` is `provisioning`.
- 2026-07-08: Relaxed nested accelerator `invalid` detection for pending/provisioning specs without accelerator assignment to avoid prematurely failing valid in-progress builds.
- 2026-07-08: Corrected endpoint display to clear stale create-response endpoint values until latest DigitalOcean status reports an endpoint.
- 2026-07-08: Qwen3-32B Dedicated is active in `tor1` on `gpu-mi325x1-256gb`; proxy chat requests now route directly to Dedicated and return visible answer text.
- 2026-07-08: Added DigitalOcean platform uptime, unresolved incidents, account status, prepay/balance, and month-to-date usage to the Console lifecycle health strip.
- 2026-07-08: Replaced the inaccurate top-toolbar runtime/token cost indicator with a DigitalOcean cost pill showing account month-to-date, last-24-hour total, and month-to-date Dedicated server estimate from lifecycle runtime.
- 2026-07-08: Connected Dedicated proxy routing to the GUI lifecycle state: the Claude Code proxy now uses the Dedicated endpoint/token/model slug, returns human-friendly not-ready lifecycle errors, auto-syncs when the global model registry changes, and exposes sync state/actions in Console.
- 2026-07-08: Fixed Claude Code 400s against Qwen3-32B Dedicated by clamping Dedicated max output tokens before upstream requests and retrying context-length 400s with a lower calculated token budget.
- 2026-07-08: Added live DigitalOcean Serverless catalog import from `/v1/models`, expanded the registry/UI to show all serverless model classes, and default-enable newly discovered models only when every known price is below `$0.45` per 1M/unit.
- 2026-07-08: Added access probes for cheap serverless text models during catalog refresh, so low-cost models that the current model access key cannot call remain visible but disabled with `access_status=forbidden` instead of producing provider 403s in Chat/Code.
- 2026-07-08: Added automated model access key verification with masked key source/fingerprint display and a full serverless text LLM audit that probes each model, disables forbidden models, enables allowed low-cost models, and syncs the proxy registry.
- 2026-07-08: Updated local DigitalOcean model access token files and fixed Console/launcher startup so existing token files are preserved instead of being overwritten by the embedded fallback key.
- 2026-07-08: Fixed forbidden Serverless LLM routing in Code by requiring audited `access_status=ok` before serverless text models are exposed to the Console launcher or proxy; Haiku 4.5 now stays disabled and local requests are rejected before reaching DigitalOcean.
- 2026-07-08: Consolidated runtime model selection around `config/models.json` as the source of truth: the proxy now refreshes active models, aliases, and pricing from the registry instead of relying on stale startup JSON, and both Console and launcher pass the same config path.
- 2026-07-08: Enriched global model selectors with training-origin country, human-readable cost labels, brand/logo metadata, access-state greyout, and use-case/comparison cards shared across Code, Create, Chat, image generation, and Dedicated fallback controls.
- 2026-07-08: Rebuilt the Code session picker with enriched live/previous session cards, inline tmux rename support, new-session highlighting, session metadata persistence, and previous-session read-only red styling.
- 2026-07-08: Consolidated Code session create/select/rename/stop into the running tmux chooser with display-name/tmux-id separation, generated `STARTTIME_` names, preset-based new session creation, pinned current/live/previous groups, and read-only previous sessions.
- 2026-07-08: Requirements survey reopened this task to harden cost-governance for private-operator dependability. Completed lifecycle work remains checked below, but remaining scope now emphasizes daily budget visibility, budget override logging, idle/unhealthy countdown enforcement, and budget-blocked fallback behavior.

**Description:** Build an enterprise-class Dedicated Inference control plane that automates DigitalOcean Dedicated Inference creation, registration, teardown, routing fallback, billing estimation, idle policy visibility, monitoring events, and Serverless parity controls.

**Files Modified:**
- `image-studio.py`
- `templates/main.html`
- `MAIN-WORKLIST.md`

**Reopened Scope:**
1. Add a global daily Dedicated budget meter showing dollars used / daily limit, with 70% warning and 90% critical styling.
2. Block new Dedicated builds by default when daily budget is critical, but allow current console-token users to override.
3. Log every budget override with timestamp, model, region/GPU, fallback, estimated cost, budget state, and user/session identifier.
4. Add background idle enforcement outside page-driven refresh: warn everywhere at idle threshold, show teardown countdown, and auto-destroy after the configured idle teardown window.
5. Add keep-alive extension choices of 5 minutes, 10 minutes, 30 minutes, and 1 hour; if no successful Dedicated work happens during the extension, tear down immediately when it expires.
6. Count only successful model requests as Dedicated work for idle reset.
7. Add unhealthy-server countdown: after 3 consecutive failed health/model checks, show teardown countdown and destroy after 5 minutes if not recovered.
8. While unhealthy countdown is active, new Dedicated requests should fail fast with a clear unhealthy message emphasizing how to keep working.
9. Preserve full Dedicated lifecycle diagnostics locally for 30 days after teardown, then archive old records as compressed files in the app cache directory.
10. After auto/manual teardown, leave the Dedicated model visible but disabled with a "Build again" action in model selectors, requiring estimated hourly cost confirmation.
11. Build-again confirmations should warn, but allow override, if the daily budget would be exceeded.
12. If Dedicated is blocked by budget, Code/Create should automatically route to configured Serverless fallback with a prominent pre-reply message and trace reason `budget_blocked_fallback`.

**Completion Criteria:**
- [x] Dedicated state/config persisted locally
- [x] DO Dedicated API build/status/delete/token endpoints wrapped
- [x] Console build/preflight/teardown/policy controls added
- [x] Global Dedicated model add/remove wired to model registry
- [x] Dedicated chat routing and Serverless fallback metadata added
- [x] Live elapsed/cost UI meter added
- [x] Activity timeline and step variation added
- [x] Live DO account/token/scopes verified against a real Dedicated build
- [x] Dedicated endpoint request shape verified against the deployed model runtime
- [ ] Idle auto-teardown background enforcement added outside page-driven refresh
- [ ] Global daily Dedicated budget meter added to the top interface
- [ ] Daily budget critical state blocks new Dedicated builds unless overridden
- [ ] Budget override decisions are logged with full build context
- [ ] Idle warning and teardown countdown alerts appear across Code, Create, and Console
- [ ] Keep-alive extension choices implemented with teardown-after-unused-extension behavior
- [ ] Unhealthy-server countdown tears down after repeated failed health/model checks
- [ ] Full lifecycle diagnostics retained for 30 days and compressed into app-cache archives
- [ ] Disabled Dedicated models expose guarded "Build again" in selectors
- [ ] Budget-blocked Dedicated routing falls back to Serverless with prominent notice and `budget_blocked_fallback` trace reason

**Dependencies:** INT-015 (global model registry), DigitalOcean Dedicated Inference account access
**Blocks:** None

---

### Task ID: INT-017
**Title:** Add detailed Hero Card descriptions for each model
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 2.5 hours

**Progress Notes:**
- *None yet*

**Specification:** `MODEL-HERO-CARD-SPEC.md`

**Description:** Create impressive, detailed Hero Cards for each model showing what they're good at, what they're not, what to expect, and alternatives.

**Key Features:**
1. **Detailed modal display**: Full-page detailed view when clicking "Info" button
2. **Manual curation**: Well-written descriptions for each model
3. **Feature-rich design**: Icons, badges, metrics, and visual elements
4. **Standard sections**: Strengths, weaknesses, use cases, alternatives
5. **Separate storage**: Model descriptions stored in JSON/YAML files for easy updates

**Files to Create/Modify:**
- Create `config/model-descriptions/` directory with JSON files
- Update `image-studio.py` to add model info modal
- Add API endpoint `/api/models/{id}/info`
- Update templates with model info button and modal HTML/CSS
- Create hero card styling (feature-rich design)

**Implementation Steps:**
1. Research and write detailed descriptions for each model
2. Create JSON structure for model metadata and descriptions
3. Add "Info" button next to each model in the UI
4. Implement modal overlay with hero card design
5. Add API endpoint to serve model information
6. Create visually impressive card design with icons and metrics
7. Test across all models and screen sizes

**Completion Criteria:**
- [ ] Detailed descriptions written for all current models
- [ ] JSON description files created and organized
- [ ] Model info modal implemented with feature-rich design
- [ ] API endpoint serving model information
- [ ] Info buttons added throughout UI (chat, image studio, model selection)
- [ ] Responsive design working on all screen sizes
- [ ] Documentation updated

**Dependencies:** INT-001 (Template separation) - for modal HTML/CSS
**Blocks:** None

---

### Task ID: INT-018
**Title:** Separate release config, runtime state, and secrets
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 2 hours

**Progress Notes:**
- 2026-07-08: Added from product/platform review. Current tracked config and local runtime state need stricter separation before release.

**Description:** Establish clean boundaries between shipped defaults, operator configuration, runtime state, cache files, generated secrets, and live cloud resource metadata. The repository should contain examples and schemas, not local mutable state from a running deployment.

**Key Improvements:**
1. Move live Dedicated Inference state out of tracked `config/dedicated-inference.json`.
2. Provide `config/dedicated-inference.example.json` with safe placeholders.
3. Add schema/version fields for model registry and Dedicated config.
4. Add migration/load helpers for old local config files.
5. Ensure tokens, endpoint credentials, event logs, and generated state stay in app/cache directories.
6. Document which files are release config vs runtime state.

**Files to Create/Modify:**
- `config/dedicated-inference.example.json`
- `config/models.schema.json` or equivalent validation helper
- `image-studio.py`
- `do-anthropic-proxy.py`
- `.gitignore`
- `README.md`
- `SECURITY.md`

**Completion Criteria:**
- [ ] Live DigitalOcean resource metadata is not tracked in release config
- [ ] Example config files are safe to publish
- [ ] Runtime state paths are documented
- [ ] Existing local installs migrate without data loss
- [ ] Config validation fails with human-readable errors
- [ ] Tests cover missing, old, and malformed config

**Dependencies:** INT-004 (Configuration system)
**Blocks:** Release packaging and broader team use

---

### Task ID: INT-019
**Title:** Reconcile release documentation with current platform behavior
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 1 hour

**Progress Notes:**
- 2026-07-08: Added from product/platform review. README and SECURITY still describe older key behavior and should be brought back in sync with the cleaned launcher and current Console.

**Description:** Update the release documentation so setup, security, model registry behavior, Dedicated Inference lifecycle, cost reporting, and operational commands match the current code.

**Files to Modify:**
- `README.md`
- `SECURITY.md`
- `CHANGELOG.md`
- `install/README.md`
- `CLAUDE.md`

**Completion Criteria:**
- [ ] No stale embedded-key documentation remains
- [ ] Model registry and `--list-models` behavior documented accurately
- [ ] Serverless and Dedicated Inference workflows documented
- [ ] Cost, billing, and DigitalOcean token scopes documented
- [ ] Release cleanup and runtime-state boundaries documented
- [ ] Quickstart verified on a clean checkout

**Dependencies:** INT-018 (Config/state separation) recommended
**Blocks:** Public release readiness

---

### Task ID: INT-020
**Title:** Add trace-first LLM observability
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 3 hours

**Progress Notes:**
- 2026-07-08: Added from product/platform review. Industry-leading LLM platforms expose request traces before evals and dashboards; the current usage log is useful but not trace-grade.

**Description:** Create a first-class trace model for every LLM, image, Dedicated, proxy, and Claude Code routing action. Traces should make it possible to debug model choice, provider failures, retries, token/cost math, tool calls, latency, and user-visible output.

**Trace Fields:**
1. Request ID and parent trace ID
2. Session/chat/tmux identifiers
3. Requested model, routed model, provider, endpoint mode
4. Prompt/message summary and privacy-safe content controls
5. Latency, status, retry/fallback path, and upstream request ID where available
6. Token usage, cost, budget attribution, and cache/fallback result
7. Error category, human message, raw diagnostic pointer

**Files to Create/Modify:**
- `src/observability/traces.py` or equivalent module
- Trace JSONL or SQLite persistence
- `do-anthropic-proxy.py`
- `image-studio.py`
- `templates/main.html`

**Completion Criteria:**
- [ ] Every chat/proxy/Dedicated request emits a trace record
- [ ] Console exposes trace search/filter by model, session, status, and cost
- [ ] Message-level Show Detail links to trace ID
- [ ] Trace data redaction policy exists
- [ ] Tests cover trace emission for success, fallback, and failure

**Dependencies:** INT-002 (Handler refactoring), INT-005 (Test suite)
**Blocks:** INT-021 (Evaluation and model comparison workflows)

---

### Task ID: INT-021
**Title:** Add evaluation and model comparison workflows
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 4 hours

**Progress Notes:**
- 2026-07-08: Added from product/platform review. The platform needs eval datasets, regression checks, and side-by-side model comparison to be industry competitive.

**Description:** Build an evaluation layer for testing prompts, models, routing policies, and Dedicated vs Serverless behavior before changes become defaults.

**Key Features:**
1. Eval datasets stored locally with versioned examples.
2. Side-by-side model comparisons with cost, latency, and answer-quality notes.
3. Regression runs before model registry or prompt changes.
4. Human rating and lightweight LLM-as-judge support.
5. Evaluation history and result export.
6. Release gate summary for changed routing/model policies.

**Files to Create/Modify:**
- `evals/` directory
- Eval runner module
- Console Evals tab or AgentBoard Evals expansion
- `config/models.json`
- `templates/main.html`

**Completion Criteria:**
- [ ] Eval dataset format defined
- [ ] Eval runner supports selected models and prompts
- [ ] Console can run and compare evals
- [ ] Results include cost, latency, failures, and selected answer
- [ ] Registry changes can be checked against a baseline
- [ ] Documentation explains how to add evals

**Dependencies:** INT-020 (Trace-first observability)
**Blocks:** Enterprise model governance

---

### Task ID: INT-022
**Title:** Add AI gateway reliability and cost controls
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 3 hours

**Progress Notes:**
- 2026-07-08: Added from product/platform review. Industry gateways include failover, rate limits, caching, circuit breakers, quota controls, and provider policy routing.

**Description:** Expand the proxy from a model adapter into a policy-driven AI gateway with configurable reliability, cost, and abuse-protection behavior.

**Key Features:**
1. Provider/model failover policies with explicit priority and constraints.
2. Circuit breakers for repeated 4xx/5xx/provider failures.
3. Response/request caching for deterministic or development workloads.
4. Per-model, per-session, and global rate limits.
5. Budget-aware routing and cooldown behavior.
6. Retry policies with trace-visible reason codes.

**Files to Create/Modify:**
- `do-anthropic-proxy.py`
- Gateway policy config
- `image-studio.py`
- `templates/main.html`
- Tests for gateway behavior

**Completion Criteria:**
- [ ] Gateway policy schema exists
- [ ] Failover and circuit breaker behavior implemented
- [ ] Rate limits and quotas emit useful client errors
- [ ] Cache can be enabled/disabled per route
- [ ] Console shows active gateway policy and recent decisions
- [ ] Tests cover fallback, circuit break, cache hit, and rate-limit cases

**Dependencies:** INT-004 (Configuration system), INT-020 (Trace-first observability)
**Blocks:** High-volume/team usage

---

### Task ID: INT-023
**Title:** Add enterprise identity, RBAC, and audit governance
**Status:** 📋 `TODO`
**Priority:** P2
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 4 hours

**Progress Notes:**
- 2026-07-08: Added from product/platform review. Token auth is acceptable for private single-operator use, but team or enterprise use needs identity and authorization boundaries.

**Description:** Replace single shared console-token semantics with user/session identity, scoped permissions, and audit logging suitable for a trusted team deployment.

**Key Features:**
1. User identity model with session management.
2. Role-based permissions for Code, Create, Console, model admin, billing, Dedicated build/teardown, and tmux kill/send actions.
3. Optional OIDC/SSO integration plan.
4. Scoped service tokens for automation.
5. Audit log for sensitive actions.
6. Secret/token rotation workflow.

**Files to Create/Modify:**
- Auth/session module
- Audit log persistence
- `image-studio.py`
- `templates/login.html`
- `templates/main.html`
- `SECURITY.md`

**Completion Criteria:**
- [ ] RBAC roles and permissions defined
- [ ] Sensitive actions are authorization checked
- [ ] Audit log records model/admin/tmux/Dedicated actions
- [ ] Token/session rotation is documented
- [ ] Login UX supports user sessions
- [ ] Security tests cover denied actions

**Dependencies:** INT-010 (Improve authentication), INT-020 (Trace-first observability)
**Blocks:** Multi-user deployment

---

### Task ID: INT-024
**Title:** Add release packaging, upgrade, and rollback discipline
**Status:** 📋 `TODO`
**Priority:** P1
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 3 hours

**Progress Notes:**
- 2026-07-08: Added from product/platform review as inferred item 9. Industry-ready products need repeatable releases, install validation, migrations, and rollback.

**Description:** Make the platform releaseable from a clean checkout and upgradeable on an existing host without losing runtime state or leaving cloud resources orphaned.

**Key Features:**
1. Versioned release checklist.
2. Install/upgrade/migration scripts for config and runtime state.
3. Backup/restore procedure for registry, chats, usage logs, tmux registry, and Dedicated state.
4. Rollback instructions.
5. Service health validation after upgrade.
6. Release notes template with breaking-change, migration, and verification sections.

**Files to Create/Modify:**
- `RELEASE.md`
- `CHANGELOG.md`
- `install/`
- Migration helpers
- Health-check script

**Completion Criteria:**
- [ ] Clean checkout setup documented and tested
- [ ] Upgrade path preserves runtime state
- [ ] Rollback path documented
- [ ] Release checklist exists
- [ ] Health validation command exists
- [ ] Changelog includes migration notes

**Dependencies:** INT-018 (Config/state separation), INT-019 (Documentation reconciliation), INT-005 (Test suite)
**Blocks:** External release

---

## P2 Tasks - Enhancements

### Task ID: INT-007
**Title:** Improve WebSocket terminal
**Status:** 📋 `TODO`
**Priority:** P2
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 2 hours

**Progress Notes:**
- *None yet*

**Description:** Complete WebSocket terminal polish. Terminal resizing and tmux-backed persistence already exist in the current console, so this task should focus on verification, edge cases, and missing operational polish.

**Improvements:**
1. Cross-browser resizing verification and bug fixes
2. Character encoding improvements
3. Session lifecycle cleanup and reconnect edge cases
4. Terminal logging
5. Connection pooling if profiling shows it is needed

**Files to Modify:**
- Update `WebSocketHandler` class
- Refine terminal session management
- Improve encoding handling

**Completion Criteria:**
- [ ] Terminal resizing verified across supported browsers
- [ ] Encoding issues resolved
- [ ] Session reconnect and cleanup edge cases covered
- [ ] Connection pooling added or explicitly documented as unnecessary
- [ ] Tests updated

**Dependencies:** INT-002 (Handler refactoring)
**Blocks:** None

---

### Task ID: INT-008
**Title:** Add API versioning
**Status:** 📋 `TODO`
**Priority:** P2
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 1.5 hours

**Progress Notes:**
- *None yet*

**Description:** Implement API versioning with backward compatibility support.

**Changes:**
- `/api/v1/` prefix for all endpoints
- Version negotiation
- Deprecation warnings
- Migration documentation

**Files to Modify:**
- Update route definitions
- Add version middleware
- Update documentation

**Completion Criteria:**
- [ ] Versioned API endpoints
- [ ] Backward compatibility
- [ ] Deprecation system
- [ ] Migration guide
- [ ] Tests updated

**Dependencies:** INT-002 (Handler refactoring)
**Blocks:** None

---

### Task ID: INT-009
**Title:** Add rate limiting
**Status:** 📋 `TODO`
**Priority:** P2
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 2 hours

**Progress Notes:**
- *None yet*

**Description:** Implement rate limiting to protect against abuse.

**Features:**
- Token-based rate limiting
- Configurable limits per endpoint
- Rate limit headers
- Quota management

**Files to Create/Modify:**
- Create rate limiting middleware
- Update handler classes
- Add configuration options

**Completion Criteria:**
- [ ] Rate limiting implemented
- [ ] Configurable limits
- [ ] Proper headers
- [ ] Abuse protection
- [ ] Tests added

**Dependencies:** INT-004 (Configuration system)
**Blocks:** None

---

### Task ID: INT-010
**Title:** Improve authentication
**Status:** 📋 `TODO`
**Priority:** P2
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 2.5 hours

**Progress Notes:**
- *None yet*

**Description:** Enhance authentication system with JWT tokens and session management.

**Improvements:**
1. JWT token support
2. Token rotation
3. Session management
4. Refresh tokens
5. Audit logging

**Files to Modify:**
- Update `AuthHandler` class
- Add JWT utilities
- Implement session storage
- Add audit logging

**Completion Criteria:**
- [ ] JWT authentication
- [ ] Token rotation
- [ ] Session management
- [ ] Audit logging
- [ ] Security tests

**Dependencies:** INT-002 (Handler refactoring)
**Blocks:** None

## P3 Tasks - Future Enhancements

### Task ID: INT-011
**Title:** Add plugin system
**Status:** 📋 `TODO`
**Priority:** P3
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 4 hours

**Progress Notes:**
- *None yet*

**Description:** Create plugin system for modular interface components and third-party extensions.

**Features:**
- Plugin lifecycle management
- Extension points
- Third-party plugin support
- Plugin configuration

**Files to Create:**
- Plugin framework
- Plugin registry
- Extension point definitions
- Plugin examples

**Completion Criteria:**
- [ ] Plugin framework created
- [ ] Extension points defined
- [ ] Example plugins
- [ ] Documentation
- [ ] Tests

**Dependencies:** INT-002 (Handler refactoring), INT-004 (Configuration system)
**Blocks:** None

---

### Task ID: INT-012
**Title:** Add theming system
**Status:** 📋 `TODO`
**Priority:** P3
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 3 hours

**Progress Notes:**
- *None yet*

**Description:** Implement theming system with light/dark mode support.

**Features:**
- Light/dark mode toggle
- Customizable colors
- CSS variable system
- Theme persistence

**Files to Modify:**
- Update templates with CSS variables
- Add theme switching JavaScript
- Theme configuration
- Theme storage

**Completion Criteria:**
- [ ] Theme switching working
- [ ] CSS variable system
- [ ] Theme persistence
- [ ] Browser preferences respected
- [ ] Documentation

**Dependencies:** INT-001 (Template separation)
**Blocks:** None

---

### Task ID: INT-013
**Title:** Add analytics dashboard
**Status:** 📋 `TODO`
**Priority:** P3
**Assigned To:** *Unassigned*
**Start Time:** *Not started*
**Estimated Duration:** 4 hours

**Progress Notes:**
- *None yet*

**Description:** Create analytics dashboard for usage statistics and performance metrics.

**Features:**
- Usage statistics visualization
- Cost tracking charts
- Performance metrics
- Export functionality

**Files to Create:**
- Analytics data collection
- Dashboard templates
- Chart rendering
- Export utilities

**Completion Criteria:**
- [ ] Analytics collection
- [ ] Dashboard UI
- [ ] Chart visualizations
- [ ] Export functionality
- [ ] Documentation

**Dependencies:** INT-001 (Template separation), INT-004 (Configuration system)
**Blocks:** None

---

## Work Execution Protocol for AI Assistants

### Before Starting Work:
1. **Check MAIN-WORKLIST.md** for existing tasks and priorities
2. **Create a new task entry** if work isn't already documented
3. **Update task status** to `IN_PROGRESS` before beginning
4. **Note start time** and **assistant name/type**

### During Work:
1. **Document progress** in task notes section
2. **Update status** if blocked or dependencies change
3. **Add intermediate commits** with clear messages

### After Completing Work:
1. **Update status** to `COMPLETED` or `NEEDS_REVIEW`
2. **Add completion timestamp**
3. **Document any follow-up work needed**
4. **Run verification tests** if applicable
5. **Update related documentation** (CLAUDE.md, README.md)

### Work Format Example:
```
### Task ID: INT-001
**Title:** Clean up HTML template separation
**Status:** 🔄 `IN_PROGRESS`
**Priority:** P1
**Assigned To:** Claude (general-purpose agent)
**Start Time:** 2026-07-07 15:30
**Estimated Duration:** 2 hours

**Description:** Move large HTML strings from image-studio.py to separate template files...

**Progress Notes:**
- 2026-07-07 15:35: Created templates/ directory with main.html template
- 2026-07-07 15:45: Implemented template loading function
- 2026-07-07 16:00: Refactored main HTML template (70% complete)

**Completion Criteria:**
- [ ] All HTML moved to template files
- [ ] Template loading system working
- [ ] Tests pass
- [ ] Documentation updated

**Dependencies:** None
**Blocks:** INT-002 (Refactor HTTP handler class)
```

---

## Recent Work History

### 2026-07-07 - Interface Refactoring Planning
- **Status:** Planning and documentation phase
- **Work Completed:**
  - Created MAIN-WORKLIST.md for tracking interface refactoring work
  - Documented 14 specific tasks with priorities and dependencies
  - Established work tracking protocol for AI assistants
  - Analyzed current `image-studio.py` structure (1873 lines)

### 2026-07-07 - Worklist Review Corrections
- **Status:** Review corrections applied
- **Work Completed:**
  - Made early health endpoints independent from the full test-suite task
  - Added progress-note placeholders to task entries
  - Re-scoped WebSocket terminal polish around remaining gaps because resizing and tmux persistence already exist
  - Added INT-014 for Bing-like Image/Text interface redesign with public-wallpaper-style background requirements

### Current State Analysis:
- **File:** `image-studio.py` (modified 2026-07-07 15:09)
- **Lines:** 1873
- **Key Issues Identified:**
  1. **Monolithic structure** - Single large file with mixed concerns
  2. **Embedded HTML** - Large HTML strings in Python code
  3. **Limited error handling** - Inconsistent error responses
  4. **Hardcoded values** - Constants scattered throughout code
  5. **No comprehensive tests** - Limited testing coverage
  6. **Authentication limitations** - Basic token system only

### Key Features Currently Working:
- Unified HTTP handler (`StudioHandler`)
- WebSocket terminal support via tmux
- Combined image studio and console interfaces
- Authentication token system
- Tmux session management
- Status dashboard with proxy health monitoring
- Cost tracking and budget enforcement
- Image generation with prompt builder
- Chat interface for text models

### Next Immediate Actions (P1 Priority):
1. **Start with INT-006:** Early health check endpoints (1 hour)
2. **Then INT-001:** HTML template separation (2 hours)
3. **Follow with INT-014:** Bing-like Image/Text redesign (3 hours)
4. **Continue with INT-002:** HTTP handler refactoring (3 hours)
5. **Then INT-003:** Error handling improvements (1.5 hours)
6. **Then INT-004:** Configuration system (2 hours)
7. **Then INT-005:** Comprehensive test suite (3 hours)

**Total P1 Work Estimate:** 15.5 hours

---

## Project Structure Notes

### Current File Organization:
```
DO-ClaudeCode-Proxy/
├── image-studio.py          # Unified web console (1873 lines)
├── do-anthropic-proxy.py    # API proxy server
├── claude-DO.sh            # Main launcher script
├── matts-console.py         # Console entry point
├── matts-image              # Image generator CLI
├── claude-*                # Model wrapper scripts
└── MAIN-WORKLIST.md        # This file
```

### Target Architecture:
```
DO-ClaudeCode-Proxy/
├── src/
│   ├── console/
│   │   ├── handlers/       # HTTP handlers
│   │   ├── templates/      # HTML templates
│   │   ├── websocket/      # WebSocket handling
│   │   └── utils/         # Utility functions
│   ├── proxy/             # API proxy logic
│   └── cli/              # CLI interfaces
├── tests/                # Test suite
├── config/              # Configuration files
└── docs/               # Documentation
```

---

## Next Immediate Actions (P1)

1. **Start with INT-006:** Early health check endpoints
2. **Then INT-001:** HTML template separation
3. **Follow with INT-014:** Bing-like Image/Text redesign
4. **Continue with INT-002:** HTTP handler refactoring
5. **Then INT-003:** Error handling improvements
6. **Then INT-004:** Configuration system
7. **Then INT-005:** Comprehensive test suite

## Dependencies & Blockers

- INT-006 is intentionally independent so health smoke checks can land before the larger refactor chain.
- INT-014 depends on INT-001 when possible, but can be implemented directly in the current HTML if UI redesign is prioritized ahead of template extraction.
- Most refactor tasks should proceed sequentially because they touch the same `image-studio.py` surfaces.

## Quality Standards

- All code changes must include tests
- Documentation must be updated
- Backward compatibility must be maintained
- Security considerations must be addressed
- Performance impact must be evaluated

---

*This document should be updated by all AI assistants working on the project.*
*Last updated by: Codex*
*Timestamp: 2026-07-07*
