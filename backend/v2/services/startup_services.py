"""Startup/boot service registry and control helpers."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from backend.v2.services.irc_bridge import IrcBridgeManager, atomic_write_json, bool_value, runtime_dir, tmux_tmpdir


SYSTEMD_UNITS = {
    "proxy": "matts-value-set-proxy.service",
    "console": "matts-console.service",
}
SYSTEMD_ACTIONS = {"start", "stop", "restart", "enable", "disable", "is-active", "is-enabled", "status"}
CORE_CONFIRM_ACTIONS = {"stop", "restart"}


def command_process_status(executable_name: str, required_args: set[str] | None = None, proc_root: Path = Path("/proc")) -> dict[str, Any]:
    required = required_args or set()
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return {"running": False, "source": "process_scan"}
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
        if not parts:
            continue
        has_executable = any(Path(part).name == executable_name for part in parts)
        if has_executable and required.issubset(set(parts)):
            return {"running": True, "pid": int(entry.name), "command": parts, "source": "process_scan"}
    return {"running": False, "source": "process_scan"}


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


class StartupConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get("MATTS_STARTUP_CONFIG_FILE", runtime_dir() / "startup-services.json"))

    def defaults(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "services": {
                "proxy": {"enabled": True},
                "console": {"enabled": True},
                "irc-bridge": {"enabled": True},
                "proxy-tui": {"enabled": True},
            },
        }

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        defaults = self.defaults()
        data = {**defaults, **(payload or {})}
        services = data.get("services") if isinstance(data.get("services"), dict) else {}
        merged: dict[str, dict[str, Any]] = {}
        for service_id, default_row in defaults["services"].items():
            row = services.get(service_id) if isinstance(services.get(service_id), dict) else {}
            merged[service_id] = {**default_row, **row, "enabled": bool_value(row.get("enabled"), bool(default_row.get("enabled")))}
        data["services"] = merged
        data["schema_version"] = 1
        return data

    def load(self) -> dict[str, Any]:
        return self.normalize(load_json(self.path, self.defaults()))

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        services = current.get("services") if isinstance(current.get("services"), dict) else {}
        incoming = payload.get("services") if isinstance(payload.get("services"), dict) else {}
        merged = {**current, **payload, "services": {**services, **incoming}}
        normalized = self.normalize(merged)
        atomic_write_json(self.path, normalized)
        return normalized


class SystemdController:
    def __init__(self, helper: str | None = None) -> None:
        self.helper = helper or os.environ.get("MATTS_STARTUP_HELPER", "/usr/bin/matts-startup-helper")

    def direct_systemctl(self, action: str, unit: str) -> tuple[int, str, str]:
        try:
            result = subprocess.run(["systemctl", action, unit], text=True, capture_output=True, check=False)
        except FileNotFoundError:
            return 127, "", "systemctl is not installed"
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def privileged(self, action: str, unit: str) -> tuple[int, str, str]:
        if os.geteuid() == 0:
            return self.direct_systemctl(action, unit)
        command = ["sudo", "-n", self.helper, action, unit]
        try:
            result = subprocess.run(command, text=True, capture_output=True, check=False)
        except FileNotFoundError:
            return 127, "", "sudo or startup helper is not installed"
        return result.returncode, result.stdout.strip(), result.stderr.strip()

    def run(self, action: str, unit: str) -> dict[str, Any]:
        if action not in SYSTEMD_ACTIONS:
            return {"ok": False, "error": f"unsupported systemd action: {action}"}
        if unit not in SYSTEMD_UNITS.values():
            return {"ok": False, "error": f"unit is not allowlisted: {unit}"}
        if action in {"start", "stop", "restart", "enable", "disable"}:
            code, out, err = self.privileged(action, unit)
        else:
            code, out, err = self.direct_systemctl(action, unit)
        return {"ok": code == 0, "code": code, "stdout": out, "stderr": err, "action": action, "unit": unit}

    def status(self, unit: str) -> dict[str, Any]:
        active = self.run("is-active", unit)
        enabled = self.run("is-enabled", unit)
        try:
            show = subprocess.run(["systemctl", "show", unit, "--property=MainPID", "--value"], text=True, capture_output=True, check=False)
            pid_code, pid_out, pid_err = show.returncode, show.stdout.strip(), show.stderr.strip()
        except FileNotFoundError:
            pid_code, pid_out, pid_err = 127, "", "systemctl is not installed"
        active_state = str(active.get("stdout") or "unavailable")
        enabled_state = str(enabled.get("stdout") or "unavailable")
        return {
            "unit": unit,
            "active_state": active_state,
            "enabled_state": enabled_state,
            "running": active_state == "active",
            "boot_enabled": enabled_state in {"enabled", "enabled-runtime", "static"},
            "pid": int(pid_out) if str(pid_out).isdigit() and int(pid_out) > 0 else None,
            "errors": [item for item in (active.get("stderr"), enabled.get("stderr"), pid_err if pid_code else "") if item],
        }


class StartupServiceManager:
    def __init__(
        self,
        store: StartupConfigStore | None = None,
        systemd: SystemdController | None = None,
        irc: IrcBridgeManager | None = None,
    ) -> None:
        self.store = store or StartupConfigStore()
        self.systemd = systemd or SystemdController()
        self.irc = irc or IrcBridgeManager()

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "proxy",
                "label": "Proxy Server",
                "kind": "systemd",
                "unit": SYSTEMD_UNITS["proxy"],
                "local_port": 18081,
                "critical": True,
                "description": "Anthropic-compatible local proxy.",
            },
            {
                "id": "console",
                "label": "V2 Console",
                "kind": "systemd",
                "unit": SYSTEMD_UNITS["console"],
                "local_port": 18182,
                "critical": True,
                "description": "React/FastAPI management console.",
            },
            {
                "id": "irc-bridge",
                "label": "IRC LLM Bridge",
                "kind": "tmux",
                "session_name": self.irc.config().get("session_name"),
                "critical": False,
                "description": "Remote IRC chat bridge for routable text LLMs.",
            },
            {
                "id": "proxy-tui",
                "label": "Proxy TUI",
                "kind": "console-tui",
                "critical": False,
                "description": "Embedded proxy TUI process served through the V2 console.",
            },
        ]

    def config(self) -> dict[str, Any]:
        return self.store.load()

    def service_config(self, service_id: str) -> dict[str, Any]:
        config = self.config()
        services = config.get("services") if isinstance(config.get("services"), dict) else {}
        return services.get(service_id) if isinstance(services.get(service_id), dict) else {"enabled": False}

    def status_payload(self) -> dict[str, Any]:
        config = self.config()
        rows = [self.service_payload(definition, config) for definition in self.definitions()]
        return {
            "generated_at": time.time(),
            "config": config,
            "services": rows,
            "summary": {
                "services": len(rows),
                "boot_enabled": len([row for row in rows if row.get("boot_enabled")]),
                "running": len([row for row in rows if row.get("running")]),
                "errors": sum(len(row.get("errors") or []) for row in rows),
            },
            "tmux_tmpdir": str(tmux_tmpdir()),
        }

    def service_payload(self, definition: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        service_id = str(definition["id"])
        service_config = (config.get("services") or {}).get(service_id) if isinstance(config.get("services"), dict) else {}
        boot_enabled = bool_value((service_config or {}).get("enabled"), True)
        status: dict[str, Any]
        if definition["kind"] == "systemd":
            status = self.systemd.status(str(definition["unit"]))
            local_status = self.local_process_status(definition)
            status["local"] = local_status
            if not status.get("running") and local_status.get("running"):
                status["running"] = True
                status["active_state"] = "local"
                status["errors"] = []
        elif definition["kind"] == "tmux":
            irc_status = self.irc.status(include_models=False)
            status = {
                "running": bool((irc_status.get("tmux") or {}).get("running")),
                "listening": bool(irc_status.get("listening")),
                "session_name": (irc_status.get("tmux") or {}).get("session_name"),
                "tail": (irc_status.get("tmux") or {}).get("tail", ""),
                "errors": [],
            }
        else:
            status = self.tui_status()
        errors = status.get("errors") if isinstance(status.get("errors"), list) else []
        return {
            **definition,
            "boot_enabled": boot_enabled,
            "configured_enabled": boot_enabled,
            "running": bool(status.get("running")),
            "status": status,
            "errors": errors,
        }

    def local_process_status(self, definition: dict[str, Any]) -> dict[str, Any]:
        port = int(definition.get("local_port") or 0)
        if port <= 0:
            return {"running": False}
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return {"running": True, "port": port, "host": "127.0.0.1"}
        except OSError as exc:
            return {"running": False, "port": port, "host": "127.0.0.1", "error": str(exc)}

    def tui_status(self) -> dict[str, Any]:
        try:
            from backend.v2.api.tui import tui_session

            status = {**tui_session.status(), "errors": []}
            if status.get("running"):
                return status
            external = command_process_status("matts-proxy-tui", {"--interactive"})
            if external.get("running"):
                return {**status, **external, "errors": [], "managed_by": "console_process"}
            return status
        except Exception as exc:
            return {"running": False, "errors": [str(exc)]}

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload or {}
        next_config = self.store.save(payload)
        services = payload.get("services") if isinstance(payload.get("services"), dict) else {}
        results: dict[str, Any] = {}
        for service_id, row in services.items():
            if service_id in SYSTEMD_UNITS and isinstance(row, dict) and "enabled" in row:
                action = "enable" if bool_value(row.get("enabled")) else "disable"
                results[str(service_id)] = self.systemd.run(action, SYSTEMD_UNITS[str(service_id)])
        return {"config": next_config, "results": results, "payload": self.status_payload()}

    def require_confirmation(self, service_id: str, action: str, payload: dict[str, Any]) -> None:
        definition = next((row for row in self.definitions() if row["id"] == service_id), None)
        if not definition or not definition.get("critical") or action not in CORE_CONFIRM_ACTIONS:
            return
        confirm = str((payload or {}).get("confirm") or "")
        accepted = {service_id, f"{action}:{service_id}", "confirm"}
        if confirm not in accepted:
            raise ValueError(f"{action} for {service_id} requires confirmation")

    def action(self, service_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        self.require_confirmation(service_id, action, payload)
        if action not in {"start", "stop", "restart", "apply"}:
            raise ValueError("unsupported service action")
        if service_id in SYSTEMD_UNITS:
            actual = action
            if action == "apply":
                actual = "start" if bool_value(self.service_config(service_id).get("enabled"), True) else "stop"
            result = self.systemd.run(actual, SYSTEMD_UNITS[service_id])
        elif service_id == "irc-bridge":
            if action == "start" or action == "apply":
                result = self.irc.ensure_tmux()
            elif action == "stop":
                result = self.irc.stop()
            else:
                result = self.irc.restart()
        elif service_id == "proxy-tui":
            result = self.tui_action(action)
        else:
            raise ValueError("unknown service")
        return {"service_id": service_id, "action": action, "result": result, "payload": self.status_payload()}

    def tui_action(self, action: str) -> dict[str, Any]:
        try:
            from backend.v2.api.tui import tui_session

            if action in {"start", "apply"}:
                if bool_value(self.service_config("proxy-tui").get("enabled"), True):
                    tui_session.ensure_started()
                return {"ok": True, "status": tui_session.status()}
            if action == "stop":
                tui_session.stop()
                return {"ok": True, "status": tui_session.status()}
            if action == "restart":
                return {"ok": True, "status": tui_session.restart()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "unsupported tui action"}

    def ensure_proxy_boot_sidecars(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        if bool_value(self.service_config("irc-bridge").get("enabled"), True):
            results["irc-bridge"] = self.irc.ensure_tmux()
        return {"ok": all(bool(row.get("ok")) for row in results.values()) if results else True, "results": results}

    def ensure_console_runtime(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        if bool_value(self.service_config("proxy-tui").get("enabled"), True):
            results["proxy-tui"] = self.tui_action("start")
        return {"ok": all(bool(row.get("ok")) for row in results.values()) if results else True, "results": results}


def ensure_proxy_boot_sidecars() -> dict[str, Any]:
    return StartupServiceManager().ensure_proxy_boot_sidecars()


def ensure_console_runtime() -> dict[str, Any]:
    return StartupServiceManager().ensure_console_runtime()
