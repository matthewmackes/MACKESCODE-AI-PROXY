# Saved Comparison Reports

Saved comparison reports turn a model comparison run into a local artifact that can be reviewed, exported, and promoted into eval coverage.

## Lifecycle

1. Run a Create text comparison with one to five selected models.
2. Use `Save Report` to add a title, optional winner model, notes, and tags.
3. The report is written as JSON under the console runtime cache `comparison-reports/` directory.
4. Load a saved report from the comparison report selector to review outputs, routing, cost, latency, trace IDs, notes, scorecard links, and dataset-builder candidates.
5. Export the report as Markdown, CSV, or JSON, or save successful responses as reviewed eval examples.

Reports are runtime/operator state. They are not release-owned config and should not be committed unless intentionally creating a sanitized fixture.

## Stored Fields

Each report stores:

- prompt, selected models, title, notes, tags, winner model, and linked chat ID
- per-model output or error, requested/routed model, route/fallback reason, usage, cost, latency, trace ID, and streaming metrics
- `scorecard_links`, which let a model scorecard or operator review point back to the report ID
- `dataset_builder_examples`, which can be promoted through the existing eval dataset builder

Reports tolerate missing or failed results. Empty reports still export with headers so interrupted comparisons can be saved for audit context.

## Exports

`/api/comparison-reports/export?id=<report>&format=<json|csv|markdown>` returns content plus filename and content type. Markdown is optimized for human review, CSV for spreadsheet comparison, and JSON for local automation.

## Privacy

The report service applies basic redaction for common token shapes such as `sk-*`, `dop_v1_*`, bearer tokens, and `token=` values before storing and exporting report text. This is a guardrail, not a full data-loss-prevention system. Operators should still review prompts, outputs, notes, and tags before exporting or saving eval examples.
