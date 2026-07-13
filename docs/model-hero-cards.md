# Model Hero Cards

Model hero cards give operators a richer view of each LLM without creating a second model source of truth.

## Source Of Truth

- `config/models.json` remains the active model registry for IDs, enablement policy, pricing, context, origin, provider identity, and generated style.
- `$HOME/.cache/matts-value-set/studio/model-access-state.json` stores key-specific access state that is merged into model cards at read time.
- `config/model-descriptions/families.json` stores curated family-level descriptions: summary, best-fit use cases, strengths, weaknesses, and comparison families.
- `src/console/services/model_hero.py` combines those two sources into per-model cards for every current registry entry.

## API

- `GET /api/model-info` returns all hero cards and a `model_info` map keyed by model ID.
- `GET /api/model-info?model=<id>` returns one card.
- `GET /api/models/<id>/info` is also supported for REST-style callers.

## UI

Hero card data is the content of the V2 model-detail dialog. Every LLM surface renders the unified `ModelIdentityCard` (see `docs/unified-model-card.md`); clicking a card body — or the ⓘ info glyph on click-to-select surfaces such as Chat contacts and model dropdowns — opens one global detail dialog (`ModelDetailHost`). Chat assistant replies embed the same small card, so clicking it opens the same dialog.

Each dialog includes cost, origin, provider identity, access state, deployment mode, best-fit use cases, strengths, watch-outs, and similar models from the active registry, alongside the measured Health grade carried on the model payload.

## Updating Descriptions

Prefer updating `config/model-descriptions/families.json` for broad provider or family behavior. Add registry facts to `config/models.json` only when the fact belongs to a specific model, such as pricing, model type, context window, or Dedicated Inference lifecycle metadata. Keep key-specific access audit results in runtime state.
