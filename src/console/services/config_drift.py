"""Runtime configuration drift detection against a local baseline."""
import hashlib
import json
import time
from pathlib import Path


class ConfigDriftService:
    """Compare operational files and config summaries against a known-good baseline."""

    def __init__(self, baseline_file, items, append_audit=None, clock=None):
        self.baseline_file = baseline_file
        self.items = items
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.clock = clock or time.time

    def value(self, item, key, default=None):
        raw = item.get(key, default)
        return raw() if callable(raw) else raw

    def safe_actor(self, actor):
        actor = actor if isinstance(actor, dict) else {}
        return {
            "id": str(actor.get("id") or actor.get("name") or "unknown"),
            "roles": [str(role) for role in (actor.get("roles") or [])],
            "source": str(actor.get("source") or ""),
        }

    def sha(self, data):
        return hashlib.sha256(data).hexdigest()

    def file_fingerprint(self, item):
        path = Path(self.value(item, "path"))
        base = {
            "name": item["name"],
            "label": self.value(item, "label", item["name"]),
            "risk": self.value(item, "risk", "medium"),
            "path": str(path),
            "kind": "file",
            "rollback": self.rollback_guidance(item),
        }
        try:
            stat = path.stat()
        except OSError as exc:
            base.update({"exists": False, "type": "missing", "size": 0, "mtime_ns": 0, "sha256": "", "sha256_short": "", "error": str(exc)})
            return base
        if path.is_dir():
            children = sorted(str(child.relative_to(path)) for child in path.rglob("*") if child.exists())[:1000]
            payload = json.dumps(children, sort_keys=True).encode("utf-8")
            base.update({"exists": True, "type": "directory", "size": len(children), "mtime_ns": stat.st_mtime_ns, "sha256": self.sha(payload), "sha256_short": self.sha(payload)[:16]})
            return base
        try:
            data = path.read_bytes()
        except OSError as exc:
            base.update({"exists": True, "type": "unreadable", "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": "", "sha256_short": "", "error": str(exc)})
            return base
        digest = self.sha(data)
        base.update({"exists": True, "type": "file", "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest, "sha256_short": digest[:16]})
        if path.suffix.lower() == ".json":
            try:
                json.loads(data.decode("utf-8"))
                base["json_valid"] = True
            except (UnicodeDecodeError, ValueError) as exc:
                base["json_valid"] = False
                base["json_error"] = str(exc)
        return base

    def virtual_fingerprint(self, item):
        provider = self.value(item, "value_provider")
        value = provider() if callable(provider) else provider
        payload = json.dumps(value if isinstance(value, (dict, list)) else {"value": value}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = self.sha(payload)
        return {
            "name": item["name"],
            "label": self.value(item, "label", item["name"]),
            "risk": self.value(item, "risk", "medium"),
            "path": self.value(item, "path", ""),
            "kind": "summary",
            "exists": True,
            "type": "summary",
            "size": len(payload),
            "mtime_ns": 0,
            "sha256": digest,
            "sha256_short": digest[:16],
            "summary": value,
            "rollback": self.rollback_guidance(item),
        }

    def rollback_guidance(self, item):
        archive = self.value(item, "backup_item", "")
        if archive:
            return {
                "backup_item": archive,
                "backup_command": "python3 scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz",
                "restore_command": "python3 scripts/runtime-state.py restore <archive>",
                "note": "Inspect the archive manifest before restoring; restore moves existing files aside unless --overwrite is used.",
            }
        return {
            "backup_item": "",
            "backup_command": "python3 scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz",
            "restore_command": "",
            "note": "No direct runtime-state restore item is registered for this summary; compare the current config to the marked baseline.",
        }

    def current_items(self):
        rows = []
        for item in self.items:
            try:
                if item.get("kind") == "summary":
                    rows.append(self.virtual_fingerprint(item))
                else:
                    rows.append(self.file_fingerprint(item))
            except Exception as exc:
                rows.append({
                    "name": item.get("name") or "unknown",
                    "label": self.value(item, "label", item.get("name") or "unknown"),
                    "risk": self.value(item, "risk", "medium"),
                    "path": str(self.value(item, "path", "")),
                    "kind": self.value(item, "kind", "file"),
                    "exists": False,
                    "type": "error",
                    "size": 0,
                    "mtime_ns": 0,
                    "sha256": "",
                    "sha256_short": "",
                    "error": str(exc),
                    "rollback": self.rollback_guidance(item),
                })
        return rows

    def read_baseline(self):
        path = Path(self.baseline_file())
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"error": str(exc), "items": {}, "acknowledgements": [], "path": str(path)}
        data["path"] = str(path)
        return data

    def write_baseline(self, doc):
        path = Path(self.baseline_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def ack_keys(self, baseline):
        keys = set()
        for ack in (baseline or {}).get("acknowledgements") or []:
            for item in ack.get("items") or []:
                keys.add("%s:%s" % (item.get("name"), item.get("sha256")))
        return keys

    def drift_rows(self, current, baseline):
        baseline_items = (baseline or {}).get("items") or {}
        acked = self.ack_keys(baseline)
        rows = []
        if not baseline_items:
            for item in current:
                row = dict(item)
                row.update({"status": "unbaselined", "changed": True, "baseline": None, "current": item, "acknowledged": False})
                rows.append(row)
            return rows
        current_by_name = {item["name"]: item for item in current}
        for name in sorted(set(baseline_items) | set(current_by_name)):
            base = baseline_items.get(name)
            cur = current_by_name.get(name)
            template = cur or base or {"name": name, "label": name, "risk": "medium", "rollback": {}}
            status = "unchanged"
            changed = False
            if base is None and cur is not None:
                status, changed = "created", True
            elif base is not None and cur is None:
                status, changed = "missing", True
            elif bool(base.get("exists")) != bool(cur.get("exists")):
                status, changed = "existence_changed", True
            elif base.get("type") != cur.get("type"):
                status, changed = "type_changed", True
            elif base.get("sha256") != cur.get("sha256"):
                status, changed = "changed", True
            if changed:
                row = {
                    "name": name,
                    "label": template.get("label") or name,
                    "risk": template.get("risk") or "medium",
                    "path": template.get("path") or "",
                    "kind": template.get("kind") or "",
                    "status": status,
                    "changed": True,
                    "baseline": base,
                    "current": cur,
                    "rollback": template.get("rollback") or {},
                    "acknowledged": ("%s:%s" % (name, (cur or {}).get("sha256"))) in acked,
                }
                rows.append(row)
        return rows

    def summary(self, rows, baseline):
        weights = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        active = [row for row in rows if row.get("changed") and not row.get("acknowledged")]
        acknowledged = [row for row in rows if row.get("acknowledged")]
        highest = "none"
        if active:
            highest = max((row.get("risk") or "medium" for row in active), key=lambda risk: weights.get(risk, 2))
        return {
            "baseline_present": bool((baseline or {}).get("items")),
            "drift_count": len([row for row in rows if row.get("changed")]),
            "active_drift_count": len(active),
            "acknowledged_count": len(acknowledged),
            "highest_risk": highest,
            "state": "no_baseline" if not (baseline or {}).get("items") else ("drift" if active else ("acknowledged" if acknowledged else "clean")),
        }

    def payload(self):
        current = self.current_items()
        baseline = self.read_baseline()
        rows = self.drift_rows(current, baseline)
        return {
            "baseline": baseline or {"path": str(self.baseline_file()), "items": {}, "acknowledgements": []},
            "items": current,
            "drift": rows,
            "summary": self.summary(rows, baseline),
            "rollback": {
                "backup_command": "python3 scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz",
                "restore_command": "python3 scripts/runtime-state.py restore <archive>",
                "docs": "RELEASE.md",
            },
        }

    def mark_baseline(self, request):
        request = request if isinstance(request, dict) else {}
        actor = self.safe_actor(request.get("actor") or {})
        current = self.current_items()
        now = float(self.clock())
        doc = {
            "schema_version": 1,
            "created_at": now,
            "label": str(request.get("label") or "last-known-good"),
            "reason": str(request.get("reason") or "operator_marked_good"),
            "actor": actor,
            "items": {item["name"]: item for item in current},
            "acknowledgements": [],
        }
        path = self.write_baseline(doc)
        self.append_audit("config_drift.baseline.mark", actor=actor, outcome="completed", permission="config_drift_admin", request={"label": doc["label"], "reason": doc["reason"], "items": list(doc["items"].keys())}, status=200)
        payload = self.payload()
        payload["baseline_file"] = str(path)
        return payload

    def acknowledge(self, request):
        request = request if isinstance(request, dict) else {}
        baseline = self.read_baseline()
        if not baseline or not baseline.get("items"):
            raise ValueError("baseline is required before acknowledging drift")
        current = self.current_items()
        rows = self.drift_rows(current, baseline)
        names = request.get("items")
        if isinstance(names, str):
            names = [names]
        wanted = {str(name) for name in names} if names else {row["name"] for row in rows if row.get("changed")}
        ack_items = []
        for row in rows:
            if row.get("name") in wanted and row.get("changed") and row.get("current"):
                cur = row["current"]
                ack_items.append({"name": row["name"], "sha256": cur.get("sha256"), "status": row.get("status"), "risk": row.get("risk")})
        if not ack_items:
            raise ValueError("no current drift items matched the acknowledgement request")
        ack = {
            "acknowledged_at": float(self.clock()),
            "actor": self.safe_actor(request.get("actor") or {}),
            "reason": str(request.get("reason") or "operator_acknowledged"),
            "items": ack_items,
        }
        baseline.setdefault("acknowledgements", []).append(ack)
        self.write_baseline(baseline)
        self.append_audit("config_drift.acknowledge", actor=ack["actor"], outcome="completed", permission="config_drift_admin", request={"reason": ack["reason"], "items": ack_items}, status=200)
        return self.payload()
