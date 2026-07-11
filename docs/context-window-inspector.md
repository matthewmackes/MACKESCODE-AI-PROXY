# Context Window Inspector

The context window inspector estimates prompt footprint before text-heavy actions run. It is exposed through `POST /api/context-window` and is shown in the Chat/Create, Claude Code launch, and Eval Runner surfaces.

## What It Estimates

- input tokens from chat messages, visible prompts, eval examples, and Claude Code launch context
- requested max output tokens
- remaining context tokens for each selected model
- per-message token contribution and text preview
- warning codes for likely context or output problems

Model metadata comes from the global model registry. The inspector uses `context_window`, `context_length`, and `max_output_tokens` when present.

## Warning Codes

- `unknown_model`: selected model is not in the registry map
- `missing_context_window`: the registry does not include context metadata
- `context_exceeded`: estimated input alone is larger than the model context window
- `output_exceeds_remaining_context`: requested output will not fit after estimated input
- `truncation_risk`: estimated input uses at least 90% of context
- `max_output_exceeds_model_limit`: requested output is above registry max output metadata

## Accuracy Limits

Counts are approximate. The local estimator uses text heuristics rather than provider-specific tokenizers. Actual provider counts can differ because of hidden system prompts, tool schemas, file context, retrieval context, model-specific tokenization, and upstream request rewriting.

Treat warnings as preflight guidance, not billing-grade or provider-authoritative limits.
