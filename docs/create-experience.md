# Create Experience

The Create tab is the image-creation workspace. It uses a scenic wallpaper background, a centered prompt, and compact controls so the wallpaper stays visible.

## First View

- The greeting reserves fixed space above the prompt, replays a typewriter animation when Create opens, and can be clicked to finish immediately.
- Greeting text names the selected image model and adds local weather context only when weather data is available.
- Suggestion chips dim while the greeting types, then return to normal.
- The weather mood pill starts from local time and upgrades with browser geolocation plus Open-Meteo when permission and network access are available.
- If geolocation or weather lookup fails, the pill shows a graceful unavailable state and the greeting omits weather.

## Wallpaper

- Create loads wallpaper metadata through `/api/wallpaper` and uses same-origin cached image URLs.
- The caption bar shows the current wallpaper caption or title.
- `Refresh` requests another wallpaper and crossfades the background.
- `Info` displays available title, caption, copyright/source, or fallback error detail.
- If wallpaper loading fails, the page keeps a dark scenic fallback instead of blocking the workflow.

## Images

- Create sends the centered prompt into the image studio controls.
- Image model, size, generation history, iteration, save, delete, and style comparison remain available in the panels below the first-view prompt.

## Model Styling

- Model selector cards use registry metadata for provider, origin, cost, use case, access state, and generated visual styling.
- Newly discovered catalog models receive a global `new` sparkle for seven days based on their registry `created` timestamp.
- Reduced-motion settings disable decorative animations while preserving the controls and status information.
