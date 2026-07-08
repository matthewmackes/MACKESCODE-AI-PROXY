# BING-UPDATE-SPEC

Purpose: Exhaustive implementation instructions for GLM-5 to build the "Bing Update" GUI transformation in the Matts Value Set Claude Code Proxy console.

Audience: GLM-5 coding agent.

Date: 2026-07-07

## Role

You are GLM-5 acting as a senior frontend/backend implementation agent inside this repository. Your job is to implement the Bing Update exactly as specified here, preserving existing working behavior while transforming the Create experience into a cinematic, Bing-inspired interface.

Do not treat this as a brainstorming brief. Treat it as the source of truth for the build.

## Repository Context

Primary files currently involved:

- `image-studio.py`: current unified web console. It contains the main HTML/CSS/JS, login HTML, terminal HTML, routes, API handlers, WebSocket terminal handling, image generation, chat, status, reporting, and AgentBoard UI.
- `MAIN-WORKLIST.md`: central work tracking document.
- `AI-WORK-PROTOCOL.md`: working protocol for AI assistants.
- `README.md`: user-facing project overview.

Related worklist task:

- `INT-014`: Redesign Image and Text interfaces with Bing-like layout.

Recommended dependency:

- `INT-001`: Template separation is recommended before or during this work. If not complete, you may implement in current `image-studio.py`, but keep changes organized and easy to extract later.

## High-Level Product Decision

The UI should become three primary areas:

1. `Coding`
   - Leave the existing Coding/Claude terminal experience as is.
   - Do not redesign the terminal workbench as part of this task.

2. `Create`
   - Combine Image and Text into one Bing-inspired cinematic creation interface.
   - This is the primary target of the Bing Update.

3. `Console`
   - Combine all other non-coding operational views under one area.
   - Existing Ops, Reporting, AgentBoard, and similar utility views should remain dense and functional.
   - They may be visually grouped under Console, but should not receive the cinematic Bing treatment in this task.

## Non-Negotiable Design Direction

The Create page must look cinematic, beautiful, bold, and world class.

It should be very close in size and layout feel to Bing's public homepage/search experience, while avoiding Microsoft/Bing logos, brand marks, exact proprietary assets, or trademarked in-app naming.

The intended feel:

- Large scenic wallpaper background.
- Large centered prompt on first load.
- Minimal chrome.
- Cinematic motion.
- High-polish typography.
- Prominent but elegant prompt box.
- Controls minimized unless immediately useful.
- Results move the experience into a Bing-chat/search-like result state.

Do not create a generic dashboard. Do not make the Create screen feel like a form-heavy admin panel.

## Brand and Legal Constraints

Do:

- Build a Bing-inspired layout and interaction model.
- Use public-wallpaper-style scenic imagery.
- Use Microsoft-like typography stacks.
- Use clean, rounded, search-like surfaces.

Do not:

- Use Microsoft or Bing logos.
- Use Bing wordmarks in the UI.
- Copy exact Bing proprietary text, icons, or protected UI assets.
- Bundle copyrighted wallpaper assets directly unless licensing is explicitly verified.

Use neutral app branding such as the existing console/private-use branding.

## Navigation Requirements

The main app navigation must become three primary tabs:

- `Coding`
- `Create`
- `Console`

Mapping:

- Coding: existing Claude Code terminal/coding tab, left as is.
- Create: combined Image/Text Bing-inspired interface.
- Console: all other utility/operational tabs grouped together.

Implementation guidance:

- Preserve all current feature access.
- If grouping utility tabs under Console requires a secondary nav, implement it cleanly inside Console.
- Do not remove Ops, Reporting, AgentBoard, history, status, budget, or test-model capabilities.

## Create Page Core Behavior

Create combines Text and Image in one screen.

Mode model:

- One unified prompt.
- A segmented pill mode toggle inside or directly attached to the prompt area.
- Modes: `Text` and `Image`.
- Default mode: `Text`.
- Last-used mode persistence is not required unless easy and non-invasive.

First-load state:

- Prompt is centered vertically and horizontally over the wallpaper.
- Size and layout should match Bing closely: large, restrained, clean, and search-first.
- The prompt should be large, cinematic, and bold. Desktop prompt font size should be approximately 22-24px.

After first Text response:

- Prompt transitions upward to a top search/results position.
- Conversation appears below, like a Bing Chat/search results flow.

