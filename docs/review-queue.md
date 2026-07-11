# Human Review Queue

The review queue gives operators one place to triage model and policy events that need human judgment. It stores metadata, short summaries, and redacted evidence in a local JSONL file under the console runtime directory.

## Triggers

Review items can be created manually through Console > Ops > Review Queue or automatically by services that detect risky events.

Current automatic sources:

- Blocked eval-on-change gates.
- Trace records with failed status, high local cost, or uncertain gateway decisions.

Supported source links include trace ids, eval gate hashes, session names, target ids, and target versions. Sensitive prompt, message, token, screen, raw, and output fields are redacted or truncated before persistence.

## Lifecycle

Each item has:

- `open`: needs operator review.
- `approved`: operator accepted the event or output.
- `rejected`: operator rejected the event or output.
- `closed`: no further action required.

Items also carry severity, reason, actor, assignee, notes, source evidence, and promotion history.

## Promotions

Operators can promote review items to:

- Eval dataset examples through `/api/reviews/promote` with `target: "eval"`.
- Worklist follow-ups through `/api/reviews/promote` with `target: "worklist"`.

Promoted eval examples include the review id in metadata so future regressions can be traced back to the human decision.

## Permissions

Review queue API routes require the `review_queue` permission. Owner and admin roles have all permissions; operator, model admin, and infra admin roles include `review_queue` by default.
