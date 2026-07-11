# Streaming Metrics

Streaming metrics report response progress without storing additional response text beyond normal chat persistence.

## Metrics

The proxy attaches `streaming_metrics` to `claude_do`, traces, and proxy usage log records:

- `elapsed_ms`
- `first_token_latency_ms`
- `generation_ms`
- `chunk_count`
- `output_tokens`
- `tokens_per_second`
- `estimated_cost_usd`
- `stream_requested`
- `client_streaming`
- `provider_streaming`
- `route_health`

`route_health` is one of:

- `streaming`: provider and client streaming were both available
- `client_streamed_from_buffer`: the client requested streaming, but the proxy streamed a completed upstream response
- `non_streaming`: no streaming route was used

## UI Behavior

Create chat cards show elapsed time while a request is pending. Final answer metadata and message detail diagnostics show route health, tokens/sec, first-token latency, output tokens, and cost estimate when the route reports metrics. Non-streaming routes are labeled explicitly.

## Limits

Some providers and compatibility paths return complete responses even when the Anthropic-compatible client requested streaming. In that case, the proxy still emits a stream-shaped response to the client, but marks `provider_streaming: false` and `route_health: client_streamed_from_buffer`.
