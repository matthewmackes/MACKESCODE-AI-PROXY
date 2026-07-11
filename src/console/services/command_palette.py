"""Searchable operational command registry and audited dispatch."""
import time


class CommandPaletteService:
    """Expose command metadata and validate dispatch permissions."""

    DEFAULT_COMMANDS = [
        {"id": "code.start_session", "title": "Start Claude Code Session", "group": "Code", "permission": "tmux_control", "action": {"type": "click", "target": "term-new"}, "keywords": ["claude", "code", "session", "start"]},
        {"id": "code.focus_terminal", "title": "Focus Current Terminal", "group": "Code", "permission": "tmux_control", "action": {"type": "click", "target": "term-focus"}, "keywords": ["terminal", "focus", "tmux"]},
        {"id": "agent.snapshot", "title": "Create Selected Session Snapshot", "group": "AgentBoard", "permission": "tmux_control", "action": {"type": "click", "target": "agent-snapshot"}, "contextual": True, "keywords": ["snapshot", "session", "diagnostic"]},
        {"id": "agent.patch_review", "title": "Review Selected Session Patch", "group": "AgentBoard", "permission": "tmux_control", "action": {"type": "click", "target": "agent-patch-review"}, "contextual": True, "keywords": ["patch", "review", "diff"]},
        {"id": "eval.run", "title": "Run Eval", "group": "Eval", "permission": "eval_run", "action": {"type": "click", "target": "eval-run"}, "keywords": ["eval", "quality", "test"]},
        {"id": "models.audit_key", "title": "Audit Model Access Key", "group": "Models", "permission": "model_admin", "action": {"type": "click", "target": "models-audit-key"}, "keywords": ["model", "key", "audit", "access"]},
        {"id": "models.refresh_catalog", "title": "Refresh DigitalOcean Catalog", "group": "Models", "permission": "model_admin", "action": {"type": "click", "target": "models-import-serverless"}, "keywords": ["serverless", "catalog", "models"]},
        {"id": "proxy.sync", "title": "Sync Proxy", "group": "Operations", "permission": "model_admin", "action": {"type": "click", "target": "sync-proxy"}, "keywords": ["proxy", "registry", "sync"]},
        {"id": "traces.open", "title": "Open Traces", "group": "Observability", "permission": "view_traces", "action": {"type": "console_view", "target": "traces"}, "keywords": ["trace", "observability", "routing"]},
        {"id": "trace.replay", "title": "Replay Selected Trace", "group": "Observability", "permission": "replay_run", "action": {"type": "custom", "target": "replay_trace"}, "contextual": True, "keywords": ["trace", "replay"]},
        {"id": "release.open", "title": "Open Release Dashboard", "group": "Release", "permission": "view_console", "action": {"type": "console_view", "target": "release"}, "keywords": ["release", "readiness", "dashboard"]},
        {"id": "rollback.open", "title": "Open Rollback Wizard", "group": "Operations", "permission": "rollback_admin", "action": {"type": "console_view", "target": "ops", "focus": "rollback-target"}, "keywords": ["rollback", "restore", "backup"]},
        {"id": "docs.search", "title": "Search Project Docs", "group": "Docs", "permission": "view_console", "action": {"type": "docs_search", "target": "docs"}, "keywords": ["docs", "documentation", "search"]},
        {"id": "model.detail", "title": "Open Selected Model Detail", "group": "Models", "permission": "view_console", "action": {"type": "custom", "target": "model_detail"}, "contextual": True, "keywords": ["model", "detail", "info"]},
        {"id": "session.open", "title": "Open Selected Agent Session", "group": "AgentBoard", "permission": "tmux_control", "action": {"type": "click", "target": "agent-open"}, "contextual": True, "keywords": ["agent", "tmux", "session"]},
    ]

    def __init__(self, append_audit=None, commands=None, clock=None):
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.commands = list(commands or self.DEFAULT_COMMANDS)
        self.clock = clock or time.time

    def actor_permissions(self, actor):
        actor = actor if isinstance(actor, dict) else {}
        return set(actor.get("permissions") or [])

    def allowed(self, command, actor):
        permission = command.get("permission") or "view_console"
        perms = self.actor_permissions(actor)
        return "*" in perms or permission in perms

    def public_command(self, command, actor=None, context=None):
        row = {key: command.get(key) for key in ("id", "title", "group", "permission", "action", "contextual", "keywords")}
        row["context_ready"] = self.context_ready(command, context or {})
        row["available"] = self.allowed(command, actor or {"permissions": ["*"]}) and row["context_ready"]
        return row

    def search(self, query="", actor=None, context=None):
        query = str(query or "").strip().lower()
        rows = []
        for command in self.commands:
            haystack = " ".join([command.get("id", ""), command.get("title", ""), command.get("group", "")] + list(command.get("keywords") or [])).lower()
            if query and query not in haystack:
                continue
            row = self.public_command(command, actor, context=context)
            rows.append(row)
        rows.sort(key=lambda row: (not row.get("available"), row.get("group") or "", row.get("title") or ""))
        return rows

    def payload(self, query="", actor=None, context=None):
        rows = self.search(query=query, actor=actor, context=context)
        return {
            "generated_at": float(self.clock()),
            "commands": rows,
            "summary": {"commands": len(rows), "available": len([row for row in rows if row.get("available")]), "contextual": len([row for row in rows if row.get("contextual")])},
            "shortcut": "Ctrl+K or Command+K",
        }

    def dispatch(self, request):
        request = request if isinstance(request, dict) else {}
        command_id = str(request.get("id") or "").strip()
        actor = request.get("actor") if isinstance(request.get("actor"), dict) else {}
        command = next((row for row in self.commands if row.get("id") == command_id), None)
        if command is None:
            raise ValueError("command not found")
        if not self.allowed(command, actor):
            raise PermissionError("command permission denied")
        context = request.get("context") if isinstance(request.get("context"), dict) else {}
        if not self.context_ready(command, context):
            raise ValueError("command context unavailable")
        result = self.public_command(command, actor, context=context)
        result["context"] = context
        self.append_audit("command_palette.dispatch", actor=actor, outcome="completed", permission=command.get("permission") or "view_console", request={"id": command_id, "context": result["context"]}, status=200)
        return {"command": result, "action": result.get("action"), "dispatched_at": float(self.clock())}

    def context_ready(self, command, context):
        if not command.get("contextual"):
            return True
        command_id = command.get("id")
        if command_id in {"agent.snapshot", "agent.patch_review", "session.open"}:
            return bool(context.get("session"))
        if command_id == "trace.replay":
            return bool(context.get("trace_id"))
        if command_id == "model.detail":
            return bool(context.get("model"))
        return False
