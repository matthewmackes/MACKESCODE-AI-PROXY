"""FastAPI WebSocket bridge for browser attachments to tmux sessions."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios
from typing import Optional

from backend.v2.api.auth import capability_service, identity_from_values

try:
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover - permits syntax checks before v2 deps.
    APIRouter = None  # type: ignore[assignment]
    WebSocket = object  # type: ignore[assignment]
    WebSocketDisconnect = Exception  # type: ignore[assignment]


router = APIRouter(tags=["tmux-websocket"]) if APIRouter else None


def terminal_dimension(value: object, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return min(max(parsed, minimum), maximum)


def tmux_target(value: object, default: str = "matts-claude") -> str:
    raw = str(value or default).strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_:.")
    return cleaned[:140] if cleaned else default


def tmux_cmd(args: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(["tmux", *args], text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return 127, "", "tmux is not installed"
    return result.returncode, result.stdout, result.stderr


def tmux_has_session(name: str) -> bool:
    return tmux_cmd(["has-session", "-t", name])[0] == 0


def set_pty_size(fd: int, rows: int, cols: int) -> None:
    rows = terminal_dimension(rows, 40, 8, 200)
    cols = terminal_dimension(cols, 120, 20, 400)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def spawn_tmux_attach(name: str, rows: int, cols: int) -> tuple[subprocess.Popen[bytes], int]:
    master_fd, slave_fd = pty.openpty()
    set_pty_size(master_fd, rows, cols)
    env = dict(os.environ)
    env["TERM"] = env.get("TERM") or "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["FORCE_COLOR"] = env.get("FORCE_COLOR") or "3"
    env["CLICOLOR"] = env.get("CLICOLOR") or "1"
    env["CLICOLOR_FORCE"] = env.get("CLICOLOR_FORCE") or "1"
    env.pop("NO_COLOR", None)
    try:
        process = subprocess.Popen(
            ["tmux", "-u", "-T", "256,RGB", "attach-session", "-t", name],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
            preexec_fn=os.setsid,
        )
    finally:
        os.close(slave_fd)
    return process, master_fd


async def close_process(process: subprocess.Popen[bytes], fd: int) -> None:
    try:
        os.killpg(process.pid, signal.SIGHUP)
    except OSError:
        try:
            process.terminate()
        except OSError:
            pass
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        await asyncio.to_thread(process.wait, 1)
    except Exception:
        try:
            process.kill()
        except OSError:
            pass


async def send_tmux_output(websocket: WebSocket, fd: int) -> None:
    while True:
        try:
            data = await asyncio.to_thread(os.read, fd, 4096)
        except OSError:
            return
        if not data:
            return
        await websocket.send_text(data.decode("utf-8", errors="replace"))


def maybe_resize(text: str, fd: int, current_rows: int, current_cols: int) -> tuple[bool, int, int]:
    if not text.startswith("{"):
        return False, current_rows, current_cols
    try:
        payload = json.loads(text)
    except ValueError:
        return False, current_rows, current_cols
    resize = payload.get("resize") if isinstance(payload, dict) else None
    if not isinstance(resize, dict):
        return False, current_rows, current_cols
    rows = terminal_dimension(resize.get("rows"), current_rows, 8, 200)
    cols = terminal_dimension(resize.get("cols"), current_cols, 20, 400)
    set_pty_size(fd, rows, cols)
    return True, rows, cols


async def receive_browser_input(websocket: WebSocket, fd: int, rows: int, cols: int) -> None:
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return
        if message.get("bytes") is not None:
            os.write(fd, message["bytes"] or b"")
            continue
        text = message.get("text")
        if text is None:
            continue
        handled, rows, cols = maybe_resize(str(text), fd, rows, cols)
        if not handled:
            os.write(fd, str(text).encode("utf-8", errors="replace"))


if router:

    @router.websocket("/ws/tmux")
    async def websocket_tmux(websocket: WebSocket) -> None:
        await websocket.accept()
        token = websocket.query_params.get("token") or ""
        headers = {
            "authorization": websocket.headers.get("authorization") or "",
            "x-matts-console-token": websocket.headers.get("x-matts-console-token") or "",
        }
        identity = identity_from_values(str(websocket.url), headers, token)
        decision = capability_service.decide(identity, "tmux.control")
        if not decision.allowed:
            await websocket.send_text(json.dumps({"type": "denied", "decision": decision.to_dict()}))
            await websocket.close(code=4403, reason="permission denied")
            return

        raw_name = websocket.query_params.get("session") or websocket.query_params.get("name") or "matts-claude"
        name = tmux_target(raw_name)
        rows = terminal_dimension(websocket.query_params.get("rows"), 40, 8, 200)
        cols = terminal_dimension(websocket.query_params.get("cols"), 120, 20, 400)
        if not tmux_has_session(name):
            await websocket.send_text(json.dumps({"type": "error", "code": "tmux_session_not_found", "session": name}))
            await websocket.close(code=4404, reason="session not found")
            return

        try:
            process, fd = await asyncio.to_thread(spawn_tmux_attach, name, rows, cols)
        except OSError as exc:
            await websocket.send_text(json.dumps({"type": "error", "code": "tmux_attach_failed", "message": str(exc), "session": name}))
            await websocket.close(code=1011, reason="attach failed")
            return

        output_task = asyncio.create_task(send_tmux_output(websocket, fd))
        input_task = asyncio.create_task(receive_browser_input(websocket, fd, rows, cols))
        try:
            done, pending = await asyncio.wait({output_task, input_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
            for task in pending:
                task.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            output_task.cancel()
            input_task.cancel()
            await close_process(process, fd)
