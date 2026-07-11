# Architecture Refinement Design

Purpose: turn the architecture review findings into implementable designs. These
designs should reduce global coupling, clarify data contracts, and make future
policy, observability, and runtime-state work easier to extend safely.

## 1. Console Application Shell

### Problem

`image-studio.py` is still the composition root, compatibility layer, service
locator, runtime registry, and HTTP handler host. Services are often recreated
through global helper functions, making dependency flow harder to inspect and
state lifetimes less explicit.

### Target Design

Introduce a `ConsoleApp` application shell that owns startup configuration,
runtime paths, long-lived services, and HTTP handler dependencies.

Proposed modules:

- `src/console/app.py` - `ConsoleApp`, dependency construction, startup/shutdown.
- `src/console/context.py` - small immutable/configured context object for paths,
  environment, version, and process settings.
- `src/console/server.py` - HTTP server factory and handler binding.
- `image-studio.py` - thin CLI entry point that builds `ConsoleApp` and serves.

Core rule: handlers receive `self.server.app` or a narrow dispatcher object,
not module-level global functions.

### Migration Plan

1. Add `ConsoleApp` with methods that wrap the existing global functions.
2. Teach `StudioHandler` to prefer `self.server.app` while keeping global
   fallback during migration.
3. Move service construction into `ConsoleApp` one service group at a time.
4. Move startup/shutdown behavior, policy worker, and proxy start into the app.
5. Retire compatibility globals once tests cover the new shell.

### Done Criteria

- `image-studio.py` is a thin executable wrapper.
- Service lifetimes are explicit and mostly long-lived.
- Tests can instantiate `ConsoleApp` with fake dependencies.
- HTTP handlers no longer depend on module global state for normal operation.

## 2. Typed Domain Model Layer

### Problem

Core records are plain dictionaries: models, traces, Dedicated configs, audit
records, gateway decisions, sessions, and eval runs. This makes drift easy and
forces validation logic to be repeated across services.

### Target Design

Add a small domain model layer using standard-library dataclasses and explicit
`from_dict` / `to_dict` methods. Avoid heavy dependencies.

Proposed modules:

- `src/console/domain/models.py` - `ModelRecord`, `ModelPricing`,
  `DedicatedRouteState`.
- `src/console/domain/traces.py` - `TraceRecord`, `MessageSummary`,
  `RoutingProof`.
- `src/console/domain/auth.py` - `ActorIdentity`, `PermissionDecision`.
- `src/console/domain/dedicated.py` - `DedicatedConfig`, `LifecycleEvent`.
- `src/console/domain/gateway.py` - `GatewayDecision`, `PolicyMatch`.
- `src/console/domain/results.py` - shared `Result` / `ErrorInfo` helpers where
  useful.

Design rules:

- Preserve JSON compatibility at service boundaries.
- Validate required fields at construction.
- Normalize optional/missing values once in the domain layer.
- Keep redaction helpers close to sensitive domain types.

### Migration Plan

1. Start with `ActorIdentity` and `GatewayDecision`, since they support security
   and explainability.
2. Convert `TraceRecord` append/read paths.
3. Convert model registry normalization to emit `ModelRecord` internally.
4. Convert Dedicated config and lifecycle public payloads.
5. Keep API responses as dicts until frontend payloads are intentionally
   versioned.

### Done Criteria

- New high-risk code uses domain objects internally.
- Services validate domain records consistently.
- Existing JSON API responses remain compatible.
- Tests cover parse/serialize/validation for each domain type.

## 3. Unified Event Envelope

### Problem

The platform has separate traces, audit logs, Dedicated events, usage logs,
future notifications, review items, and analytics inputs. These are related
observability records but are written through separate paths with different
shapes.

### Target Design

Introduce a shared internal event envelope and project it into specialized
stores/views.

Envelope shape:

```json
{
  "event_id": "evt_...",
  "ts": 0,
  "kind": "trace|audit|lifecycle|usage|notification|review|policy",
  "severity": "debug|info|warning|error|critical",
  "actor": {"id": "", "roles": [], "source": ""},
  "subject": {"type": "model|session|trace|config|dedicated", "id": ""},
  "correlation": {"trace_id": "", "session_id": "", "request_id": ""},
  "payload": {},
  "redaction": {"profile": "default", "contains_sensitive": false}
}
```

Proposed modules:

