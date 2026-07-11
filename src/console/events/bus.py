"""Synchronous local event bus."""
from src.console.events.envelope import EventEnvelope


class EventBus:
    """Publish local event envelopes to synchronous sinks."""

    def __init__(self, sinks=None, clock=None, uuid_factory=None):
        self.sinks = list(sinks or [])
        self.clock = clock
        self.uuid_factory = uuid_factory

    def publish(self, kind, severity="info", actor=None, subject=None, correlation=None, payload=None):
        envelope = EventEnvelope.create(kind, severity=severity, actor=actor, subject=subject, correlation=correlation, payload=payload, clock=self.clock, uuid_factory=self.uuid_factory)
        for sink in self.sinks:
            sink.write(envelope)
        return envelope.to_dict()
