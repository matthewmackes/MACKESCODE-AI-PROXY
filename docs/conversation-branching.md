# Conversation Branching

Conversation branching lets an operator fork a saved chat at a reviewed message, continue the fork with a different model or prompt posture, and compare the branch against its parent without rewriting the parent chat.

## Storage

Saved chats remain JSON documents under the console app cache `chats/` directory. A branch is a normal saved chat with an additional `branch` object:

```json
{
  "branch": {
    "parent_chat_id": "chat_123",
    "source_message_index": 3,
    "source_trace_id": "trace-a",
    "source_model": "model-a",
    "source_route": {"used": "model-a", "backend": "serverless"},
    "source_cost": {"total_cost_usd": 0.01},
    "source_latency_ms": 123,
    "selected_model": "model-b",
    "notes": "try concise"
  }
}
```

Autosave sends the `branch` object back with branch conversations so later replies do not detach the fork from its parent. Deleting a branch removes only that branch chat file; the parent remains unchanged.

## Console Behavior

Use `Fork` on any non-pending chat message. If the current chat has not been saved yet, the console autosaves it first, then creates a branch containing messages through the selected source message. The new branch becomes the active chat and can be continued with the selected model.

The `Branches` view loads `/api/chat/branches?id=<parent_chat_id>` and shows sibling branches with:

- selected and routed model metadata
- route, cost, latency, trace, and streaming metrics from the latest branch reply
- operator notes
- a compact response delta against the parent's latest response
- actions to load the branch or save a reviewed one-example eval dataset

## Replay Limits

Branches preserve messages and metadata, not a full deterministic provider replay. Provider model revisions, gateway policy changes, context-window changes, rate limits, and Dedicated or Serverless availability can change future branch replies. Treat branch comparison as operational evidence for the saved run, not a guarantee that the same route or answer will reproduce later.

Before saving a branch as an eval example, review the prompt and response for secrets or runtime-only data. The console saves each branch eval as its own dataset so it does not overwrite an existing shared dataset.
