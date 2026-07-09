"""Request trace persistence and redaction helpers."""
import json
import time
import uuid


class TraceService:
    """Append and query privacy-safe trace records."""

    def __init__(self, trace_file, clock=None, uuid_factory=None):
        self.trace_file = trace_file
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def new_id(self):
        return "trace_%s" % self.uuid_factory().hex

    def summarize_messages(self, messages, limit=160):
        rows = messages if isinstance(messages, list) else []
        last_user = ""
        for msg in rows:
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user = str(msg.get("content") or "")
        preview = " ".join(last_user.split())[:limit]
        return {
            "message_count": len(rows),
            "last_user_preview": preview,
            "last_user_chars": len(last_user),
        }

    def normalize(self, record):
        now = self.clock()
        rec = dict(record or {})
        rec.setdefault("trace_id", self.new_id())
        rec.setdefault("timestamp", now)
        rec.setdefault("status", "unknown")
        if "latency_ms" in rec:
            rec["latency_ms"] = int(max(0, rec["latency_ms"]))
        return rec

    def append(self, record):
        rec = self.normalize(record)
        path = self.trace_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def read(self, limit=200, model=None, status=None, session=None, min_cost=None):
        rows = []
        path = self.trace_file()
        if not path.exists():
            return rows
        try:
            raw_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return rows
        for line in reversed(raw_lines):
            try:
                row = json.loads(line)
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
