# Agent Execution Graphs

AgentBoard includes a Graph tab for each tmux-backed Claude session. The graph
is a normalized timeline of execution events derived from existing local
evidence.

## Event Sources

Directly observed events come from:

- trace records, including route, requested/routed model, backend, latency,
  cost, status, and trace ID
- audit records for sensitive operator actions such as tmux sends, lifecycle
  changes, model registry updates, and permission-gated actions
- tmux pane metadata such as process command, pane target, path, PID, and
  active state

Inferred events come from tmux captures:

- latest prompt/task summaries
- terminal snapshots represented by a short summary and digest
- approval prompts detected from permission-style screen text

Each graph node includes `confidence` as either `direct` or `inferred` so the UI
does not imply more certainty than the evidence supports.

## Privacy Boundary

Graph nodes do not store full prompts, full terminal output, or model responses.
They use existing trace summaries, audit metadata, short tmux summaries, and
digests. Full terminal context remains available only in the live AgentBoard
session detail pane, which is a current tmux capture rather than graph storage.

## Payload Shape

`GET /api/agentboard` includes:

- `graphs[]`: one graph per active session
- `graphs[].nodes[]`: ordered events with type, timestamp, source, confidence,
  status, model/backend metadata, cost, latency, and evidence handles
- `graphs[].edges[]`: sequential `next` edges between ordered nodes
- `graphs[].summary`: event count, direct/inferred counts, total cost, and error
  count

The UI renders the selected session graph and links evidence through trace IDs,
audit action names, tmux pane targets, and session identifiers where available.
