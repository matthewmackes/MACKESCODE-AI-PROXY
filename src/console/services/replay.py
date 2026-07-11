"""Trace and chat replay helpers."""
import difflib
import json
import time
import uuid


class ReplayService:
    """Build replay-safe snapshots and run comparisons through chat routing."""

    def __init__(self, read_traces, load_chat, chat_completion, default_text_model, text_models, replay_file, append_trace=None, clock=None, uuid_factory=None):
        self.read_traces = read_traces
        self.load_chat = load_chat
        self.chat_completion = chat_completion
        self.default_text_model = default_text_model
        self.text_models = text_models
        self.replay_file = replay_file
        self.append_trace = append_trace or (lambda record: record)
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def snapshot(self, source):
        source = source if isinstance(source, dict) else {}
        source_type = str(source.get("type") or source.get("source_type") or "").strip().lower()
        if source_type == "chat":
            return self.chat_snapshot(source.get("id") or source.get("chat_id"), source.get("message_index"))
        if source_type == "trace":
            return self.trace_snapshot(source.get("id") or source.get("trace_id"))
        raise ValueError("replay source type must be trace or chat")

    def chat_snapshot(self, chat_id, message_index=None):
        chat = self.load_chat(chat_id)
        if not chat:
            raise ValueError("chat was not found")
        messages = [self.safe_message(msg) for msg in (chat.get("messages") or []) if isinstance(msg, dict)]
        if message_index not in (None, ""):
            index = int(message_index)
            messages = messages[: index + 1]
        replay_messages = self.prompt_messages(messages)
        if not replay_messages:
            raise ValueError("chat has no replayable user messages")
        return {
            "source": {"type": "chat", "id": chat.get("id"), "message_index": message_index},
            "model": chat.get("model") or self.default_text_model(),
            "messages": replay_messages,
            "available": True,
            "redaction": "full_chat_messages",
            "limitations": [],
        }

    def trace_snapshot(self, trace_id):
        trace = next((row for row in self.read_traces(limit=1000) if row.get("trace_id") == trace_id), None)
        if not trace:
            raise ValueError("trace was not found")
        summary = trace.get("message_summary") if isinstance(trace.get("message_summary"), dict) else {}
        preview = str(summary.get("last_user_preview") or "")
        messages = [{"role": "user", "content": preview}] if preview else []
        limitations = []
        if not preview or int(summary.get("last_user_chars") or len(preview)) > len(preview):
            limitations.append("Trace contains only a redacted prompt preview; replay is approximate or unavailable.")
        return {
            "source": {"type": "trace", "id": trace.get("trace_id")},
            "model": trace.get("requested_model") or trace.get("routed_model") or self.default_text_model(),
            "messages": messages,
            "available": bool(messages),
            "redaction": "trace_summary",
            "limitations": limitations,
            "original": self.safe_trace(trace),
        }

    def replay(self, request):
        request = request if isinstance(request, dict) else {}
        snapshot = request.get("snapshot") if isinstance(request.get("snapshot"), dict) else self.snapshot(request.get("source") if isinstance(request.get("source"), dict) else request)
        if not snapshot.get("available") or not snapshot.get("messages"):
            raise ValueError("source does not retain enough prompt data for replay")
        targets = self.targets(snapshot, request)
        started = float(self.clock())
        replay_id = "replay_%d_%s" % (started, self.uuid_factory().hex[:10])
        baseline_text = str(request.get("baseline_text") or "")
        results = []
        for target in targets:
            req_started = float(self.clock())
            status, payload = self.chat_completion({
                "model": target,
                "messages": snapshot["messages"],
                "max_tokens": request.get("max_tokens") or 512,
                "temperature": request.get("temperature", ""),
            })
            latency_ms = int(max(0, (float(self.clock()) - req_started) * 1000))
            text = str(payload.get("text") if isinstance(payload, dict) else "")
            cost = payload.get("cost") if isinstance(payload, dict) and isinstance(payload.get("cost"), dict) else {}
            routing = payload.get("routing") if isinstance(payload, dict) and isinstance(payload.get("routing"), dict) else {}
            results.append({
                "model": target,
                "status": int(status),
                "ok": int(status) < 400,
                "text": text,
                "routing": routing,
                "latency_ms": latency_ms,
                "usage": payload.get("usage") if isinstance(payload, dict) else {},
                "cost": cost,
                "cost_usd": float(cost.get("total_cost_usd") or 0.0),
                "trace_id": payload.get("trace_id") if isinstance(payload, dict) else "",
                "error": (payload.get("message") or payload.get("error") or "") if isinstance(payload, dict) and int(status) >= 400 else "",
                "diff": self.diff(baseline_text, text),
            })
        doc = {
            "id": replay_id,
            "created_at": started,
            "source": snapshot.get("source") or {},
            "snapshot": {key: snapshot.get(key) for key in ("model", "redaction", "limitations", "available")},
            "targets": targets,
            "results": results,
            "summary": self.summary(results),
        }
        self.record(doc)
        self.append_trace({
            "trace_id": replay_id,
            "timestamp": started,
            "action": "replay.run",
            "status": "ok" if all(row["ok"] for row in results) else "error",
            "requested_model": ",".join(targets),
            "routing_reason": "replay",
            "source": snapshot.get("source") or {},
            "cost_usd": round(sum(row.get("cost_usd") or 0 for row in results), 8),
        })
        return doc

    def targets(self, snapshot, request):
        mode = str(request.get("target") or "original").strip().lower()
        selected = [str(model) for model in (request.get("models") or []) if str(model or "").strip()]
        if mode == "comparison" and selected:
            targets = selected[:5]
        elif mode == "selected" and selected:
            targets = selected[:1]
        elif mode == "default":
            targets = [self.default_text_model()]
        else:
            targets = [snapshot.get("model") or self.default_text_model()]
        active = set(self.text_models())
        unavailable = [model for model in targets if model not in active]
        if unavailable:
            raise ValueError("unavailable replay models: " + ", ".join(unavailable))
        return targets

    def list_records(self, limit=50):
        path = self.replay_file()
        if not path.exists():
            return []
        rows = []
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            rows.append(row)
            if len(rows) >= int(limit or 50):
                break
        return rows

    def record(self, doc):
        path = self.replay_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(doc, sort_keys=True) + "\n")

    def prompt_messages(self, messages):
        rows = []
        for msg in messages:
            role = str(msg.get("role") or "")
            if role in {"user", "system"}:
                content = str(msg.get("content") or "").strip()
                if content:
                    rows.append({"role": role, "content": content})
        return rows[-20:]

    def safe_message(self, msg):
        return {"role": str(msg.get("role") or ""), "content": str(msg.get("content") or ""), "timestamp": msg.get("timestamp")}

    def safe_trace(self, trace):
        return {key: trace.get(key) for key in ("trace_id", "timestamp", "status", "requested_model", "routed_model", "routing_reason", "endpoint_mode", "latency_ms", "cost_usd")}

    def diff(self, before, after):
        before = str(before or "")
        after = str(after or "")
        return {
            "changed": before != after,
            "line_diff": list(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile="baseline", tofile="replay", lineterm=""))[:80],
            "chars_before": len(before),
            "chars_after": len(after),
        }

    def summary(self, results):
        return {
            "models": len(results),
            "ok": sum(1 for row in results if row.get("ok")),
            "errors": sum(1 for row in results if not row.get("ok")),
            "total_cost_usd": round(sum(float(row.get("cost_usd") or 0.0) for row in results), 8),
            "avg_latency_ms": int(sum(int(row.get("latency_ms") or 0) for row in results) / max(1, len(results))),
        }
