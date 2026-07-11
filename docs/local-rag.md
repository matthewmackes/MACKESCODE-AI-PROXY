# Local RAG Document Workspace

The console includes a local retrieval workspace for grounding chat, eval, comparison, and Claude Code launch prompts against operator-selected project files. It is opt-in per request and stores only a local lexical index.

## Collections

Collections are stored in the configured `rag_config_file` path, defaulting to `.cache/local-rag.json`. A collection declares explicit include and exclude globs relative to the project root:

```json
{
  "schema_version": 1,
  "collections": [
    {
      "id": "project-docs",
      "name": "Project Docs",
      "include": ["README.md", "GOVERNANCE.md", "MAIN-WORKLIST.md", "docs/**/*.md"],
      "exclude": [],
      "max_file_bytes": 250000
    }
  ]
}
```

The default collection indexes project documentation and worklist context. Operators can define additional collections through `POST /api/rag/config`, then index one collection with `POST /api/rag/index`.

Supported file types are Markdown, text, JSON, Python, JavaScript, TypeScript, HTML, CSS, shell, YAML, and YML. Large files over `max_file_bytes` are skipped.

## Boundaries

Indexing is local by default. The service does not crawl outside the project root and always applies runtime-state and secret-oriented excludes before collection-specific rules. Built-in excludes include `.git`, `.cache`, build/dist folders, `frontend/node_modules`, `frontend/dist`, Python bytecode/cache directories, `.env`, and paths containing token, secret, or key.

The index is stored in the configured `rag_index_file` path, defaulting to `.cache/local-rag-index.json`. Do not commit local RAG config or index files unless the collection intentionally contains only non-sensitive project documentation.

## Request Use

Retrieval is enabled by adding a `retrieval` object:

```json
{
  "retrieval": {
    "enabled": true,
    "collection_id": "project-docs",
    "query": "gateway routing policy",
    "limit": 5
  }
}
```

For chat, eval, and comparison requests, matching snippets are inserted as a system message that asks the model to cite sources as `[path#chunk]`. For Claude Code launch prompts, the cited context is prepended to the generated prompt.

If `query` is omitted, chat/eval retrieval uses the prompt or most recent user message. The UI exposes a Local retrieval toggle, collection field, optional query field, index action, and search preview in Chat advanced settings.

## Citations

Responses include retrieval metadata when grounding is enabled:

```json
{
  "retrieval": {
    "enabled": true,
    "query": "gateway routing policy",
    "matches": [
      {
        "collection_id": "project-docs",
        "path": "docs/gateway-routing.md",
        "chunk": 2,
        "score": 25,
        "text": "..."
      }
    ]
  }
}
```

The Chat response detail panel exposes this payload alongside routing, trace, cost, token, and streaming diagnostics.

## Limits

Retrieval is lexical rather than vector based. It is deterministic, dependency-free, and private, but it will miss semantic matches that do not share query terms. Use focused collection includes and explicit queries for best results.
