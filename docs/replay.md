# Trace And Chat Replay

Replay reruns a previous request against the original model, current default model, a selected model, or a comparison set. It is designed around the repository's redaction rules.

## Sources

Supported sources:

- Saved chats: full user/system messages are available because the operator saved the chat locally.
- Traces: only `message_summary.last_user_preview` is available unless another linked record retained the full prompt.

Trace replay is therefore approximate. If the trace prompt was truncated or omitted, replay returns a limitation or rejects the replay when no prompt data remains.

## Targets

Replay requests support:

- `original`: use the source model.
- `default`: use the current default text model.
- `selected`: use one selected model.
- `comparison`: run up to five selected models.

Replay results include output text, routing, latency, usage, cost, error state, and a bounded unified diff against an optional baseline response.

## Persistence

Replay records are written to `replays.jsonl` in the console runtime directory and a linked `replay.run` trace is appended with source metadata and total replay cost. The replay record stores replay metadata and model responses, not provider credentials or raw trace bodies.

## API

- `POST /api/replay/snapshot`: preview replay availability and redaction limitations.
- `POST /api/replay`: run replay.
- `GET /api/replays?limit=50`: list recent replay records.