After first Image generation:

- Prompt also transitions upward.
- Image results appear below.

The prompt should not stay centered after results appear.

## Create Prompt Controls

Prompt bar must include:

Shared:

- Mode toggle: segmented pill control.
- Gear/sliders settings button opening a mode-specific popover.
- Submit button.

Text mode visible controls on desktop:

- Mode toggle.
- Model selector.
- Creativity/depth preset selector with labels: `Short`, `Standard`, `Deep`.
- Submit button with visible text `Ask`.

Text mode visible controls on mobile:

- Mode toggle.
- Creativity/depth preset if space allows.
- Submit button icon-only.
- Model selector hidden in the gear/sliders settings popover.

Text token limit:

- Must not be visible in the prompt bar.
- Put token limit in the settings popover only.

Image mode visible controls:

- Mode toggle.
- Model selector, always visible even if only one image model exists.
- Size control.
- Count stepper.
- Submit button with visible text `Generate` on desktop.

Image mode mobile:

- Submit button should be icon-only with accessible label.
- Other controls may wrap or compact, but must remain usable.

Prompt bar sizing:

- Text mode may use a slightly taller or wider prompt bar than Image mode.
- The interface must remain stable and polished while switching modes.

Submit button:

- Same shape for Text and Image.
- Different icon per mode.
- Text mode icon: chat bubble.
- Image mode icon: camera.
- Desktop: icon plus visible text (`Ask`, `Generate`).
- Mobile: icon-only with accessible label.

## Settings Popover

Use a single gear/sliders icon to open settings.

Popover behavior:

- Mode-specific popover depending on current mode.
- Show only current mode settings plus shared essentials.
- Do not show disabled irrelevant controls.

Text settings should include at minimum:

- Model selector, especially on mobile.
- Token limit.
- Any existing chat/model options that are not shown in prompt bar.
- Save/load chat controls if they are not elsewhere available.

Image settings should include at minimum:

- Style selection.
- Any prompt-builder controls moved out of the main view.
- Advanced generation options.

## Text Presets

Visible preset labels:

- `Short`
- `Standard`
- `Deep`

Behavior:

- These are UI labels for instruction style, not direct model/effort switching.
- They should map to prompt/system instruction behavior:
  - Short: concise answer instruction.
  - Standard: normal answer instruction.
  - Deep: detailed reasoning/explanation instruction.
- Do not automatically switch model based on these presets.
- Do not expose token limit through these presets in the prompt bar.

Implementation detail:

- Keep mappings configurable or easy to tune later.
- Avoid destructive changes to existing chat endpoint behavior.
- Add the preset instruction in a clear way when constructing the message request.

## Image Controls

Count:

- Use a stepper with minus/plus buttons.
- Keep it compact.
- Respect existing valid count constraints.

Size:

- Use icon buttons for all current exact sizes:
  - `512x512`
  - `768x768`
  - `1024x1024`
  - `1024x768`
  - `768x1024`
- Show small text under each icon.
- Tooltips are allowed but not the only way to see size.
- Selected state must be clear.

Model selector:

- Always show in Image mode.
- If only one image model exists, still show it for consistency.

Style:

- Style does not need to be visible in the main prompt bar.
- Put style in Image settings popover unless design has ample room without clutter.

Prompt builder:

- Preserve existing prompt-builder capabilities.
- It may move into an expandable or settings panel.
- Do not remove prompt builder behavior.

Iteration:

- Preserve image iteration behavior.
- Iteration controls should appear only after selecting an image or through a contextual selected-image area.

## Results Layout

Text results:

- Appear below the prompt after it moves upward.
- Use translucent conversation/result cards.
- Assistant responses should support markdown formatting if the existing app already does or can safely add it.
- Code blocks should use a Microsoft-like monospace stack.
- Copy buttons for messages/code are desirable if low-risk, but not required unless already present.

Image results:

- Appear below the prompt after generation.
- Use a visually rich image results grid inspired by image search results.
- Preserve current actions: iterate, save/download, delete.
- Metadata can be subtle but must remain available.
- Generated images should be easy to inspect.
- Use fixed dimensions/aspect handling to avoid layout jumps.

History:

- Existing image history and text chat history must remain available.
- History should not dominate the first viewport.
- It can be placed in a compact dropdown, side panel, or lower section.

## Suggestions

