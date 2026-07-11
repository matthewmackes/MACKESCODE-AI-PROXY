# Offline And Degraded Mode

The Console exposes an offline/degraded state so local workflows remain usable
when DigitalOcean or provider APIs are unavailable.

## Modes

- `online`: provider checks and Serverless catalog refresh are healthy.
- `degraded`: provider health or catalog refresh is failing, but cached data is
  available.
- `offline`: provider/catalog access is unavailable and no useful live catalog
  response is available.

The status is visible in Console > System Operations > Offline Mode and through
`GET /api/offline-mode`.

## Local Workflows That Remain Available

These workflows use local files or runtime cache and remain available:

- Browse the active model registry.
- Edit local eval datasets.
- Review prior eval runs.
- Browse saved reports, traces, notifications, reviews, snapshots, and runtime
  state.
- Edit saved profiles and templates.

Cached data includes source and age metadata so operators can decide how much to
trust it.

## Live Cloud Actions

These actions require provider access and are guarded when degraded or disabled
when offline:

- Refresh Serverless catalog.
- Audit model access keys.
- Build Dedicated Inference.
- Discover Dedicated sizes and GPU/model configurations.
- Fetch DigitalOcean billing reports.

The UI disables live-cloud buttons in offline mode and annotates them in degraded
mode.

## Cache Confidence

The Serverless catalog cache reports:

- `source`: live API, local cache, stale cache fallback, or empty fallback.
- `fetched_at`: source timestamp.
- `age_seconds`: cache age at payload generation time.
- `stale`: true when the cache is missing or older than 24 hours.
- `confidence`: `fresh`, `stale`, or `empty`.

The model registry, eval datasets, and eval runs report local counts and source
labels.

## Limits

Offline mode does not make provider-backed work run locally. It only keeps safe
local workflows available and prevents accidental live-cloud actions when the
provider state is not trustworthy.
