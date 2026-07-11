import json
import tempfile
import unittest
from pathlib import Path

from src.console.events.bus import EventBus
from src.console.events.envelope import EventEnvelope
from src.console.events.sinks import JsonlEventSink
from src.console.services.audit import AuditService
from src.console.services.traces import TraceService


class FakeUuid:
    hex = "abc123"


class EventBusTests(unittest.TestCase):
    def test_envelope_validates_and_redacts_sensitive_payload(self):
        event = EventEnvelope.create(
            "trace.created",
            payload={"trace_id": "trace-a", "messages": [{"content": "private"}], "nested": {"token": "secret"}},
            clock=lambda: 1000,
            uuid_factory=lambda: FakeUuid(),
        )

        payload = event.to_dict()

        self.assertEqual(payload["event_id"], "evt_abc123")
        self.assertEqual(payload["payload"]["messages"], "[redacted]")
        self.assertEqual(payload["payload"]["nested"]["token"], "[redacted]")
        self.assertTrue(payload["redaction"]["contains_sensitive"])
        with self.assertRaisesRegex(ValueError, "kind"):
            EventEnvelope.create("")

    def test_bus_writes_jsonl_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            bus = EventBus([JsonlEventSink(lambda: path)], clock=lambda: 1000, uuid_factory=lambda: FakeUuid())

            bus.publish("audit.recorded", actor={"id": "ops"}, payload={"action": "test"})

            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["kind"], "audit.recorded")
            self.assertEqual(row["actor"]["id"], "ops")

    def test_trace_and_audit_emit_events_without_changing_primary_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            bus = EventBus([JsonlEventSink(lambda: events)], clock=lambda: 1000, uuid_factory=lambda: FakeUuid())
            trace_path = root / "traces.jsonl"
            audit_path = root / "audit.jsonl"
            trace = TraceService(trace_file=lambda: trace_path, clock=lambda: 1000, uuid_factory=lambda: FakeUuid(), event_bus=bus)
            audit = AuditService(audit_file=lambda: audit_path, clock=lambda: 1001, event_bus=bus)

            trace_record = trace.append({"action": "chat", "status": "success", "messages": [{"role": "user", "content": "private"}]})
            audit_record = audit.append("model.save", actor={"id": "ops"}, request={"token": "secret"})

            trace_row = json.loads(trace_path.read_text(encoding="utf-8"))
            audit_row = json.loads(audit_path.read_text(encoding="utf-8"))
            event_rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(trace_row["trace_id"], trace_record["trace_id"])
            self.assertEqual(audit_row["request"]["token"], "[redacted]")
            self.assertEqual([row["kind"] for row in event_rows], ["trace.created", "audit.recorded"])
            self.assertEqual(event_rows[0]["payload"]["messages"], "[redacted]")
            self.assertEqual(event_rows[1]["payload"]["request"]["token"], "[redacted]")


if __name__ == "__main__":
    unittest.main()
