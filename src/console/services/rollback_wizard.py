"""Guided rollback target discovery, preview, and runtime-state restore."""
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import time
import warnings
from pathlib import Path


class RollbackWizardService:
    """Discover rollback targets and apply runtime-state archive restores safely."""

    def __init__(self, archive_dirs, backup_output_dir, item_paths, append_audit=None, health_check=None, v2_run_db=None, clock=None):
        self.archive_dirs = archive_dirs
        self.backup_output_dir = backup_output_dir
        self.item_paths = item_paths
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.health_check = health_check or (lambda: {"offered": True, "message": "Run scripts/health-validate.py after rollback."})
        self.v2_run_db = v2_run_db
        self.clock = clock or time.time

    def value(self, raw):
        return raw() if callable(raw) else raw

    def safe_actor(self, actor):
        actor = actor if isinstance(actor, dict) else {}
        return {
            "id": str(actor.get("id") or actor.get("name") or "unknown"),
            "roles": [str(role) for role in (actor.get("roles") or [])],
            "source": str(actor.get("source") or ""),
        }

    def target_id(self, path):
        path = Path(path)
        key = "%s:%s:%s" % (path.resolve(), path.stat().st_mtime_ns, path.stat().st_size)
        return "runtime:%s" % hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def archive_candidates(self):
        seen = set()
        for raw_dir in self.value(self.archive_dirs) or []:
            root = Path(raw_dir).expanduser()
            for pattern in ("*.tar.gz", "*.tgz"):
                for path in sorted(root.glob(pattern), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
                    if path in seen or not path.is_file():
                        continue
                    seen.add(path)
                    yield path

    def read_archive_manifest(self, path):
        path = Path(path)
        with tarfile.open(path, "r:gz") as tar:
            member = tar.getmember("manifest.json")
            handle = tar.extractfile(member)
            if handle is None:
                raise ValueError("manifest.json is missing")
            manifest = json.loads(handle.read().decode("utf-8"))
        stat = path.stat()
        return {
            "id": self.target_id(path),
            "type": "runtime_state_archive",
            "path": str(path),
            "created_at": manifest.get("created_at") or stat.st_mtime,
            "include_secrets": bool(manifest.get("include_secrets")),
            "items": manifest.get("items") if isinstance(manifest.get("items"), list) else [],
            "size": stat.st_size,
        }

    def runtime_targets(self):
        targets = []
        for path in self.archive_candidates():
            try:
                targets.append(self.read_archive_manifest(path))
            except (OSError, tarfile.TarError, KeyError, ValueError, json.JSONDecodeError) as exc:
                targets.append({"id": "invalid:%s" % hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12], "type": "invalid_archive", "path": str(path), "error": str(exc), "items": []})
        return targets

    def v2_targets(self):
        path = Path(self.value(self.v2_run_db) if self.v2_run_db else os.environ.get("MATTS_V2_RUN_DB", Path.home() / ".cache/matts-value-set/studio/v2-run.sqlite3"))
        if not path.exists():
            return []
        try:
            conn = sqlite3.connect(str(path))
            try:
                profile_count = conn.execute("SELECT COUNT(*) FROM run_profile_versions").fetchone()[0]
                template_count = conn.execute("SELECT COUNT(*) FROM prompt_template_versions").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return [{"id": "v2-run-store", "type": "v2_run_versions", "path": str(path), "error": str(exc), "items": []}]
        rows = []
        if profile_count:
            rows.append({"id": "v2-run-profiles", "type": "v2_run_profile_versions", "path": str(path), "count": int(profile_count), "apply": "Use React Run workspace or POST /v2/run/profiles/{profile_id}/rollback."})
        if template_count:
            rows.append({"id": "v2-prompt-templates", "type": "v2_prompt_template_versions", "path": str(path), "count": int(template_count), "apply": "Use React Run workspace or POST /v2/run/prompt-templates/{template_id}/rollback."})
        return rows

    def targets(self):
        runtime = self.runtime_targets()
        v2 = self.v2_targets()
        return {
            "targets": runtime + v2,
            "summary": {"runtime_archives": len([row for row in runtime if row.get("type") == "runtime_state_archive"]), "v2_version_targets": len(v2)},
            "procedures": {
                "runtime_state": "scripts/runtime-state.py backup --output build/runtime-state-backup.tar.gz && scripts/runtime-state.py restore <archive>",
                "v2_profiles": "Use the React Run workspace rollback controls for immutable prompt-template and run-profile versions.",
                "health_validation": "Run scripts/health-validate.py after restoring runtime state.",
            },
        }

    def find_target(self, target_id):
        for target in self.runtime_targets():
            if target.get("id") == target_id or target.get("path") == target_id:
                if target.get("type") != "runtime_state_archive":
                    raise ValueError("target is not restorable")
                return target
        raise ValueError("rollback target not found")

    def current_state(self, entry):
        path = Path(entry.get("path") or "")
        try:
            stat = path.stat()
        except OSError:
            return {"exists": False, "type": "missing", "size": 0, "mtime_ns": 0}
        return {"exists": True, "type": "directory" if path.is_dir() else "file", "size": len(list(path.rglob("*"))) if path.is_dir() else stat.st_size, "mtime_ns": stat.st_mtime_ns}

    def preview(self, request):
        request = request if isinstance(request, dict) else {}
        target = self.find_target(str(request.get("target_id") or request.get("path") or ""))
        selected = request.get("items")
        if isinstance(selected, str):
            selected = [selected]
        selected = {str(item) for item in selected} if selected else None
        items = []
        for entry in target.get("items") or []:
            if selected and entry.get("name") not in selected:
                continue
            current = self.current_state(entry)
            items.append({
                "name": entry.get("name"),
                "path": entry.get("path"),
                "archive_exists": bool(entry.get("exists")),
                "archive_type": entry.get("type"),
                "current": current,
                "impact": "restore" if entry.get("exists") else "skip_missing_archive_item",
                "will_move_existing_aside": bool(entry.get("exists") and current.get("exists")),
            })
        return {
            "target": target,
            "items": items,
            "summary": {
                "items": len(items),
                "will_restore": len([item for item in items if item.get("impact") == "restore"]),
                "will_move_existing_aside": len([item for item in items if item.get("will_move_existing_aside")]),
                "include_secrets": bool(target.get("include_secrets")),
            },
            "next_checks": ["Run scripts/health-validate.py", "Refresh Console > System Operations", "Review config drift after rollback"],
        }

    def copy_into_payload(self, source, dest):
        source = Path(source)
        if source.is_dir():
            shutil.copytree(source, dest)
        elif source.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)

    def create_pre_backup(self, entries):
        root = Path(self.value(self.backup_output_dir))
        root.mkdir(parents=True, exist_ok=True)
        output = root / ("pre-rollback-%d.tar.gz" % int(self.clock()))
        staging = root / (".%s.staging" % output.name)
        if staging.exists():
            shutil.rmtree(staging)
        payload = staging / "payload"
        payload.mkdir(parents=True)
        manifest = {"created_at": int(self.clock()), "include_secrets": False, "items": []}
        for entry in entries:
            source = Path(entry.get("path") or "")
            item = {"name": entry.get("name"), "path": str(source), "exists": source.exists(), "type": "missing"}
            if source.is_dir():
                item["type"] = "directory"
            elif source.is_file():
                item["type"] = "file"
            if source.exists():
                self.copy_into_payload(source, payload / str(entry.get("name")))
            manifest["items"].append(item)
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with tarfile.open(output, "w:gz") as tar:
            tar.add(staging / "manifest.json", arcname="manifest.json")
            tar.add(payload, arcname="payload")
        shutil.rmtree(staging)
        return output

    def extract_archive(self, archive):
        archive = Path(archive)
        staging = archive.parent / (".%s.rollback" % archive.name)
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        with tarfile.open(archive, "r:gz") as tar:
            staging_root = staging.resolve()
            for member in tar.getmembers():
                target = (staging / member.name).resolve()
                if staging_root not in target.parents and target != staging_root:
                    raise ValueError("archive member escapes rollback directory: %s" % member.name)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    tar.extract(member, staging)
        return staging

    def apply(self, request):
        request = request if isinstance(request, dict) else {}
        reason = str(request.get("reason") or "").strip()
        if not reason:
            raise ValueError("rollback reason is required")
        actor = self.safe_actor(request.get("actor") or {})
        preview = self.preview(request)
        entries = [entry for entry in (preview.get("target", {}).get("items") or []) if entry.get("name") in {item["name"] for item in preview.get("items") or []} and entry.get("exists")]
        if not entries:
            raise ValueError("no restorable items selected")
        pre_backup = self.create_pre_backup(entries)
        staging = self.extract_archive(preview["target"]["path"])
        restored = []
        try:
            for entry in entries:
                src = staging / "payload" / str(entry.get("name"))
                if not src.exists():
                    continue
                dest = Path(entry.get("path") or "")
                moved_aside = ""
                if dest.exists():
                    moved = dest.with_name(dest.name + ".pre-rollback-%d" % int(self.clock()))
                    shutil.move(str(dest), str(moved))
                    moved_aside = str(moved)
                dest.parent.mkdir(parents=True, exist_ok=True)
                self.copy_into_payload(src, dest)
                restored.append({"name": entry.get("name"), "path": str(dest), "moved_aside": moved_aside})
        finally:
            shutil.rmtree(staging)
        health = self.health_check()
        result = {
            "target": preview["target"],
            "pre_backup": str(pre_backup),
            "restored": restored,
            "health": health,
            "next_checks": preview.get("next_checks") or [],
        }
        self.append_audit("rollback.apply", actor=actor, outcome="completed", permission="rollback_admin", request={"reason": reason, "target": preview["target"].get("path"), "items": [row["name"] for row in restored], "pre_backup": str(pre_backup)}, status=200)
        return result