On empty Create state, show mode-specific suggestion chips under the prompt.

Text mode suggestions:

- Rotating set.
- `News in last 6 Hours` must always be present.
- `Weather Report` must always be present.
- Mix in creative prompts.

When greeting is typing:

- Show suggestions immediately but dimmed until the greeting finishes.

Image mode suggestions:

- Include creative image prompt suggestions.
- Keep them cinematic and concise.
- Examples can include landscape, product render, cinematic portrait, concept art, architecture, or editorial-style prompts.

## News Suggestion Behavior

Chip: `News in last 6 Hours`

Expected behavior:

- Sends a text prompt asking the selected model to summarize recent news.
- Because current information is required, run live lookup first, then ask the model to summarize.
- The response should cover all three scopes:
  - General top headlines.
  - Technology and AI news.
  - Local news based on weather/location.
- Organize the response into three sections:
  - General
  - Technology/AI
  - Local
- Include 5 items per section.
- Always include source links.
- Include relative timestamps such as `2 hours ago` when available.

Implementation requirement:

- If live lookup is not available in the local app implementation, degrade gracefully:
  - Tell the user live news lookup is unavailable.
  - Do not fabricate current news.
  - Offer to run a normal model prompt instead.

Do not let the model answer current-news questions from stale knowledge without live lookup.

## Weather Suggestion Behavior

Chip: `Weather Report`

Expected behavior:

- Ask for location each time the chip is clicked.
- Remember the answer by updating the weather widget/default location too.
- Use the same weather system as the weather widget after location is provided.

Weather report content:

- Current conditions.
- Three-day mini forecast.
- Each day: icon, high/low, short condition.
- Units: Fahrenheit by default.

## Greeting Requirements

A custom greeting appears on the empty Create screen.

Placement:

- Above the prompt, as a Bing-like welcome line.

Content:

- Begins with the selected model name introducing itself.
- Includes build date if known.
- Includes live weather context in the greeting.
- Example direction: `I'm {model}, built {date}. It's {weather} in {location}.`

But final greeting text should be model-generated.

Generation behavior:

- The selected model should generate its own greeting text each time, constrained enough to mention at least the model name.
- The greeting may be mostly free-form but must mention the selected model name.
- Include build date only if known.
- If build date is unknown, omit it. Do not say unknown.
- Include weather context if available.
- If weather is unavailable, omit weather rather than showing an error in the greeting.

Cost behavior:

- Greeting calls count against normal usage/cost tracking.

Caching:

- Cache generated greeting for the same model/weather for 15 minutes.
- Even when using cached greeting text, replay the typewriter animation every time Create opens.

Typewriter animation:

- Type out one character at a time.
- Replay every time Create opens.
- Speed: adaptive based on greeting length.
- Blinking cursor: always visible after greeting, and visible while typing.
- Click/tap greeting to fast-forward and reveal the full text.
- Reserve fixed greeting height so the prompt does not shift while text types.

Accessibility:

- Respect reduced-motion where feasible, but the selected product direction wants expressive motion.
- If reduced-motion is enabled, strongly reduce or skip non-essential motion while preserving content.

## Model Names and Build Dates

Display names:

- Use friendly model display names.
- Raw model ID should be available in tooltip/settings where appropriate, but not in the Create edit dialog.

Editing:

- Friendly display names should be editable directly from the Create page model selector.
- Use a small edit dialog.
- The edit dialog includes friendly name and build date.
- The edit dialog should not show raw model ID.
- Persist edits globally for the console on this machine.

Build date source:

- Display build date only if the API provides it.
- User edits may define build dates globally for models.
- If still unknown, omit build date in greeting.

Persistence:

- Store friendly names and user-entered build dates in a local config/data file under the existing app config/cache pattern.
- Do not require a browser-only localStorage implementation for global persistence.

## Weather Widget

Place weather in the same area where Bing would include it:

- Top-right corner.
- Compact Bing-like weather widget.

Weather source:

- Browser geolocation first.
- Then weather API if location is allowed.

If geolocation is denied:

- Show a small `Set location` control in the widget.
- That control opens the full settings panel.

Weather display:

- Current conditions plus 3-day mini forecast.
- Each day: icon, high/low, short condition.
- Units: Fahrenheit by default.
- Update automatically every hour.
- Cache weather data locally for one hour.

Greeting/weather relation:

- Greeting may mention weather briefly.
- Weather widget remains separate and visible.

