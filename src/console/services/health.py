"""Console health and Prometheus metrics service."""
import datetime
import time


class ConsoleHealthService:
    """Build health status and metrics without depending on HTTP handlers."""

    def __init__(
        self,
        service,
        version,
        started_at,
        proxy_host,
        proxy_port,
        port_open,
        launcher_health,
        auth_enabled,
        tmux_sessions,
        request_counts,
        clock=None,
    ):
        self.service = service
        self.version = version
        self.started_at = started_at
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.port_open = port_open
        self.launcher_health = launcher_health
        self.auth_enabled = auth_enabled
        self.tmux_sessions = tmux_sessions
        self.request_counts = request_counts
        self.clock = clock or time.time

    def status(self):
        host = self.proxy_host()
        port = self.proxy_port()
        proxy_ready = self.port_open(host, port)
        launcher = self.launcher_health()
        now = self.clock()
        uptime_seconds = max(0, int(now - self.started_at))
        return {
            "service": self.service,
            "version": self.version,
            "status": "ok" if proxy_ready and launcher.get("ok") else "degraded",
            "uptime_seconds": uptime_seconds,
            "time": datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(),
            "proxy": {
                "host": host,
                "port": port,
                "listening": proxy_ready,
            },
            "launcher": launcher,
            "auth_enabled": self.auth_enabled(),
        }

    def metrics_text(self, status=None):
        status = status or self.status()
        lines = [
            "# HELP matts_console_up Console process health.",
            "# TYPE matts_console_up gauge",
            "matts_console_up 1",
            "# HELP matts_console_ready Console readiness for traffic.",
            "# TYPE matts_console_ready gauge",
            "matts_console_ready %d" % (1 if status["status"] == "ok" else 0),
            "# HELP matts_console_uptime_seconds Console process uptime in seconds.",
            "# TYPE matts_console_uptime_seconds gauge",
            "matts_console_uptime_seconds %d" % status["uptime_seconds"],
            "# HELP matts_console_proxy_listening Local proxy socket readiness.",
            "# TYPE matts_console_proxy_listening gauge",
            "matts_console_proxy_listening %d" % (1 if status["proxy"]["listening"] else 0),
            "# HELP matts_console_tmux_sessions Active matts tmux sessions detected.",
            "# TYPE matts_console_tmux_sessions gauge",
            "matts_console_tmux_sessions %d" % len(self.tmux_sessions()),
            "# HELP matts_console_requests_total Requests handled by method.",
            "# TYPE matts_console_requests_total counter",
        ]
        for method, count in sorted(self.request_counts.items()):
            lines.append('matts_console_requests_total{method="%s"} %d' % (method, count))
        return "\n".join(lines) + "\n"
