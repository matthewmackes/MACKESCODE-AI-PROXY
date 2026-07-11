import json
import signal
import unittest

from src.console.handlers.auth_handler import AuthHandler
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
            "pongs": [],
            "sizes": [],
            "writes": [],
            "kills": [],
            "closed": [],
            "fcntl": [],
            "prints": [],
            "tmux": [],
            "audits": [],
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
            identity=overrides.pop("identity", None),
            permission_for=overrides.pop("permission_for", None),
            has_permission=overrides.pop("has_permission", None),
            audit=overrides.pop("audit", lambda action, **kwargs: records["audits"].append({"action": action, **kwargs})),
            tmux_target=overrides.pop("tmux_target", lambda value: "target-" + value),
            tmux_cmd=overrides.pop("tmux_cmd", lambda args, check=True: records["tmux"].append((args, check)) or (0, "", "")),
            websocket_accept_key=overrides.pop("websocket_accept_key", lambda key: "accept-" + key),
            websocket_send=overrides.pop("websocket_send", lambda conn, text: records["sent"].append(text)),
            websocket_send_pong=overrides.pop("websocket_send_pong", lambda conn, payload=b"": records["pongs"].append(payload)),
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

    ROLE_TOKENS = {
        "viewer-token": {"id": "viewer-a", "roles": ["viewer"]},
        "billing-token": {"id": "billing-a", "roles": ["billing_admin"]},
        "operator-token": {"id": "operator-a", "roles": ["operator"]},
    }

    def auth_wired_handler(self, token, auth_enabled=True, **overrides):
        """Build a handler wired to a real AuthHandler, like the console factory does."""
        auth = AuthHandler(
            auth_enabled=lambda: auth_enabled,
            auth_token=lambda: "owner-secret",
            role_tokens=lambda: dict(self.ROLE_TOKENS),
        )
        path = "/ws/tmux?name=work&cols=100&rows=30" + ("&token=%s" % token if token else "")
        request = overrides.pop("request", FakeRequest(path=path))
        return self.handler(
            request=request,
            authorized=lambda: auth.authorized(request.path, request.headers),
            identity=lambda: auth.identity(request.path, request.headers),
            permission_for=auth.permission_for,
            has_permission=auth.has_permission,
            **overrides,
        )

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
        frames = [{"ping": b"keepalive"}, '{"resize":{"rows":44,"cols":132}}', "hello", None]
        select_ready = [[7], [request.connection], [request.connection], [request.connection], [request.connection]]
        handler, request, records = self.handler(request=request, frames=frames, select_ready=select_ready)

        handler.handle(request)

        self.assertEqual(request.responses, [(101, "Switching Protocols")])
        self.assertIn(("Upgrade", "websocket"), request.headers_sent)
        self.assertIn(("Sec-WebSocket-Accept", "accept-client-key"), request.headers_sent)
        self.assertTrue(request.connection.blocking)
        self.assertEqual(records["sent"], ["screen"])
        self.assertEqual(records["pongs"], [b"keepalive"])
        self.assertEqual(records["sizes"], [(7, 30, 100), (7, 44, 132)])
        self.assertEqual(records["writes"], [(7, b"hello")])
        self.assertEqual(records["kills"], [(123, signal.SIGHUP)])
        self.assertEqual(records["closed"], [7])
        self.assertIn("reason=client_closed", records["prints"][-1][0][0])

    def test_bad_query_and_resize_dimensions_are_clamped_or_fallback(self):
        request = FakeRequest(path="/ws/tmux?name=work&cols=bad&rows=999")
        frames = ['{"resize":{"rows":-1,"cols":900}}', None]
        select_ready = [[request.connection], [request.connection]]
        handler, request, records = self.handler(request=request, frames=frames, reads=[], select_ready=select_ready)

        handler.handle(request)

        self.assertEqual(records["sizes"], [(7, 200, 120), (7, 8, 400)])

    def test_pty_eof_breaks_and_cleans_up(self):
        handler, request, records = self.handler(reads=[b""])
        handler.handle(request)

        self.assertEqual(request.responses[0][0], 101)
        self.assertEqual(records["sent"], [])
        self.assertEqual(records["closed"], [7])
        self.assertIn("reason=pty_eof", records["prints"][-1][0][0])

    def test_owner_token_is_accepted_and_attach_detach_audited(self):
        handler, request, records = self.auth_wired_handler("owner-secret", reads=[b""])
        handler.handle(request)

        self.assertEqual(request.responses[0][0], 101)
        self.assertEqual([record["action"] for record in records["audits"]], ["tmux.ws_attach", "tmux.ws_detach"])
        attach, detach = records["audits"]
        self.assertEqual(attach["outcome"], "allowed")
        self.assertEqual(attach["permission"], "tmux_control")
        self.assertEqual(attach["status"], 101)
        self.assertEqual(attach["actor"]["id"], "console-owner")
        self.assertEqual(attach["request"], {"path": "/ws/tmux", "session": "target-work", "rows": 30, "cols": 100})
        self.assertEqual(detach["outcome"], "completed")
        self.assertEqual(detach["permission"], "tmux_control")
        self.assertEqual(detach["request"], {"path": "/ws/tmux", "session": "target-work", "reason": "pty_eof"})

    def test_scoped_token_with_tmux_control_is_accepted(self):
        handler, request, records = self.auth_wired_handler("operator-token", reads=[b""])
        handler.handle(request)

        self.assertEqual(request.responses[0][0], 101)
        self.assertEqual(records["audits"][0]["action"], "tmux.ws_attach")
        self.assertEqual(records["audits"][0]["outcome"], "allowed")
        self.assertEqual(records["audits"][0]["actor"]["id"], "operator-a")
        self.assertEqual(records["audits"][-1]["action"], "tmux.ws_detach")

    def test_scoped_token_without_tmux_control_is_rejected_pre_attach(self):
        for token, actor_id in (("viewer-token", "viewer-a"), ("billing-token", "billing-a")):
            with self.subTest(token=token):
                handler, request, records = self.auth_wired_handler(token)
                handler.handle(request)

                self.assertEqual(request.responses, [(403, None)])
                self.assertEqual(request.headers_sent, [])
                self.assertEqual(records["tmux"], [])
                self.assertEqual(records["sizes"], [])
                self.assertEqual(records["kills"], [])
                self.assertEqual(records["closed"], [])
                self.assertEqual(len(records["audits"]), 1)
                denied = records["audits"][0]
                self.assertEqual(denied["action"], "tmux.ws_attach")
                self.assertEqual(denied["outcome"], "denied")
                self.assertEqual(denied["permission"], "tmux_control")
                self.assertEqual(denied["status"], 403)
                self.assertEqual(denied["actor"]["id"], actor_id)
                self.assertNotIn(token, json.dumps(denied["request"]))

    def test_audit_never_contains_keystroke_or_screen_content(self):
        request = FakeRequest(path="/ws/tmux?name=work&cols=100&rows=30&token=owner-secret")
        frames = ["secret-keystrokes", None]
        select_ready = [[7], [request.connection], [request.connection]]
        handler, request, records = self.auth_wired_handler(
            "owner-secret", request=request, frames=frames, reads=[b"secret-screen"], select_ready=select_ready
        )
        handler.handle(request)

        self.assertEqual(records["writes"], [(7, b"secret-keystrokes")])
        self.assertEqual(records["sent"], ["secret-screen"])
        audit_dump = json.dumps(records["audits"])
        self.assertNotIn("secret-keystrokes", audit_dump)
        self.assertNotIn("secret-screen", audit_dump)
        self.assertNotIn("owner-secret", audit_dump)

    def test_auth_disabled_mode_accepts_and_audits_like_before(self):
        handler, request, records = self.auth_wired_handler("", auth_enabled=False, reads=[b""])
        handler.handle(request)

        self.assertEqual(request.responses[0][0], 101)
        self.assertEqual(records["audits"][0]["actor"]["id"], "auth-disabled")
        self.assertEqual(records["audits"][0]["outcome"], "allowed")
        self.assertEqual(records["audits"][-1]["action"], "tmux.ws_detach")

    def test_handler_without_permission_wiring_keeps_legacy_behavior(self):
        handler, request, records = self.handler(reads=[b""])
        handler.handle(request)

        self.assertEqual(request.responses[0][0], 101)
        self.assertEqual(records["audits"], [])


if __name__ == "__main__":
    unittest.main()