Implementation requirement:

- If no weather API key/source is configured, widget should degrade gracefully:
  - Show `Set location` or `Weather unavailable` compactly.
  - Do not block Create page.
  - Do not crash.

## Wallpaper Requirements

The user said no more wallpaper questions, so use these finalized decisions.

Source:

- Use Bing daily public image endpoint with local fallback.
- Cache daily and use cached image as fallback.
- Keep cached wallpapers according to configurable retention.
- Retention setting should exist in both config file and UI setting, with config as default source of truth.
- Do not allow users to manually choose from cached wallpapers on the Create page.

Attribution:

- Show wallpaper attribution/location in a caption bar.
- Caption bar should be prominent, like a photo credit/caption bar.
- Include both refresh and info controls in the caption bar.

Refresh behavior:

- Manual refresh should fetch a random historical Bing wallpaper if available.
- Historical wallpapers should be fetched from Bing archive when available, then cached locally.
- Daily wallpaper refresh should happen automatically while the app is open.
- Check periodically and update when the daily wallpaper changes.
- Automatic and manual refresh should fade between wallpapers.

Fallback behavior:

- If endpoint is unavailable and no cached wallpaper exists, use a solid dark background.
- Keep the same Bing-style centered layout when fallback is active.

Licensing/safety:

- Prefer remote-loaded or cached metadata-backed wallpaper.
- Do not bundle copyrighted Bing wallpaper images directly.
- Cache responsibly and include attribution/location text when available.
- Make endpoint and cache retention configurable.

## Motion Requirements

The Create interface should have expressive cinematic motion.

Required motion:

- Typewriter greeting.
- Wallpaper fade transitions.
- Subtle but expressive entrance animation for prompt, chips, and result cards.
- More expressive motion may include parallax/background movement.

Direction:

- Use cinematic, beautiful, bold motion.
- Avoid janky animation or layout shifts.
- Respect reduced-motion by reducing or disabling background parallax and non-essential transitions.

## Typography

Overall font direction:

- Microsoft-like system font stack.
- Use `Segoe UI, Arial, sans-serif` for general UI text.

Monospace/code direction:

- Switch to a Cascadia Code/Consolas-style stack.
- Example stack: `Cascadia Code, Consolas, Menlo, Monaco, monospace`.

Prompt font size:

- Desktop main prompt input should be large and dramatic: approximately 22-24px.
- Mobile should scale down enough to avoid overflow.
- Do not use viewport-width-based font sizing.

Tone:

- Cinematic, beautiful, bold, world class.
- Avoid cramped admin aesthetics in Create.

## Background and Surface Styling

Create background:

- Full-bleed scenic wallpaper or fallback dark background.
- Use overlays to keep text readable.
- Prompt and cards may use translucent material treatment.
- Use blur/transparency carefully to preserve readability.

Controls:

- Minimize controls visually.
- Keep immediately required controls visible based on mode decisions above.
- Use icon buttons where appropriate.
- Include accessible labels/tooltips for icon-only controls.

Contrast:

- All text and interactive controls must remain readable over bright or dark wallpaper.
- Use scrims, shadows, or translucent panels as needed.

## Responsiveness

Desktop:

- Match Bing-like centered search layout closely.
- Large prompt and cinematic empty state.
- Text model selector visible in Text mode.
- Image controls visible as specified.

Mobile:

- Keep wallpaper visible.
- Prompt remains central on empty state.
- Submit buttons are icon-only.
- Text model selector moves into settings popover.
- Panels may become full-screen sheets or stacked layouts.
- No text should overflow controls.
- No controls should overlap incoherently.

Testing viewports:

- Desktop: at least 1440x900 and 1280x720.
- Mobile: at least 390x844 and 360x800.

## Data and API Additions

Implement only what is necessary, but expected support includes:

1. Wallpaper API/cache endpoints or local helpers:
   - Get current wallpaper metadata and URL.
   - Refresh to random historical wallpaper.
   - Cache daily wallpaper.
   - Read/write wallpaper retention setting.

2. Weather endpoints/helpers:
   - Get weather by browser-provided coordinates.
   - Get weather by configured/manual location.
   - Cache for one hour.
   - Return current plus 3-day forecast.

3. Model metadata endpoints/helpers:
   - Get friendly display names.
   - Save friendly display name/build date edits globally.
   - Use API-provided build date when available; otherwise user metadata.

