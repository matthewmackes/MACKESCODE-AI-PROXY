# Event Envelope And Local Bus

The console has a synchronous local event bus under `src/console/events/`.
Events are emitted in parallel with existing trace, audit, and lifecycle files
so current JSONL outputs remain compatible.

## Envelope

Each event has:

- `event_id`: local `evt_...` identifier
- `ts`: event timestamp
- `kind`: namespaced event kind such as `trace.created`,
  `audit.recorded`, or `lifecycle.dedicated`
- `severity`: `info`, `warning`, `error`, or related local severity
- `actor`: redacted actor identity
- `subject`: typed subject such as trace, audit, or dedicated
- `correlation`: trace/session/request identifiers where available
- `payload`: redacted event payload
- `redaction`: profile metadata and whether sensitive values were removed

## Redaction

The event envelope redacts fields commonly containing prompts, responses,
terminal screens, provider raw payloads, message arrays, tokens, API keys,
passwords, and secrets before writing to sinks.

## Sinks

`JsonlEventSink` appends events to `events.jsonl` under the runtime app
directory by default. The sink is local and synchronous. Sink failures are
swallowed by producers so trace, audit, and lifecycle writes remain the source
of compatibility.

## Current Producers

- `TraceService.append()` emits `trace.created`
- `AuditService.append()` emits `audit.recorded`
- `DedicatedInferenceService.append_event()` emits `lifecycle.dedicated`

Future notification, review, analytics, and reporting code can consume event
envelopes without changing the existing JSONL compatibility files.
