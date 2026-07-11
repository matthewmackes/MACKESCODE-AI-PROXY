# Budget Forecasting

The console exposes pre-run cost forecasts for cost-bearing batch actions:

- Create image batches and style variants
- Create multi-model text comparisons
- AgentBoard eval runs
- Dedicated Inference builds and rebuilds

Forecasts are served by `POST /api/cost-forecast` and are shown in browser
confirmation prompts before the action runs. When the action response includes
actual cost, the response also includes `forecast_actual` with estimated,
actual, and delta values for later calibration.

## Inputs

Text forecasts use the model registry pricing fields:

- `pricing.input` dollars per million input tokens
- `pricing.output` dollars per million output tokens
- prompt text, chat messages, eval example inputs, and `max_tokens`

Image forecasts use:

- `pricing.image` dollars per generated image
- selected image model and requested image count

Dedicated Inference forecasts use:

- `price_per_hour` from the Dedicated configuration or build form
- `forecast_hours`, defaulting to one hour for pre-build confirmation

Budget impact uses the local budget file, current cost summary, recent
Dedicated runtime, and local proxy usage. DigitalOcean billing insights can lag,
so the console labels these values as estimates where provider data is not the
source of truth.

## Warnings

Forecast warnings distinguish:

- the action estimate
- current last-24-hour spend
- current month-to-date spend when available
- configured daily/monthly/total limits
- missing or zero model pricing

Daily and monthly warnings become errors when projected spend exceeds the
configured limit. Missing pricing is treated as a warning because it can
understate actual spend.

## Calibration

Forecasts are approximate. Text output cost assumes `max_tokens` could be fully
used, while actual provider responses may be shorter. Image and Dedicated
forecasts are closer because they use unit count and hourly price. Comparison,
eval, image, and Dedicated build responses attach `forecast_actual` whenever
the console can compare actual spend with the submitted forecast.