4. Greeting endpoint/helper:
   - Generate greeting with selected model.
   - Cache same model/weather greeting for 15 minutes.
   - Track usage/cost like normal model call.

5. News helper:
   - Support live lookup for `News in last 6 Hours` if available.
   - Must not hallucinate current news without live lookup.

Use existing project patterns for file locations. Prefer existing cache/config directories such as `$HOME/.cache/matts-value-set/` where consistent.

## Suggested Local Data Files

Use exact names only if consistent with repo style; otherwise adapt cleanly.

- `$HOME/.cache/matts-value-set/create-ui.json`
  - friendly model names
  - user-entered build dates
  - weather default location
  - wallpaper retention setting

- `$HOME/.cache/matts-value-set/wallpapers/`
  - cached wallpaper files and metadata

- `$HOME/.cache/matts-value-set/weather-cache.json`
  - weather cache with timestamp, location, units, forecast

- `$HOME/.cache/matts-value-set/greeting-cache.json`
  - greeting cache keyed by model and weather summary, expires after 15 minutes

Do not store secrets in these files.

## Implementation Strategy

Phase 1: Inspect current UI

- Read `image-studio.py` fully enough to understand HTML/CSS/JS structure.
- Identify current tab names and DOM IDs for Image, Text/Chat, Claude/Coding, Ops, Reporting, AgentBoard.
- Identify current JS functions for image generation, chat, history, model loading, status loading.
- Preserve working endpoint contracts.

Phase 2: Navigation grouping

- Convert top-level nav to `Coding`, `Create`, `Console`.
- Map existing coding tab to Coding unchanged.
- Build Create as the combined Image/Text view.
- Move non-coding utility views into Console with secondary tabs or grouped panels.
- Keep all existing functions reachable.

Phase 3: Create shell

- Add full-bleed wallpaper/dark fallback background.
- Add top-right weather widget.
- Add prominent wallpaper caption bar with attribution/location plus refresh/info controls.
- Add greeting area above prompt with reserved height.
- Add centered prompt group with mode toggle, visible controls, settings button, submit button.
- Add suggestion chips.

Phase 4: Mode logic

- Implement Text/Image mode switching.
- Default to Text.
- Update visible controls per mode.
- Keep prompt contents unless switching should intentionally clear; default should preserve typed text.
- Update submit action based on mode.

Phase 5: Text flow

- On Text submit, move prompt to top result state.
- Apply selected `Short`/`Standard`/`Deep` instruction behavior.
- Send request through existing chat completion flow.
- Render results in polished translucent conversation cards.
- Preserve save/load/delete chat history.

Phase 6: Image flow

- On Image submit, move prompt to top result state.
- Use selected image model, size, count, style/settings.
- Send request through existing image generation flow.
- Render results in polished image grid.
- Preserve iterate/save/delete/history behavior.

Phase 7: Settings and metadata

- Implement mode-specific settings popover.
- Implement model friendly name/build date edit dialog from model selector.
- Persist globally on machine.
- Do not show raw model ID in edit dialog.

Phase 8: Weather/greeting/wallpaper integrations

- Implement graceful weather system.
- Implement model-generated greeting cache and typewriter animation.
- Implement wallpaper loading/cache/fallback/attribution/refresh.

Phase 9: News and weather chips

- Implement `Weather Report` location prompt and update weather widget/default location.
- Implement `News in last 6 Hours` with live lookup requirement and graceful fallback.

Phase 10: Verification

- Run Python syntax checks.
- Run available tests, if any.
- Start local console server if feasible.
- Verify desktop and mobile screenshots or manual DOM checks.
- Confirm no existing major workflow is broken.

## Detailed Acceptance Criteria

Navigation:

- [ ] Top-level nav shows `Coding`, `Create`, `Console`.
- [ ] Coding tab preserves existing terminal/coding behavior.
- [ ] Create contains combined Text/Image interface.
- [ ] Console contains existing operational views.

Create empty state:

- [ ] Full-screen wallpaper or solid dark fallback is visible.
- [ ] Prompt is centered like Bing homepage/search.
- [ ] Greeting appears above prompt.
- [ ] Greeting types character-by-character every time Create opens.
- [ ] Greeting can be clicked/tapped to reveal full text.
- [ ] Suggestion chips appear dimmed while greeting types.
- [ ] Weather widget appears top-right.
- [ ] Wallpaper caption bar appears prominently with attribution/location plus refresh/info controls.

