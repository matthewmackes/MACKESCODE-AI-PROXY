"""Application shell for the console HTTP server."""
from http.server import ThreadingHTTPServer


class ConsoleApp:
    """Own console dependencies, lifecycle hooks, and server binding."""

    def __init__(self, service_name, version, config=None, dependencies=None, request_counts=None):
        self.service_name = service_name
        self.version = version
        self.config = config if isinstance(config, dict) else {}
        self.dependencies = dependencies or {}
        self.request_counts = request_counts if isinstance(request_counts, dict) else {"GET": 0, "POST": 0}
        self.started = False
        self.stopped = False

    def call(self, name, *args, **kwargs):
        dependency = self.dependencies[name]
        if callable(dependency):
            return dependency(*args, **kwargs)
        if args or kwargs:
            raise TypeError("dependency %s is not callable" % name)
        return dependency

    def get(self, name, default=None):
        return self.dependencies.get(name, default)

    def increment_request(self, method):
        method = str(method or "").upper()
        self.request_counts[method] = int(self.request_counts.get(method, 0)) + 1
        return self.request_counts[method]

    def startup(self):
        self.call_if_present("write_token")
        token = self.call_if_present("auth_token")
        self.call_if_present("start_proxy_if_needed")
        self.call_if_present("start_dedicated_policy_worker")
        self.started = True
        return token

    def shutdown(self):
        self.call_if_present("terminal_stop_all")
        self.stopped = True

    def call_if_present(self, name, *args, **kwargs):
        if name not in self.dependencies:
            return None
        return self.call(name, *args, **kwargs)

    def make_server(self, host, port, handler_cls):
        server = ThreadingHTTPServer((host, int(port)), handler_cls)
        server.app = self
        return server
