"""Request trace persistence and redaction helpers."""
import time
import uuid

from src.console.domain.traces import MessageSummary, TraceRecord
from src.console.store import TraceRepository


class TraceService:
    """Append and query privacy-safe trace records."""

    def __init__(self, trace_file, clock=None, uuid_factory=None, otel_exporter=None, event_bus=None, repository=None):
        self.trace_file = trace_file
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4
        self.otel_exporter = otel_exporter
        self.event_bus = event_bus
        self.repository = repository or TraceRepository(trace_file, clock=self.clock)

    def new_id(self):
        return "trace_%s" % self.uuid_factory().hex

    def summarize_messages(self, messages, limit=160):
        return MessageSummary.from_messages(messages, limit=limit).to_dict()

    def normalize(self, record):
        now = self.clock()
        rec = dict(record or {})
        rec.setdefault("trace_id", self.new_id())
        rec.setdefault("timestamp", now)
        rec.setdefault("status", "unknown")
        return TraceRecord.from_dict(rec).to_dict()

    def append(self, record):
        rec = self.normalize(record)
        self.repository.append(rec)
        if self.event_bus is not None:
            try:
                self.event_bus.publish(
                    "trace.created",
                    severity="error" if rec.get("status") == "error" else "info",
                    subject={"type": "trace", "id": rec.get("trace_id")},
                    correlation={"trace_id": rec.get("trace_id"), "session_id": rec.get("session_id") or rec.get("chat_id") or rec.get("tmux_session") or ""},
                    payload=rec,
                )
            except Exception:
                pass
        if self.otel_exporter is not None:
            try:
                self.otel_exporter.export_trace(rec)
            except Exception:
                pass
        return rec

    def read(self, limit=200, model=None, status=None, session=None, min_cost=None):
        rows = []
        filters = {"model": model, "status": status, "session": session, "min_cost": min_cost}
        for row in self.repository.read(limit=limit or 200, filters=filters):
            try:
                row = TraceRecord.from_dict(row).to_dict()
            except ValueError:
                continue
            if model and model not in {row.get("requested_model"), row.get("routed_model")}:
                continue
            if status and str(row.get("status")) != str(status):
                continue
            if session and session not in {row.get("session_id"), row.get("chat_id"), row.get("tmux_session")}:
                continue
            if min_cost not in (None, ""):
                try:
                    if float(row.get("cost_usd") or 0) < float(min_cost):
                        continue
                except (TypeError, ValueError):
                    continue
            rows.append(row)
            if len(rows) >= int(limit or 200):
                break
        return rows

    def metadata(self):
        return self.repository.metadata()
