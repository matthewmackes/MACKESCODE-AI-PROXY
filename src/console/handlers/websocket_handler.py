"""WebSocket handler for attaching a browser terminal to a tmux session."""
import fcntl
import json
import os
import pty
import select
import signal
from urllib.parse import parse_qs, urlparse


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
        cols = int((query.get("cols") or ["120"])[0] or 120)
        rows = int((query.get("rows") or ["40"])[0] or 40)
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
        try:
            while True:
                ready, _, _ = self.select_func([conn, fd], [], [], 0.05)
                if fd in ready:
                    try:
                        data = self.read_func(fd, 4096)
                    except OSError as exc:
                        self.print_func("tmux websocket pty read failed for %s: %r" % (name, exc), flush=True)
                        break
                    if not data:
                        self.print_func("tmux websocket pty eof for %s" % name, flush=True)
                        break
                    try:
                        self.websocket_send(conn, data.decode("utf-8", errors="replace"))
                    except OSError as exc:
                        self.print_func("tmux websocket send failed for %s: %r" % (name, exc), flush=True)
                        break
                if conn in ready:
                    try:
                        frame = self.websocket_read_frame(conn)
                    except OSError as exc:
                        self.print_func("tmux websocket client read failed for %s: %r" % (name, exc), flush=True)
                        break
                    if frame is None:
                        self.print_func("tmux websocket client closed for %s" % name, flush=True)
                        break
                    if isinstance(frame, dict):
                        continue
                    if frame.startswith("{"):
                        try:
                            message = json.loads(frame)
                            resize = message.get("resize")
                            if resize:
                                self.set_pty_size(fd, int(resize.get("rows") or rows), int(resize.get("cols") or cols))
                                continue
                        except ValueError:
                            pass
                    self.write_func(fd, frame.encode("utf-8", errors="replace"))
        finally:
            try:
                self.kill_func(pid, signal.SIGHUP)
            except OSError:
                pass
            try:
                self.close_func(fd)
            except OSError:
                pass
