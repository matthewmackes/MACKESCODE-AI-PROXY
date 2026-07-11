import unittest
from http.server import BaseHTTPRequestHandler

from src.console.app import ConsoleApp


class EmptyHandler(BaseHTTPRequestHandler):
    def handle(self):
        return None


class ConsoleAppTests(unittest.TestCase):
    def test_dependency_calls_request_counts_and_lifecycle(self):
        events = []
        app = ConsoleApp(
            service_name="console",
            version="1",
            dependencies={
                "write_token": lambda: events.append("write_token"),
                "auth_token": lambda: "secret",
                "start_proxy_if_needed": lambda: events.append("proxy"),
                "start_dedicated_policy_worker": lambda: events.append("policy"),
                "terminal_stop_all": lambda: events.append("cleanup"),
                "value": {"ok": True},
            },
        )

        token = app.startup()
        app.increment_request("GET")
        app.increment_request("GET")
        app.shutdown()

        self.assertEqual(token, "secret")
        self.assertEqual(events, ["write_token", "proxy", "policy", "cleanup"])
        self.assertEqual(app.request_counts["GET"], 2)
        self.assertEqual(app.call("value"), {"ok": True})
        self.assertTrue(app.started)
        self.assertTrue(app.stopped)

    def test_make_server_attaches_app(self):
        app = ConsoleApp("console", "1")
        server = app.make_server("127.0.0.1", 0, EmptyHandler)
        try:
            self.assertIs(server.app, app)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
