"""Tmux session registry, naming, and chooser metadata service."""
import json
from http import HTTPStatus


class SessionService:
    """Owns tmux session naming, registry persistence, and enriched session rows."""

    def __init__(self, registry_file, log_file, script_dir, tmux_exists, tmux_cmd, model_metadata_map, clock, resource_monitor=None):
        self.registry_file = registry_file
        self.log_file = log_file
        self.script_dir = script_dir
        self.tmux_exists = tmux_exists
        self.tmux_cmd = tmux_cmd
        self.model_metadata_map = model_metadata_map
        self.clock = clock
        self.resource_monitor = resource_monitor
        self.hidden = {"matts-console-web", "matts-value-set-proxy"}

    def session_name(self, value):
        raw = str(value or "").strip()
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")
        return cleaned[:80] if cleaned else "matts-claude"

    def unique_name(self, base, reserved=None):
        reserved = set(reserved or [])
        root = self.session_name(base)
        candidate = root
        index = 2
        registry = self.read_registry()
        while self.tmux_exists(candidate) or candidate in registry or candidate in reserved:
            suffix = "-%d" % index
            candidate = (root[: max(1, 80 - len(suffix))] + suffix) if len(root) + len(suffix) > 80 else root + suffix
            index += 1
        return candidate

    def read_registry(self):
        path = self.registry_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_registry(self, data):
        path = self.registry_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)

    def upsert(self, name, data=None, live=True, stopped=False):
        registry = self.read_registry()
        record = registry.get(name) if isinstance(registry.get(name), dict) else {}
        now = self.clock()
        record.update({
            "name": name,
            "display_name": (data or {}).get("display_name") or record.get("display_name") or name,
            "updated_at": now,
            "live": bool(live),
        })
        if data:
            record.update({
                "model": data.get("model") or record.get("model") or "",
                "project_dir": data.get("project_dir") or record.get("project_dir") or str(self.script_dir()),
                "run_mode": data.get("run_mode") or record.get("run_mode") or "interactive",
                "permission_mode": data.get("permission_mode") or record.get("permission_mode") or "",
                "profile": data.get("profile") or record.get("profile") or "",
                "output_format": data.get("output_format") or record.get("output_format") or "",
                "claude_session_name": data.get("claude_session_name") or record.get("claude_session_name") or "",
                "max_budget_usd": data.get("max_budget_usd") or record.get("max_budget_usd") or "",
            })
            if isinstance(data.get("imported_context"), dict):
                record["imported_context"] = data.get("imported_context")
        record.setdefault("created_at", now)
        if stopped:
            record["live"] = False
            record["stopped_at"] = now
        registry[name] = record
        self.write_registry(registry)
        return record

    def proxy_usage_since(self, model, since_ts):
        if not model:
            return {"cost_usd": 0.0, "tokens": 0, "requests": 0}
        total_cost = 0.0
        total_tokens = 0
        requests = 0
        path = self.log_file()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-5000:]
        except OSError:
            return {"cost_usd": 0.0, "tokens": 0, "requests": 0}
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if model and row.get("model") != model:
                continue
            if float(row.get("ts") or 0) < float(since_ts or 0):
                continue
            cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
            total_cost += float(cost.get("total_cost_usd") or 0)
            total_tokens += int(cost.get("total_tokens_est") or 0)
            requests += 1
        return {"cost_usd": total_cost, "tokens": total_tokens, "requests": requests}

    def live_session_rows(self):
        fmt = "#{session_name}\t#{session_created}\t#{session_activity}\t#{session_attached}\t#{session_windows}"
        code, out, _ = self.tmux_cmd(["list-sessions", "-F", fmt], check=False)
        if code != 0:
            return {}
        rows = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                attached_clients = int(parts[3] or 0)
            except ValueError:
                attached_clients = 0
            try:
                windows = int(parts[4] or 0)
            except ValueError:
                windows = 0
            rows[parts[0]] = {
                "name": parts[0],
                "created_at": float(parts[1] or 0),
                "last_activity_at": float(parts[2] or 0),
                "attached": attached_clients > 0,
                "attached_clients": attached_clients,
                "windows": windows,
            }
        return rows

    def session_items(self):
        registry = self.read_registry()
        live_rows = self.live_session_rows()
        now = self.clock()
        for name, live in live_rows.items():
            if name in self.hidden:
                continue
            record = registry.get(name) if isinstance(registry.get(name), dict) else {}
            record.update({
                "name": name,
                "display_name": record.get("display_name") or name,
                "live": True,
                "created_at": record.get("created_at") or live.get("created_at") or now,
                "last_activity_at": live.get("last_activity_at") or now,
                "attached": bool(live.get("attached")),
                "attached_clients": int(live.get("attached_clients") or 0),
                "windows": live.get("windows"),
                "updated_at": now,
            })
            registry[name] = record
        for name, record in list(registry.items()):
            if name in self.hidden:
                continue
            if name not in live_rows:
                record["live"] = False
                record["attached"] = False
                record["attached_clients"] = 0
                record.setdefault("stopped_at", record.get("updated_at") or now)
        self.write_registry(registry)

        items = []
        metadata = self.model_metadata_map()
        for name, record in registry.items():
            if name in self.hidden:
                continue
            created = float(record.get("created_at") or 0)
            spend = self.proxy_usage_since(record.get("model") or "", created)
            model_id = record.get("model") or ""
            meta = metadata.get(model_id) or {}
            item = dict(record)
            item.update({
                "name": name,
                "display_name": record.get("display_name") or name,
                "model_display": meta.get("display_name") or model_id or "Unknown model",
                "model_cost": meta.get("cost_label") or "Pricing unavailable",
                "uptime_seconds": int(max(0, now - created)) if created else 0,
                "idle_seconds": int(max(0, now - float(record.get("last_activity_at") or created or now))),
                "estimated_cost_usd": spend["cost_usd"],
                "estimated_tokens": spend["tokens"],
                "estimated_requests": spend["requests"],
                "cost_attribution": "model_since_session_start" if model_id else "unattributed",
                "unattributed": not bool(model_id),
                "process_status": "running" if record.get("live") else "stopped",
                "status": "live" if record.get("live") else "previous",
                "read_only": not bool(record.get("live")),
            })
            if callable(self.resource_monitor) and record.get("live"):
                monitor = self.resource_monitor()
                resources = monitor.summarize(name, project_dir=record.get("project_dir") or str(self.script_dir()), idle_seconds=item["idle_seconds"])
                item["resource_metrics"] = resources
                item["resource_warnings"] = resources.get("warnings") or []
            items.append(item)
        items.sort(key=lambda item: (0 if item.get("live") else 1, -float(item.get("created_at") or item.get("stopped_at") or 0)))
        return items

    def rename_session(self, old_name, new_name, display_name=None):
        old_name = self.session_name(old_name)
        display_name = str(display_name or new_name or old_name).strip() or old_name
        requested_name = self.session_name(new_name or display_name)
        registry = self.read_registry()
        record = registry.get(old_name) if isinstance(registry.get(old_name), dict) else {}
        if record and not record.get("live") and not self.tmux_exists(old_name):
            return HTTPStatus.BAD_REQUEST, {"error": "previous sessions are read-only"}
        reserved = {old_name}
        new_name = old_name if requested_name == old_name else self.unique_name(requested_name, reserved=reserved)
        if old_name == new_name:
            record = registry.get(old_name) if isinstance(registry.get(old_name), dict) else {}
            record["display_name"] = display_name
            record["updated_at"] = self.clock()
            registry[old_name] = record
            self.write_registry(registry)
            return HTTPStatus.OK, {"ok": True, "name": new_name, "display_name": display_name, "renamed": False, "sessions": self.session_items()}
        if self.tmux_exists(old_name):
            code, _, err = self.tmux_cmd(["rename-session", "-t", old_name, new_name], check=False)
            if code != 0:
                return HTTPStatus.BAD_REQUEST, {"error": err or "tmux rename-session failed"}
        record = registry.pop(old_name, {}) if isinstance(registry.get(old_name), dict) else {}
        record["name"] = new_name
        record["display_name"] = display_name
        record["updated_at"] = self.clock()
        registry[new_name] = record
        self.write_registry(registry)
        return HTTPStatus.OK, {"ok": True, "name": new_name, "display_name": display_name, "renamed": True, "sessions": self.session_items()}

    def live_session_names(self):
        items = self.session_items()
        names = [item["name"] for item in items if item.get("live")]
        app_names = [name for name in names if name.startswith("matts-")]
        return app_names or names
