"""Manifest-based plugin discovery for console extension points."""
import json
from pathlib import Path


DEFAULT_EXTENSION_POINTS = [
    "console.nav",
    "console.panel",
    "create.prompt_action",
    "code.session_action",
    "model.metadata_enricher",
    "dedicated.lifecycle_hook",
    "reporting.exporter",
]


class PluginRegistryService:
    """Load plugin manifests without executing third-party code."""

    def __init__(self, config, root_dir):
        self.config = config or {}
        self.root_dir = Path(root_dir)

    def enabled(self):
        return bool(self.config.get("enabled", True))

    def extension_points(self):
        configured = self.config.get("extension_points")
        if isinstance(configured, list) and configured:
            return [str(item) for item in configured]
        return list(DEFAULT_EXTENSION_POINTS)

    def directories(self):
        rows = self.config.get("directories")
        if not isinstance(rows, list) or not rows:
            rows = ["plugins"]
        result = []
        for item in rows:
            path = Path(str(item))
            result.append(path if path.is_absolute() else self.root_dir / path)
        return result

    def manifest_files(self):
        files = []
        for directory in self.directories():
            if directory.is_file() and directory.suffix == ".json":
                files.append(directory)
            elif directory.exists():
                files.extend(sorted(directory.glob("*.json")))
        return files

    def load_manifest(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"id": path.stem, "enabled": False, "status": "invalid", "error": str(exc), "path": str(path)}
        plugin_id = str(data.get("id") or path.stem)
        extensions = data.get("extensions") if isinstance(data.get("extensions"), list) else []
        known = set(self.extension_points())
        invalid_extensions = [item for item in extensions if item.get("point") not in known]
        enabled = bool(data.get("enabled", True)) and not invalid_extensions and self.enabled()
        return {
            "id": plugin_id,
            "name": str(data.get("name") or plugin_id),
            "version": str(data.get("version") or "0.0.0"),
            "description": str(data.get("description") or ""),
            "author": str(data.get("author") or ""),
            "enabled": enabled,
            "status": "enabled" if enabled else ("disabled" if not invalid_extensions else "invalid"),
            "path": str(path),
            "extensions": extensions,
            "invalid_extensions": invalid_extensions,
            "config": data.get("config") if isinstance(data.get("config"), dict) else {},
        }

    def plugins(self):
        if not self.enabled():
            return []
        return [self.load_manifest(path) for path in self.manifest_files()]

    def payload(self):
        plugins = self.plugins()
        return {
            "enabled": self.enabled(),
            "directories": [str(path) for path in self.directories()],
            "extension_points": self.extension_points(),
            "plugins": plugins,
            "counts": {
                "total": len(plugins),
                "enabled": len([item for item in plugins if item.get("enabled")]),
                "invalid": len([item for item in plugins if item.get("status") == "invalid"]),
            },
        }
