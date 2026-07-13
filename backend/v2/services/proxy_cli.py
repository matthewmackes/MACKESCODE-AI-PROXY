"""Reusable proxy CLI operations for the v2 API and TUI."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_CONFIG_FILE = PROJECT_DIR / "config" / "models.json"
DEFAULT_MODEL_ACCESS_STATE_FILE = Path.home() / ".cache" / "matts-value-set" / "studio" / "model-access-state.json"
DEFAULT_COST_FILE = Path.home() / ".cache" / "matts-value-set" / "usage.jsonl"
DEFAULT_BUDGET_FILE = Path.home() / ".cache" / "matts-value-set" / "budgets.json"
DEFAULT_LOG_FILE = Path.home() / ".cache" / "matts-value-set" / "proxy.jsonl"


@dataclass(frozen=True)
class ProxyCommandResult:
    """Result object shared by API and TUI command surfaces."""

    ok: bool
    command: str
    status: str
    data: dict[str, Any]
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "status": self.status,
            "message": self.message,
            "data": self.data,
        }


class ProxyCliService:
    """Small command facade over the current proxy runtime files and HTTP API."""

    def __init__(
        self,
        *,
        proxy_host: str | None = None,
        proxy_port: int | None = None,
        model_config_file: str | os.PathLike[str] | None = None,
        model_access_state_file: str | os.PathLike[str] | None = None,
        cost_file: str | os.PathLike[str] | None = None,
        budget_file: str | os.PathLike[str] | None = None,
        log_file: str | os.PathLike[str] | None = None,
    ) -> None:
        self.proxy_host = proxy_host or os.environ.get("MATTS_VALUE_SET_PROXY_HOST", "127.0.0.1")
        self.proxy_port = int(proxy_port or os.environ.get("MATTS_VALUE_SET_PROXY_PORT", "18081"))
        self.model_config_file = Path(model_config_file or os.environ.get("MATTS_MODEL_CONFIG_FILE", DEFAULT_MODEL_CONFIG_FILE))
        self.model_access_state_file = Path(model_access_state_file or os.environ.get("MATTS_MODEL_ACCESS_STATE_FILE", DEFAULT_MODEL_ACCESS_STATE_FILE))
        self.cost_file = Path(cost_file or os.environ.get("MATTS_VALUE_SET_COST_FILE", DEFAULT_COST_FILE))
        self.budget_file = Path(budget_file or os.environ.get("MATTS_VALUE_SET_BUDGET_FILE", DEFAULT_BUDGET_FILE))
        self.log_file = Path(log_file or os.environ.get("MATTS_VALUE_SET_LOG_FILE", DEFAULT_LOG_FILE))

    @property
    def base_url(self) -> str:
        return "http://%s:%d" % (self.proxy_host, self.proxy_port)

    def is_listening(self, timeout: float = 0.2) -> bool:
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            sock.connect((self.proxy_host, self.proxy_port))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    def status(self) -> ProxyCommandResult:
        listening = self.is_listening()
        capabilities = self._get_json("/v1/claude-do/capabilities") if listening else {}
        return ProxyCommandResult(
            ok=listening,
            command="status",
            status="running" if listening else "stopped",
            message="Proxy is listening." if listening else "Proxy is not listening.",
            data={
                "proxy_url": self.base_url,
                "listening": listening,
                "capabilities": capabilities,
                "model_config_file": str(self.model_config_file),
                "cost_file": str(self.cost_file),
                "budget_file": str(self.budget_file),
                "log_file": str(self.log_file),
            },
        )

    def list_models(self) -> ProxyCommandResult:
        models = self._load_models()
        return ProxyCommandResult(
            ok=bool(models),
            command="models",
            status="ok" if models else "empty",
            message="%d route-enabled models found." % len(models),
            data={"models": models, "model_config_file": str(self.model_config_file)},
        )

    def costs(self, limit: int = 200) -> ProxyCommandResult:
        records = self._tail_jsonl(self.cost_file, limit)
        total = 0.0
        for record in records:
            cost = record.get("cost") if isinstance(record.get("cost"), dict) else {}
            total += float(cost.get("total_cost_usd") or record.get("cost_usd") or 0.0)
        return ProxyCommandResult(
            ok=True,
            command="costs",
            status="ok",
            message="Loaded %d recent cost records." % len(records),
            data={"records": records, "recent_total_usd": round(total, 8), "cost_file": str(self.cost_file)},
        )

    def budget(self) -> ProxyCommandResult:
        data = self._read_json(self.budget_file, default={})
        return ProxyCommandResult(
            ok=True,
            command="budget",
            status="ok" if data else "missing",
            message="Budget file loaded." if data else "Budget file is missing or empty.",
            data={"budget": data, "budget_file": str(self.budget_file)},
        )

    def logs(self, limit: int = 80) -> ProxyCommandResult:
        records = self._tail_jsonl(self.log_file, limit)
        return ProxyCommandResult(
            ok=True,
            command="logs",
            status="ok",
            message="Loaded %d recent proxy log records." % len(records),
            data={"records": records, "log_file": str(self.log_file)},
        )

    def doctor(self) -> ProxyCommandResult:
        checks = {
            "proxy_status": self.status().to_dict(),
            "models": self.list_models().to_dict(),
            "budget": self.budget().to_dict(),
            "costs": self.costs(limit=20).to_dict(),
        }
        ok = bool(checks["proxy_status"]["ok"] and checks["models"]["ok"])
        return ProxyCommandResult(
            ok=ok,
            command="doctor",
            status="ok" if ok else "needs_attention",
            message="Proxy doctor passed." if ok else "Proxy doctor found issues.",
            data={"checks": checks},
        )

    def restart(self) -> ProxyCommandResult:
        return self._run_launcher("restart", ["--restart", "--status"], timeout=20)

    def test_models(self) -> ProxyCommandResult:
        return self._run_launcher("test-models", ["--test-models"], timeout=300)

    def _run_launcher(self, command: str, args: list[str], timeout: int) -> ProxyCommandResult:
        launcher = PROJECT_DIR / "claude-DO.sh"
        if not launcher.exists():
            return ProxyCommandResult(
                ok=False,
                command=command,
                status="missing_launcher",
                message="claude-DO.sh was not found.",
                data={"launcher": str(launcher)},
            )
        try:
            completed = subprocess.run(
                [str(launcher)] + args,
                cwd=str(PROJECT_DIR),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return ProxyCommandResult(
                ok=False,
                command=command,
                status="timeout",
                message="%s timed out." % command,
                data={"stdout": exc.stdout or "", "stderr": exc.stderr or "", "timeout": timeout},
            )
        return ProxyCommandResult(
            ok=completed.returncode == 0,
            command=command,
            status="ok" if completed.returncode == 0 else "failed",
            message="%s completed with exit code %d." % (command, completed.returncode),
            data={
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )

    def _get_json(self, path: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=1.5) as resp:
                data = json.load(resp)
            return data if isinstance(data, dict) else {"value": data}
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            return {"error": str(exc)}

    def _load_models(self) -> list[dict[str, Any]]:
        data = self._read_json(self.model_config_file, default={})
        rows = data.get("models") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        rows = self._apply_access_state(rows)
        return [row for row in rows if isinstance(row, dict) and row.get("id") and self._route_enabled(row)]

    def _apply_access_state(self, rows: list[Any]) -> list[dict[str, Any]]:
        state = self._read_json(self.model_access_state_file, default={})
        state_models = state.get("models") if isinstance(state, dict) else {}
        if not isinstance(state_models, dict):
            state_models = {}
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            overlay = state_models.get(str(item.get("id") or ""))
            if isinstance(overlay, dict):
                if overlay.get("access_status"):
                    item["access_status"] = str(overlay.get("access_status"))
                if overlay.get("last_error"):
                    item["last_error"] = str(overlay.get("last_error"))
            out.append(item)
        return out

    def _route_enabled(self, model: dict[str, Any]) -> bool:
        if model.get("enabled") is False:
            return False
        if model.get("serverless") and model.get("type", "text") == "text":
            return model.get("access_status") == "ok"
        return True

    def _read_json(self, path: Path, *, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _tail_jsonl(self, path: Path, limit: int) -> list[dict[str, Any]]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        records: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records


class ProxyTuiAudit:
    """Append-only audit helper for TUI control events."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        default_path = Path.home() / ".cache" / "matts-value-set" / "studio" / "tui-audit.jsonl"
        self.path = Path(path or os.environ.get("MATTS_TUI_AUDIT_FILE", default_path))

    def append(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {
            "ts": time.time(),
            "action": action,
            "payload": payload or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        return event
