"""WebSocket handler for attaching a browser terminal to a tmux session."""
import fcntl
import json
import os
import pty
import select
import signal
from urllib.parse import parse_qs, urlparse


def _terminal_dimension(value, fallback, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(max(parsed, minimum), maximum)


class TmuxWebSocketHandler:
    """Bridge a WebSocket connection to `tmux attach-session` running in a PTY."""

    def __init__(
        self,
        *,
        authorized,
        tmux_target,
        tmux_cmd,
        websocket_accept_key,
        websocket_send,
        websocket_send_pong=None,
        websocket_read_frame,
        set_pty_size,
        fork_func=None,
        execvp_func=None,
        select_func=None,
        fcntl_func=None,
        read_func=None,
        write_func=None,
        kill_func=None,
        close_func=None,
        environ=None,
        print_func=None,
    ):
        self.authorized = authorized
        self.tmux_target = tmux_target
        self.tmux_cmd = tmux_cmd
        self.websocket_accept_key = websocket_accept_key
        self.websocket_send = websocket_send
        self.websocket_send_pong = websocket_send_pong or (lambda conn, payload=b"": None)
        self.websocket_read_frame = websocket_read_frame
        self.set_pty_size = set_pty_size
        self.fork_func = fork_func or pty.fork
        self.execvp_func = execvp_func or os.execvp
        self.select_func = select_func or select.select
        self.fcntl_func = fcntl_func or fcntl.fcntl
        self.read_func = read_func or os.read
        self.write_func = write_func or os.write
        self.kill_func = kill_func or os.kill
        self.close_func = close_func or os.close
        self.environ = environ if environ is not None else os.environ
        self.print_func = print_func or print

    def _send_status(self, request, status):
        request.send_response(status)
        request.end_headers()

    def handle(self, request):
        if not self.authorized():
            self._send_status(request, 401)
            return
        parsed = urlparse(request.path)
        query = parse_qs(parsed.query)
        name = self.tmux_target((query.get("name") or ["matts-claude"])[0])
        cols = _terminal_dimension((query.get("cols") or ["120"])[0], 120, 20, 400)
        rows = _terminal_dimension((query.get("rows") or ["40"])[0], 40, 8, 200)
        if self.tmux_cmd(["has-session", "-t", name], check=False)[0] != 0:
            self._send_status(request, 404)
            return
        key = request.headers.get("sec-websocket-key", "")
        if not key:
            self._send_status(request, 400)
            return
        request.send_response(101, "Switching Protocols")
        request.send_header("Upgrade", "websocket")
        request.send_header("Connection", "Upgrade")
        request.send_header("Sec-WebSocket-Accept", self.websocket_accept_key(key))
        request.end_headers()
        pid, fd = self.fork_func()
        if pid == 0:
            self.environ.setdefault("TERM", "xterm-256color")
            self.environ.setdefault("COLORTERM", "truecolor")
            self.execvp_func("tmux", ["tmux", "attach-session", "-t", name])
        self.set_pty_size(fd, rows, cols)
        conn = request.connection
        conn.setblocking(True)
        flags = self.fcntl_func(fd, fcntl.F_GETFL)
        self.fcntl_func(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        close_reason = "unknown"
        self.print_func("tmux websocket connected for %s rows=%s cols=%s" % (name, rows, cols), flush=True)
        try:
            while True:
                ready, _, _ = self.select_func([conn, fd], [], [], 0.05)
                if fd in ready:
                    try:
                        data = self.read_func(fd, 4096)
                    except OSError as exc:
                        self.print_func("tmux websocket pty read failed for %s: %r" % (name, exc), flush=True)
                        close_reason = "pty_read_failed"
                        break
                    if not data:
                        self.print_func("tmux websocket pty eof for %s" % name, flush=True)
                        close_reason = "pty_eof"
                        break
                    try:
                        self.websocket_send(conn, data.decode("utf-8", errors="replace"))
                    except OSError as exc:
                        self.print_func("tmux websocket send failed for %s: %r" % (name, exc), flush=True)
                        close_reason = "client_send_failed"
                        break
                if conn in ready:
                    try:
                        frame = self.websocket_read_frame(conn)
                    except OSError as exc:
                        self.print_func("tmux websocket client read failed for %s: %r" % (name, exc), flush=True)
                        close_reason = "client_read_failed"
                        break
                    if frame is None:
                        self.print_func("tmux websocket client closed for %s" % name, flush=True)
                        close_reason = "client_closed"
                        break
                    if isinstance(frame, dict):
                        if "ping" in frame:
                            self.websocket_send_pong(conn, frame.get("ping") or b"")
                        continue
                    if frame.startswith("{"):
                        try:
                            message = json.loads(frame)
                            resize = message.get("resize")
                            if resize:
                                rows = _terminal_dimension(resize.get("rows"), rows, 8, 200)
                                cols = _terminal_dimension(resize.get("cols"), cols, 20, 400)
                                self.set_pty_size(fd, rows, cols)
                                continue
                        except ValueError:
                            pass
                    self.write_func(fd, frame.encode("utf-8", errors="replace"))
        finally:
            self.print_func("tmux websocket disconnected for %s reason=%s" % (name, close_reason), flush=True)
            try:
                self.kill_func(pid, signal.SIGHUP)
            except OSError:
                pass
            try:
                self.close_func(fd)
            except OSError:
                pass
