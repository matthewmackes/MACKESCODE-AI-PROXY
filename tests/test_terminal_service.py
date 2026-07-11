import signal
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services.terminal import TerminalSession, TerminalSessionService


class FakeTerminalSession:
    def __init__(self, session_id="terminal-1"):
        self.id = session_id
        self.reads = 0
        self.writes = []
        self.stopped = False

    def read(self):
        self.reads += 1
        return {"id": self.id, "output": "hello", "closed": False}

    def write(self, text):
        self.writes.append(text)

    def stop(self):
        self.stopped = True


class TerminalSessionTests(unittest.TestCase):
    def test_terminal_session_reads_writes_and_stops_with_injected_os_calls(self):
        read_chunks = [b"hello", b""]
        writes = []
        killed = []
        closed = []
        fcntl_calls = []

        def select_func(reads, writes_, errors, timeout):
            return (reads if read_chunks else [], [], [])

        def read_func(fd, size):
            return read_chunks.pop(0)

        def fcntl_func(fd, op, value=None):
            fcntl_calls.append((fd, op, value))
            return 0

        session = TerminalSession(
            "model-a",
            "/project",
            ["--verbose"],
            script_dir=lambda: Path("/app"),
            fork=lambda: (123, 7),
            fcntl_func=fcntl_func,
            select_func=select_func,
            read_func=read_func,
            write_func=lambda fd, data: writes.append((fd, data)),
            waitpid_func=lambda pid, flags: (0, 0),
            kill_func=lambda pid, sig: killed.append((pid, sig)),
            close_func=lambda fd: closed.append(fd),
            environ={},
            clock=lambda: 1000,
            session_id="terminal-1",
        )

        payload = session.read()
        session.write("input")
        session.stop()

        self.assertEqual(session.created_at, 1000)
        self.assertEqual(payload, {"id": "terminal-1", "output": "hello", "closed": True})
        self.assertEqual(session.output, "hello")
        self.assertEqual(writes, [])
        self.assertEqual(killed, [])
        self.assertEqual(closed, [7])
        self.assertEqual(len(fcntl_calls), 2)

    def test_terminal_session_forces_color_environment_for_child(self):
        exec_calls = []

        def execvpe_func(command, args, env):
            exec_calls.append((command, args, env))
            raise RuntimeError("stop child branch")

        with self.assertRaises(RuntimeError):
            TerminalSession(
                "model-a",
                "/project",
                [],
                script_dir=lambda: Path("/app"),
                fork=lambda: (0, 7),
                chdir_func=lambda path: None,
                execvpe_func=execvpe_func,
                environ={"NO_COLOR": "1", "TERM": ""},
                session_id="terminal-color",
            )

        env = exec_calls[0][2]
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")
        self.assertEqual(env["FORCE_COLOR"], "3")
        self.assertEqual(env["CLICOLOR_FORCE"], "1")
        self.assertNotIn("NO_COLOR", env)

    def test_terminal_session_writes_when_open_and_marks_waitpid_exit(self):
        writes = []
        session = TerminalSession(
            "model-a",
            "/project",
            [],
            script_dir=lambda: Path("/app"),
            fork=lambda: (123, 7),
            fcntl_func=lambda fd, op, value=None: 0,
            select_func=lambda reads, writes_, errors, timeout: ([], [], []),
            write_func=lambda fd, data: writes.append((fd, data)),
            waitpid_func=lambda pid, flags: (pid, 0),
            kill_func=lambda pid, sig: None,
            close_func=lambda fd: None,
            environ={},
            session_id="terminal-2",
        )

        session.write("input")
        payload = session.read()
        session.stop()

        self.assertEqual(writes, [(7, b"input")])
        self.assertTrue(payload["closed"])

    def test_terminal_session_stop_sends_sigterm_when_open(self):
        killed = []
        closed = []
        session = TerminalSession(
            "model-a",
            "/project",
            [],
            script_dir=lambda: Path("/app"),
            fork=lambda: (123, 7),
            fcntl_func=lambda fd, op, value=None: 0,
            select_func=lambda reads, writes_, errors, timeout: ([], [], []),
            waitpid_func=lambda pid, flags: (0, 0),
            kill_func=lambda pid, sig: killed.append((pid, sig)),
            close_func=lambda fd: closed.append(fd),
            environ={},
            session_id="terminal-3",
        )

        session.stop()

        self.assertEqual(killed, [(123, signal.SIGTERM)])
        self.assertEqual(closed, [7])


class TerminalSessionServiceTests(unittest.TestCase):
    def test_start_defaults_model_splits_extra_args_and_stores_session(self):
        created = []

        def factory(model, project_dir, extra_args):
            created.append((model, project_dir, extra_args))
            return FakeTerminalSession("created-1")

        with tempfile.TemporaryDirectory() as tmp:
            sessions = {}
            service = TerminalSessionService(
                script_dir=lambda: Path(tmp),
                text_models=lambda: ["model-a"],
                default_text_model=lambda: "model-a",
                sessions=sessions,
                session_factory=factory,
            )
            status, payload = service.start({"model": "missing", "extra_args": "--one --two"})

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(payload, {"id": "created-1"})
        self.assertEqual(created[0][0], "model-a")
        self.assertEqual(created[0][2], ["--one", "--two"])
        self.assertIn("created-1", sessions)

    def test_start_rejects_missing_project_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = TerminalSessionService(
                script_dir=lambda: Path(tmp),
                text_models=lambda: ["model-a"],
                default_text_model=lambda: "model-a",
            )
            status, payload = service.start({"project_dir": str(Path(tmp) / "missing")})

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertIn("project directory", payload["error"])

    def test_read_write_stop_and_stop_all(self):
        session = FakeTerminalSession("terminal-1")
        service = TerminalSessionService(
            script_dir=lambda: Path("/tmp"),
            text_models=lambda: ["model-a"],
            default_text_model=lambda: "model-a",
            sessions={"terminal-1": session},
        )

        read_status, read_payload = service.read("terminal-1")
        write_status, write_payload = service.write("terminal-1", "hi")
        stop_status, stop_payload = service.stop("terminal-1")
        missing_status, missing_payload = service.read("terminal-1")

        self.assertEqual(read_status, HTTPStatus.OK)
        self.assertEqual(read_payload["output"], "hello")
        self.assertEqual(write_status, HTTPStatus.OK)
        self.assertEqual(write_payload, {"ok": True})
        self.assertEqual(session.writes, ["hi"])
        self.assertEqual(stop_status, HTTPStatus.OK)
        self.assertEqual(stop_payload, {"ok": True})
        self.assertTrue(session.stopped)
        self.assertEqual(missing_status, HTTPStatus.NOT_FOUND)
        self.assertEqual(missing_payload["error"], "terminal not found")

    def test_stop_all_stops_and_clears_sessions(self):
        sessions = {"a": FakeTerminalSession("a"), "b": FakeTerminalSession("b")}
        service = TerminalSessionService(
            script_dir=lambda: Path("/tmp"),
            text_models=lambda: ["model-a"],
            default_text_model=lambda: "model-a",
            sessions=sessions,
        )

        service.stop_all()

        self.assertEqual(sessions, {})


if __name__ == "__main__":
    unittest.main()
