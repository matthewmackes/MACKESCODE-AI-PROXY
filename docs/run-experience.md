# V2 Run Experience

The V2 Run workspace stores operator-authored prompt templates, run profiles,
run records, conversation branches, and session snapshots in a local SQLite
runtime database. The default path is:

```text
~/.cache/matts-value-set/studio/operational.sqlite3
```

The Run tables now share the operational store (`MATTS_OPERATIONAL_DB`) with
trace backfills, model registry rows, research dossiers, DigitalOcean snapshots,
and analyst runs. Set `MATTS_V2_RUN_DB` only when intentionally splitting the
Run workspace onto a legacy or diagnostic database.
This state is operator data, not release configuration, and should be handled by
runtime backup/restore processes rather than committed to the repository.

## Prompt Templates

Prompt templates contain a reusable body, declared variables, example payloads,
owner notes, tags, and a monotonic version. Template preview renders
`{{variable}}` placeholders with operator-provided JSON values and reports
missing variables before use.

Template examples are stored as small JSON objects with a title, values,
rendered prompt, and note. They are meant to document safe reuse patterns, not
to store production transcripts. Owner notes are local operator guidance for
when a template should or should not be used.

Each template save creates an immutable snapshot in
`prompt_template_versions`. Rollback creates a new current version from an
older snapshot and does not rewrite history.

Templates should remain secret-free. Runtime secrets belong in environment
variables, token files, or provider-specific credential stores.

## Run Profiles

Run profiles capture reproducibility settings for a class of work:

- selected model
- linked prompt template
- default prompt
- system instructions
- mode, sampling parameters, and token limits
- tool allow/deny lists
- budget caps
- gateway policy JSON
- tags and description

Each save creates a new current profile version. The profile version snapshot is
archived in `run_profile_versions` with `INSERT OR IGNORE`, so an existing
snapshot is not rewritten by later activation, rollback, or edit operations.

Rollback creates a new current version from an older immutable snapshot. It does
not modify the old version.

## Run Records

Run records link execution evidence to the exact profile/template versions used
for a run. A record stores:

- trace ID
- session ID
- run profile ID and resolved profile version
- prompt template ID and resolved template version
- input and result summaries
- metadata, status, and tags

When a run record is saved with `profile_id` or `prompt_template_id` but without
an explicit version, the store resolves the current version at save time. This
keeps later profile/template edits from changing the historical record.

## Runtime-State Boundary

The operational database is local runtime state. It can contain prompts,
operator notes, trace IDs, session IDs, and workflow metadata, so it must be
treated as sensitive. It is intentionally separate from release config such as
the git-tracked `config/models.json` export snapshot, source files, and
generated frontend client artifacts.

Do not store provider API keys, access tokens, or long-lived secrets in prompt
templates, run profiles, run records, branches, or snapshots.
