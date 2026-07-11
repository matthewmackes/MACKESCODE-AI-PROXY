"""Shared runtime-state file repository primitives."""
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


class RuntimeStateRepository:
    """Small file-backed repository for local JSON and JSONL runtime state."""

    def __init__(self, path, name, schema_version=1, retention=None, redacted_keys=None, clock=None):
        self.path = path
        self.name = str(name)
        self.schema_version = int(schema_version)
        self.retention = retention or {}
        self.redacted_keys = {str(key).lower() for key in (redacted_keys or [])}
        self.clock = clock or time.time

    def file_path(self):
        path = self.path() if callable(self.path) else self.path
        return Path(path)

    @contextlib.contextmanager
    def file_lock(self, path=None):
        target = Path(path or self.file_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_path = target.with_name(target.name + ".lock")
        with lock_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def redact(self, value):
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                key_l = str(key).lower()
                if key_l in self.redacted_keys or any(part in key_l for part in self.redacted_keys):
                    clean[key] = "[redacted]"
                else:
                    clean[key] = self.redact(item)
            return clean
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def read_json(self, fallback=None, migrations=None):
        path = self.file_path()
        fallback = {} if fallback is None else fallback
        if not path.exists():
            return fallback
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fallback
        for migration in migrations or []:
            data = migration(data)
        return data

    def write_json(self, data, mode=0o600):
        path = self.file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.redact(data)
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        with self.file_lock(path):
            fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(tmp_name, mode)
                os.replace(tmp_name, path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        return payload

    def append_jsonl(self, record, mode=0o600):
        path = self.file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        clean = self.redact(record)
        with self.file_lock(path):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(clean, sort_keys=True) + "\n")
            path.chmod(mode)
        return clean

    def read_jsonl(self, limit=80, reverse=False, malformed="skip"):
        path = self.file_path()
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        if limit:
            lines = lines[-int(limit):]
        if reverse:
            lines = list(reversed(lines))
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                if malformed == "raw":
                    rows.append({"raw": line})
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def fingerprint(self):
        path = self.file_path()
        if not path.exists():
            return {"exists": False, "path": str(path), "sha256": "", "size_bytes": 0, "updated_at": 0}
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            stat = path.stat()
        except OSError:
            return {"exists": False, "path": str(path), "sha256": "", "size_bytes": 0, "updated_at": 0}
        return {"exists": True, "path": str(path), "sha256": digest.hexdigest(), "size_bytes": stat.st_size, "updated_at": stat.st_mtime}

    def backup_candidates(self):
        path = self.file_path()
        parent = path.parent
        if not parent.exists():
            return []
        patterns = [
            path.name + ".bak",
            path.name + ".backup",
            path.stem + "-backup*" + path.suffix,
            path.stem + "-archive*" + path.suffix + "*",
        ]
        rows = []
        seen = set()
        for pattern in patterns:
            for candidate in parent.glob(pattern):
                if candidate in seen:
                    continue
                seen.add(candidate)
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                rows.append({"path": str(candidate), "size_bytes": stat.st_size, "updated_at": stat.st_mtime})
        rows.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
        return rows

    def metadata(self):
        return {
            "name": self.name,
            "schema_version": self.schema_version,
            "path": str(self.file_path()),
            "retention": self.retention,
            "fingerprint": self.fingerprint(),
            "backups": self.backup_candidates(),
        }
