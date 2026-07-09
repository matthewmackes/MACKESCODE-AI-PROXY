# API Versioning

The Console JSON API supports explicit v1 paths under `/api/v1/*`.

Examples:

```bash
curl http://127.0.0.1:18181/api/v1/models
curl -X POST http://127.0.0.1:18181/api/v1/chat -d '{"messages":[]}'
```

Legacy `/api/*` paths remain compatible and currently dispatch to v1. Legacy responses include:

- `x-matts-api-version: v1`
- `x-matts-api-supported-versions: v1`
- `deprecation: true`
- `warning: 299 - "Unversioned API path is deprecated; use /api/v1/..."`

New clients should use `/api/v1/*` directly. Existing clients can migrate by inserting `/v1` after `/api` without changing request or response bodies.

Version negotiation is also accepted with:

```text
x-matts-api-version: v1
accept: application/vnd.matts-value-set.v1+json
```

Unsupported versions return a structured `400` response with `code: unsupported_api_version` and `details.supported_versions`.
