import signal
import unittest

from src.console.handlers.websocket_handler import TmuxWebSocketHandler


class FakeConnection:
    def __init__(self):
        self.blocking = None

    def setblocking(self, value):
        self.blocking = value


class FakeRequest:
    def __init__(self, path="/ws/tmux?name=work&cols=100&rows=30", headers=None):
        self.path = path
        self.headers = {"sec-websocket-key": "client-key"} if headers is None else headers
        self.connection = FakeConnection()
        self.responses = []
        self.headers_sent = []
        self.ended = 0

    def send_response(self, status, message=None):
        self.responses.append((status, message))

    def send_header(self, key, value):
        self.headers_sent.append((key, value))

    def end_headers(self):
        self.ended += 1


class TmuxWebSocketHandlerTests(unittest.TestCase):
    def handler(self, **overrides):
        records = {
            "sent": [],
            "sizes": [],
            "writes": [],
            "kills": [],
            "closed": [],
            "fcntl": [],
            "prints": [],
            "tmux": [],
        }
        frames = overrides.pop("frames", [])
        reads = overrides.pop("reads", [b"screen"])
        select_ready = overrides.pop("select_ready", None)

        def select_func(items, writes, errors, timeout):
            if select_ready is not None:
                return (select_ready.pop(0) if select_ready else [], [], [])
            if reads:
                return ([7], [], [])
            if frames:
                return ([request.connection], [], [])
            return ([request.connection], [], [])

        request = overrides.pop("request", FakeRequest())
        handler = TmuxWebSocketHandler(
            authorized=overrides.pop("authorized", lambda: True),
            tmux_target=overrides.pop("tmux_target", lambda value: "target-" + value),
            tmux_cmd=overrides.pop("tmux_cmd", lambda args, check=True: records["tmux"].append((args, check)) or (0, "", "")),
            websocket_accept_key=overrides.pop("websocket_accept_key", lambda key: "accept-" + key),
            websocket_send=overrides.pop("websocket_send", lambda conn, text: records["sent"].append(text)),
            websocket_read_frame=overrides.pop("websocket_read_frame", lambda conn: frames.pop(0) if frames else None),
            set_pty_size=overrides.pop("set_pty_size", lambda fd, rows, cols: records["sizes"].append((fd, rows, cols))),
            fork_func=overrides.pop("fork_func", lambda: (123, 7)),
            execvp_func=overrides.pop("execvp_func", lambda *args: None),
            select_func=overrides.pop("select_func", select_func),
            fcntl_func=overrides.pop("fcntl_func", lambda fd, op, value=None: records["fcntl"].append((fd, op, value)) or 0),
            read_func=overrides.pop("read_func", lambda fd, size: reads.pop(0) if reads else b""),
            write_func=overrides.pop("write_func", lambda fd, data: records["writes"].append((fd, data))),
            kill_func=overrides.pop("kill_func", lambda pid, sig: records["kills"].append((pid, sig))),
            close_func=overrides.pop("close_func", lambda fd: records["closed"].append(fd)),
            environ=overrides.pop("environ", {}),
            print_func=overrides.pop("print_func", lambda *args, **kwargs: records["prints"].append((args, kwargs))),
        )
        self.assertEqual(overrides, {})
        return handler, request, records

    def test_rejects_unauthorized_missing_tmux_and_missing_key(self):
        handler, request, _ = self.handler(authorized=lambda: False)
        handler.handle(request)
        self.assertEqual(request.responses, [(401, None)])

        handler, request, _ = self.handler(tmux_cmd=lambda args, check=True: (1, "", "missing"))
        handler.handle(request)
        self.assertEqual(request.responses, [(404, None)])

        handler, request, _ = self.handler(request=FakeRequest(headers={}))
        handler.handle(request)
        self.assertEqual(request.responses, [(400, None)])

    def test_successful_bridge_sends_output_resizes_writes_input_and_cleans_up(self):
        request = FakeRequest()
        frames = ['{"resize":{"rows":44,"cols":132}}', "hello", None]
        select_ready = [[7], [request.connection], [request.connection], [request.connection]]
        handler, request, records = self.handler(request=request, frames=frames, select_ready=select_ready)

        handler.handle(request)

        self.assertEqual(request.responses, [(101, "Switching Protocols")])
        self.assertIn(("Upgrade", "websocket"), request.headers_sent)
        self.assertIn(("Sec-WebSocket-Accept", "accept-client-key"), request.headers_sent)
        self.assertTrue(request.connection.blocking)
        self.assertEqual(records["sent"], ["screen"])
        self.assertEqual(records["sizes"], [(7, 30, 100), (7, 44, 132)])
        self.assertEqual(records["writes"], [(7, b"hello")])
        self.assertEqual(records["kills"], [(123, signal.SIGHUP)])
        self.assertEqual(records["closed"], [7])

    def test_pty_eof_breaks_and_cleans_up(self):
        handler, request, records = self.handler(reads=[b""])
        handler.handle(request)

        self.assertEqual(request.responses[0][0], 101)
        self.assertEqual(records["sent"], [])
        self.assertEqual(records["closed"], [7])


if __name__ == "__main__":
    unittest.main()
