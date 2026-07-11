"""Global singleton TUI process lifecycle and control lease state."""
from __future__ import annotations

import os
import pty
import select
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from backend.v2.services.proxy_cli import ProxyTuiAudit


@dataclass
class TuiControlLease:
    holder: str = ""
    acquired_at: float = 0.0

    def to_dict(self) -> dict[str, float | str | bool]:
        return {
            "holder": self.holder,
            "acquired_at": self.acquired_at,
            "active": bool(self.holder),
        }


class GlobalTuiSession:
    """Own one proxy TUI PTY process for all React Console clients."""

    def __init__(self, command: list[str] | None = None, audit: ProxyTuiAudit | None = None) -> None:
        default_command = [str(Path(__file__).resolve().parents[3] / "matts-proxy-tui"), "--interactive"]
        self.command = command or default_command
        self.audit = audit or ProxyTuiAudit()
        self._lock = threading.RLock()
        self._lease = TuiControlLease()
        self._master_fd: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._started_at = 0.0

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "running": self._process is not None and self._process.poll() is None,
                "pid": self._process.pid if self._process else None,
                "started_at": self._started_at,
                "command": self.command,
                "lease": self._lease.to_dict(),
            }

    def ensure_started(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None and self._master_fd is not None:
                return
            master_fd, slave_fd = pty.openpty()
            self._process = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
            )
            os.close(slave_fd)
            self._master_fd = master_fd
            self._started_at = time.time()
            self.audit.append("tui.started", {"pid": self._process.pid, "command": self.command})

    def restart(self) -> dict[str, object]:
        with self._lock:
            self.stop()
            self.ensure_started()
            self.audit.append("tui.restarted", {"pid": self._process.pid if self._process else None})
            return self.status()

    def stop(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            if self._master_fd is not None:
                try:
                    os.close(self._master_fd)
                except OSError:
                    pass
            self._master_fd = None
            self._process = None
            self._lease = TuiControlLease()

    def acquire_control(self, client_id: str, *, force: bool = False) -> dict[str, object]:
        with self._lock:
            if not client_id:
                self.audit.append("tui.control_denied", {"client_id": client_id, "reason": "missing_client_id", "force": force})
                return self._lease.to_dict()
            if not self._lease.holder or self._lease.holder == client_id or force:
                previous = self._lease.holder
                self._lease = TuiControlLease(holder=client_id, acquired_at=time.time())
                self.audit.append("tui.control_acquired", {"client_id": client_id, "previous": previous, "force": force})
            elif self._lease.holder != client_id:
                self.audit.append("tui.control_denied", {"client_id": client_id, "holder": self._lease.holder, "reason": "lease_held", "force": force})
            return self._lease.to_dict()

    def release_control(self, client_id: str, *, force: bool = False) -> dict[str, object]:
        with self._lock:
            if self._lease.holder == client_id or force:
                previous = self._lease.holder
                self._lease = TuiControlLease()
                self.audit.append("tui.control_released", {"client_id": client_id, "previous": previous, "force": force})
            elif client_id:
                self.audit.append("tui.release_denied", {"client_id": client_id, "holder": self._lease.holder, "reason": "not_holder"})
            return self._lease.to_dict()

    def can_write(self, client_id: str) -> bool:
        with self._lock:
            return bool(client_id and self._lease.holder == client_id)

    def write(self, client_id: str, data: bytes) -> bool:
        with self._lock:
            if not self.can_write(client_id):
                self.audit.append("tui.write_denied", {"client_id": client_id, "holder": self._lease.holder, "reason": "control_lease_required"})
                return False
        self.ensure_started()
        with self._lock:
            if not self.can_write(client_id) or self._master_fd is None:
                self.audit.append("tui.write_denied", {"client_id": client_id, "holder": self._lease.holder, "reason": "session_not_ready"})
                return False
            os.write(self._master_fd, data)
            return True

    def read_available(self, timeout: float = 0.05, size: int = 4096) -> bytes:
        self.ensure_started()
        with self._lock:
            fd = self._master_fd
        if fd is None:
            return b""
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            return b""
        try:
            return os.read(fd, size)
        except OSError:
            return b""