- `src/console/events/envelope.py` - event dataclass and validation.
- `src/console/events/bus.py` - synchronous local event bus.
- `src/console/events/sinks.py` - JSONL trace/audit/lifecycle/notification sinks.
- `src/console/events/projectors.py` - adapters from event envelope to existing
  views.

Design rules:

- The event bus is local and synchronous first.
- Existing JSONL files can remain as sinks.
- Security-sensitive audit semantics remain strict.
- Prompt/output content is not added to default events.

### Migration Plan

1. Add event envelope without changing existing outputs.
2. Emit events in parallel from trace, audit, Dedicated lifecycle, and budget
   paths.
3. Add projectors that reproduce current trace/audit files from events.
4. Move analytics and notifications to read event-derived data.
5. Retire duplicate write paths only after parity tests.

### Done Criteria

- Related records can be correlated by event/trace/session IDs.
- Existing trace/audit/lifecycle behavior remains compatible.
- New notification/review features can subscribe to event envelopes.
- Tests verify event redaction and sink parity.

## 4. Policy Engine Boundary

### Problem

Authorization, gateway routing, budget checks, rate limits, quotas, model access,
Dedicated teardown, and future automation policies are spread across handlers and
services. This makes policy precedence and explanations harder to reason about.

### Target Design

Introduce a `PolicyService` that answers policy questions and returns structured
decisions with explanations.

Proposed modules:

- `src/console/policy/service.py` - main policy facade.
- `src/console/policy/rbac.py` - role and permission decisions.
- `src/console/policy/routing.py` - model/gateway route decisions.
- `src/console/policy/budget.py` - budget/quota decisions.
- `src/console/policy/dedicated.py` - idle/unhealthy/build policy decisions.
- `src/console/policy/explain.py` - common explanation payload builder.

Decision shape:

```json
{
  "allowed": true,
  "action": "route|block|warn|fallback|teardown",
  "reason": "budget_ok",
  "inputs": {},
  "policy": {"source": "", "version": "", "rule": ""},
  "alternatives": [],
  "audit_required": false
}
```

Design rules:

- Handlers ask policy, services execute.
- Policy returns decisions; it does not perform side effects.
- Every deny/fallback/override has an explanation-ready decision payload.
- Existing config files remain the initial policy source.

### Migration Plan

1. Move `AuthHandler.permission_for` and `has_permission` behind policy facade.
2. Move gateway route/access checks into route policy decisions.
3. Move budget and quota checks into budget policy decisions.
4. Move Dedicated idle/build/teardown decisions into Dedicated policy.
5. Feed decisions into traces, audit, Explain views, and policy-as-code.

### Done Criteria

- Policy decisions are centralized and testable.
- Denials, fallbacks, and teardown actions all carry explanation payloads.
- Handlers do not duplicate permission or budget logic.
- Tests cover policy precedence and override behavior.

## 5. Runtime State Repository Layer

### Problem

Runtime state is correctly separated from release config, but persistence code is
scattered across services and JSON/JSONL helpers. Locking, schema migration,
retention, redaction, backup, and restore behavior are not enforced through one
consistent boundary.

### Target Design

Add repository classes for runtime state with shared atomic write, JSONL append,
locking, redaction, and migration helpers.

Proposed modules:

- `src/console/store/base.py` - atomic JSON write, JSONL append/read windows,
  lock helper, backup metadata.
- `src/console/store/chats.py` - saved chat repository.
- `src/console/store/traces.py` - trace repository.
- `src/console/store/audit.py` - audit repository.
- `src/console/store/sessions.py` - tmux/session repository.
- `src/console/store/evals.py` - eval dataset/run repository.
- `src/console/store/runtime.py` - registry of runtime files and backup policy.

Design rules:

- Services depend on repositories, not raw paths.
- All writes that replace JSON files are atomic.
- JSONL readers support bounded reads and corrupt-line tolerance.
- Repositories expose schema version and migration hooks.
- Backup/restore can query repositories for included files.

### Migration Plan

1. Add base store helpers and use them in new features first.
2. Move trace and audit persistence behind repositories.
3. Move chat/session/eval persistence behind repositories.
4. Integrate runtime backup/restore with repository metadata.
5. Add schema migration tests before changing on-disk formats.

### Done Criteria

- Runtime state writes use shared atomic/append helpers.
- Backup/restore can discover runtime files from repository metadata.
- Services no longer hand-roll JSON/JSONL persistence for core state.
- Tests cover corruption tolerance, atomic writes, migrations, and redaction.