Create prompt:

- [ ] Default mode is Text.
- [ ] Mode toggle is segmented pill style.
- [ ] Text desktop controls show mode, model, Short/Standard/Deep, Ask button.
- [ ] Image controls show mode, model, size icons, count stepper, Generate button.
- [ ] Gear/sliders settings opens mode-specific settings.
- [ ] Submit button shape is shared; icon differs by mode.
- [ ] Desktop submit buttons show text.
- [ ] Mobile submit buttons are icon-only and accessible.

Text behavior:

- [ ] Text submit moves prompt upward.
- [ ] Text result cards render below prompt.
- [ ] Short/Standard/Deep affect instruction style as specified.
- [ ] Token limit is only in settings, not prompt bar.
- [ ] Chat save/load/history still works.

Image behavior:

- [ ] Image submit moves prompt upward.
- [ ] Image grid renders below prompt.
- [ ] All current sizes are available as icon buttons with small text labels.
- [ ] Count stepper works.
- [ ] Model selector is always visible.
- [ ] Style/settings remain available.
- [ ] Iterate/save/delete/history still work.

Weather:

- [ ] Browser geolocation is attempted first.
- [ ] If denied, widget shows Set location and opens settings panel.
- [ ] Weather shows current plus 3-day forecast.
- [ ] Forecast day display includes icon, high/low, short condition.
- [ ] Units default Fahrenheit.
- [ ] Weather updates hourly and caches for one hour.

Greeting:

- [ ] Selected model generates greeting when cache expired.
- [ ] Greeting mentions model name.
- [ ] Greeting includes build date only if known.
- [ ] Greeting includes weather only if available.
- [ ] Greeting usage counts like normal model usage.
- [ ] Same model/weather greeting caches for 15 minutes.
- [ ] Cached greeting still typewrites every Create open.

Model metadata:

- [ ] Friendly display names are used.
- [ ] Friendly name/build date edit dialog is reachable from Create model selector.
- [ ] Edit dialog does not show raw model ID.
- [ ] Edits persist globally on this machine.

Wallpaper:

- [ ] Daily Bing public wallpaper source is used when available.
- [ ] Cached wallpaper fallback works.
- [ ] Configurable retention exists in config and UI settings.
- [ ] Manual refresh fetches random historical wallpaper if available.
- [ ] Automatic daily refresh works while app is open.
- [ ] Wallpaper transitions fade.
- [ ] Solid dark fallback works when no wallpaper exists.

Suggestions:

- [ ] Text suggestions always include News in last 6 Hours and Weather Report.
- [ ] Text suggestions rotate/mix creative prompts.
- [ ] News chip does not fabricate current news without live lookup.
- [ ] Weather Report asks for location and updates widget/default location.

Responsive/polish:

- [ ] Desktop layout is cinematic, bold, and world class.
- [ ] Mobile layout has no overlapping controls.
- [ ] Text does not overflow buttons/cards/panels.
- [ ] Reduced-motion users are respected where practical.
- [ ] Existing endpoints and workflows remain backward compatible.

## Constraints From Existing Codebase

- Prefer existing helper functions and local patterns.
- Keep edits scoped.
- Avoid unrelated refactors.
- Do not break current API routes used by existing JavaScript unless all callers are updated.
- Do not remove existing history, budget, reporting, status, AgentBoard, terminal, image, or chat features.
- Keep security in mind for remote URLs, browser geolocation, stored settings, and user-provided locations.
- Handle network failures gracefully.

## Verification Commands

Run at minimum:

```bash
python3 -m py_compile image-studio.py do-anthropic-proxy.py
```

If tests exist after/while implementing:

```bash
python3 -m pytest
```

If starting local console is feasible:

```bash
python3 image-studio.py --no-open
```

Then verify the printed local URL manually or with browser automation if available.

## Final Deliverable Expectations For GLM-5

When finished, report:

- Files changed.
- Which acceptance criteria are complete.
- Which criteria are intentionally deferred and why.
- Verification commands run and results.
- Local URL if a dev server/console was started.
- Any network/API keys or environment variables needed for weather/news/wallpaper features.

Do not mark INT-014 complete unless Image and Text are actually combined into Create and the core Bing Update experience is implemented.
