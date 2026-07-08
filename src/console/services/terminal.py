"""Lightweight PTY terminal session lifecycle helpers."""
import fcntl
import os
import pty
import select
import signal
import time
import uuid
from http import HTTPStatus
from pathlib import Path


class TerminalSession:
    """A single Claude launcher process attached to a PTY."""

    def __init__(
        self,
        model,
        project_dir,
        extra_args,
        script_dir,
        *,
        fork=pty.fork,
        fcntl_func=fcntl.fcntl,
        select_func=select.select,
        read_func=os.read,
        write_func=os.write,
        waitpid_func=os.waitpid,
        kill_func=os.kill,
        close_func=os.close,
        chdir_func=os.chdir,
        execvpe_func=os.execvpe,
        environ=None,
        clock=time.time,
        session_id=None,
    ):
        self.id = session_id or uuid.uuid4().hex
        self.created_at = clock()
        self.output = ""
        self.closed = False
        self.select_func = select_func
        self.read_func = read_func
        self.write_func = write_func
        self.waitpid_func = waitpid_func
        self.kill_func = kill_func
        self.close_func = close_func
        self.fd = None
        self.pid = None

        root = script_dir() if callable(script_dir) else script_dir
        cmd = [str(Path(root) / "claude-DO.sh"), "--model", model]
        if project_dir:
            cmd += ["--project-dir", project_dir]
        if extra_args:
            cmd += list(extra_args)
        env = dict(environ if environ is not None else os.environ)
        env["TERM"] = env.get("TERM", "xterm-256color")
        self.pid, self.fd = fork()
        if self.pid == 0:
            chdir_func(project_dir or str(root))
            execvpe_func(cmd[0], cmd, env)
        flags = fcntl_func(self.fd, fcntl.F_GETFL)
        fcntl_func(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def read(self):
        if self.closed:
            return {"id": self.id, "output": "", "closed": True}
        chunks = []
        while True:
            ready, _, _ = self.select_func([self.fd], [], [], 0)
            if not ready:
                break
            try:
                data = self.read_func(self.fd, 4096)
            except OSError:
                self.closed = True
                break
            if not data:
                self.closed = True
                break
            chunks.append(data.decode("utf-8", errors="replace"))
        text = "".join(chunks)
        self.output = (self.output + text)[-100000:]
        try:
            ended, _ = self.waitpid_func(self.pid, os.WNOHANG)
            if ended:
                self.closed = True
        except ChildProcessError:
            self.closed = True
        return {"id": self.id, "output": text, "closed": self.closed}

    def write(self, text):
        if not self.closed:
            self.write_func(self.fd, str(text or "").encode("utf-8"))

    def stop(self):
        if not self.closed:
            try:
                self.kill_func(self.pid, signal.SIGTERM)
            except OSError:
                pass
            self.closed = True
        try:
            self.close_func(self.fd)
        except OSError:
            pass


class TerminalSessionService:
    """Owns terminal start/read/write/stop API behavior."""

    def __init__(
        self,
        script_dir,
        text_models,
        default_text_model,
        sessions=None,
        session_factory=None,
    ):
        self.script_dir = script_dir
        self.text_models = text_models
        self.default_text_model = default_text_model
        self.sessions = sessions if sessions is not None else {}
        self.session_factory = session_factory or self._new_session

    def active_text_models(self):
        return list(self.text_models() if callable(self.text_models) else self.text_models)

    def _new_session(self, model, project_dir, extra_args):
        return TerminalSession(model, project_dir, extra_args, self.script_dir)

    def start(self, data):
        model = data.get("model") if data.get("model") in self.active_text_models() else self.default_text_model()
        root = self.script_dir() if callable(self.script_dir) else self.script_dir
        project_dir = data.get("project_dir") or str(root)
        if not Path(project_dir).is_dir():
            return HTTPStatus.BAD_REQUEST, {"error": "project directory does not exist"}
        extra_args = [part for part in str(data.get("extra_args") or "").split() if part]
        session = self.session_factory(model, project_dir, extra_args)
        self.sessions[session.id] = session
        return HTTPStatus.OK, {"id": session.id}

    def read(self, session_id):
        session = self.sessions.get(session_id)
        if not session:
            return HTTPStatus.NOT_FOUND, {"error": "terminal not found"}
        return HTTPStatus.OK, session.read()

    def write(self, session_id, text):
        session = self.sessions.get(session_id)
        if not session:
            return HTTPStatus.NOT_FOUND, {"error": "terminal not found"}
        session.write(text or "")
        return HTTPStatus.OK, {"ok": True}

    def stop(self, session_id):
        session = self.sessions.pop(session_id, None)
        if session:
            session.stop()
        return HTTPStatus.OK, {"ok": True}

    def stop_all(self):
        for session in list(self.sessions.values()):
            session.stop()
        self.sessions.clear()
