"""Local diagnostic snapshot bundles for tmux sessions."""
import hashlib
import json
import re
import time
from pathlib import Path


class SessionSnapshotService:
    """Collect redacted session diagnostics and export JSON/Markdown artifacts."""

    token_re = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|dop_v1_[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]+|token=[^&\s]+)", re.I)

    def __init__(self, snapshots_dir, tmux_session_items, agentboard_payload, read_traces, tail_jsonl, audit_file, tmux_capture, cost_summary_payload, console_status, model_config_file, gateway_policy_file, clock=None):
        self.snapshots_dir = snapshots_dir
        self.tmux_session_items = tmux_session_items
        self.agentboard_payload = agentboard_payload
        self.read_traces = read_traces
        self.tail_jsonl = tail_jsonl
        self.audit_file = audit_file
        self.tmux_capture = tmux_capture
        self.cost_summary_payload = cost_summary_payload
        self.console_status = console_status
        self.model_config_file = model_config_file
        self.gateway_policy_file = gateway_policy_file
        self.clock = clock or time.time

    def redact_text(self, value, limit=None):
        text = self.token_re.sub("[redacted]", str(value or ""))
        return text[:limit] if limit else text

    def redact(self, value):
        if isinstance(value, dict):
            return {key: ("[redacted]" if any(part in str(key).lower() for part in ("token", "secret", "password", "authorization", "api_key")) else self.redact(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value[:50]]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return self.redact_text(value, 500)

    def safe_name(self, value):
        cleaned = "".join(ch for ch in str(value or "session") if ch.isalnum() or ch in "-_")
        return cleaned[:80] or "session"

    def fingerprint(self, path_func):
        path = Path(path_func())
        try:
            data = path.read_bytes()
        except OSError as exc:
            return {"path": str(path), "available": False, "error": str(exc)}
        return {"path": str(path), "available": True, "sha256": hashlib.sha256(data).hexdigest()[:16], "bytes": len(data)}

    def audit_rows(self, session):
        rows = []
        for row in self.tail_jsonl(self.audit_file(), limit=500):
            if not isinstance(row, dict):
                continue
            request = row.get("request") if isinstance(row.get("request"), dict) else {}
            body = request.get("body") if isinstance(request.get("body"), dict) else {}
            names = {body.get("name"), body.get("session_id"), request.get("session_id")}
            if session in {str(item) for item in names if item}:
                rows.append(self.redact(row))
        return rows[-50:]

    def tmux_excerpt(self, session):
        try:
            status, payload = self.tmux_capture(session)
        except Exception as exc:
            return {"available": False, "error": str(exc)}
        if int(status) >= 400:
            return {"available": False, "status": int(status), "error": (payload or {}).get("error") if isinstance(payload, dict) else str(payload)}
        screen = payload.get("screen") if isinstance(payload, dict) else ""
        return {"available": True, "status": int(status), "excerpt": self.redact_text(screen, 4000)}

    def markdown(self, doc):
        session = doc.get("session") or {}
        lines = [
            "# Session Snapshot",
            "",
            "- id: `%s`" % doc.get("id"),
            "- session: `%s`" % session.get("name"),
            "- generated_at: `%s`" % doc.get("generated_at"),
            "- privacy: %s" % doc.get("privacy"),
            "",
            "## Summary",
            "",
            "- model: `%s`" % (session.get("model") or "n/a"),
            "- status: `%s`" % (session.get("status") or session.get("process_status") or "n/a"),
            "- project: `%s`" % (session.get("project_dir") or session.get("path") or "n/a"),
            "",
            "## Resources",
            "",
            "```json",
            json.dumps(doc.get("resources") or {}, indent=2, sort_keys=True),
            "```",
            "",
            "## Traces",
            "",
        ]
        for trace in doc.get("traces") or []:
            lines.append("- `%s` %s %s %s" % (trace.get("trace_id"), trace.get("status"), trace.get("requested_model") or "", trace.get("cost_usd") or ""))
        lines += ["", "## Tmux Excerpt", "", "```text", (doc.get("tmux") or {}).get("excerpt") or "", "```"]
        imported = session.get("imported_context") if isinstance(session.get("imported_context"), dict) else {}
        if imported:
            lines += [
                "",
                "## Imported Repository Context",
                "",
                "- source: `%s %s/%s#%s`" % (imported.get("provider") or "repo", imported.get("owner") or "", imported.get("repo") or "", imported.get("number") or ""),
                "- title: `%s`" % (imported.get("title") or "n/a"),
                "- url: `%s`" % (imported.get("url") or "n/a"),
            ]
        return "\n".join(lines) + "\n"

    def write_artifacts(self, doc):
        root = self.snapshots_dir()
        root.mkdir(parents=True, exist_ok=True)
        base = "%s-%s" % (self.safe_name((doc.get("session") or {}).get("name")), doc.get("id"))
        json_path = root / (base + ".json")
        md_path = root / (base + ".md")
        json_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        md_path.write_text(self.markdown(doc), encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path)}

    def create(self, request):
        request = request if isinstance(request, dict) else {}
        session_name = str(request.get("session") or request.get("name") or "").strip()
        if not session_name:
            raise ValueError("session is required")
        sessions = self.tmux_session_items()
        session = next((row for row in sessions if row.get("name") == session_name), {"name": session_name})
        agentboard = self.agentboard_payload()
        agent = next((row for row in (agentboard.get("sessions") or []) if isinstance(row, dict) and row.get("name") == session_name), {})
        traces = self.read_traces(limit=500, session=session_name)
        now = float(self.clock())
        doc = {
            "id": "snapshot_%d" % now,
            "generated_at": now,
            "actor": self.redact(request.get("actor") or {}),
            "session": self.redact({**session, **{key: agent.get(key) for key in ("status", "path", "last_prompt") if agent.get(key)}}),
            "resources": self.redact(session.get("resource_metrics") or agent.get("resource_metrics") or {}),
            "traces": self.redact(traces[-50:]),
            "audit": self.audit_rows(session_name),
            "tmux": self.tmux_excerpt(session_name),
            "cost": self.redact(self.cost_summary_payload()),
            "console": self.redact(self.console_status()),
            "config_fingerprints": {"model_registry": self.fingerprint(self.model_config_file), "gateway_policy": self.fingerprint(self.gateway_policy_file)},
            "privacy": "Tokens, secret-like fields, and long text are redacted or truncated by default.",
        }
        doc["files"] = self.write_artifacts(doc)
        return {"snapshot": doc, "files": doc["files"]}
