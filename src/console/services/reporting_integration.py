"""Local Grafana and Prometheus reporting integration metadata."""
from pathlib import Path


class ReportingIntegrationService:
    """Describe optional reporting setup without starting external services."""

    def __init__(self, project_root, console_status, metrics_text, otel_exporter=None):
        self.project_root = Path(project_root)
        self.console_status = console_status
        self.metrics_text = metrics_text
        self.otel_exporter = otel_exporter

    def payload(self):
        status = self.console_status()
        metrics = self.metrics_text()
        dashboards = self.dashboard_files()
        exporter = self.exporter_status()
        return {
            "metrics": {
                "enabled": True,
                "endpoint": "/metrics",
                "reachable": "matts_console_up 1" in metrics,
                "series_count": len([line for line in metrics.splitlines() if line and not line.startswith("#")]),
                "content_type": "text/plain; version=0.0.4",
            },
            "console": {
                "service": status.get("service"),
                "status": status.get("status"),
                "uptime_seconds": status.get("uptime_seconds"),
            },
            "exporter": exporter,
            "dashboards": dashboards,
            "prometheus_scrape_config": self.prometheus_scrape_config(),
            "docker_compose": self.docker_compose_snippet(),
            "privacy": {
                "bounded_labels": True,
                "excluded": ["prompts", "responses", "raw tokens", "endpoint credentials", "source snippets"],
            },
        }

    def dashboard_files(self):
        directory = self.project_root / "config" / "grafana" / "dashboards"
        rows = []
        for path in sorted(directory.glob("*.json")) if directory.exists() else []:
            rows.append({
                "name": path.stem,
                "path": str(path.relative_to(self.project_root)),
                "import_hint": "Grafana > Dashboards > New > Import",
            })
        return rows

    def exporter_status(self):
        exporter = self.otel_exporter
        if exporter is None:
            return {"enabled": False, "kind": "opentelemetry", "last_error": ""}
        enabled = bool(exporter.enabled()) if hasattr(exporter, "enabled") else False
        return {"enabled": enabled, "kind": "opentelemetry", "last_error": getattr(exporter, "last_error", "")}

    def prometheus_scrape_config(self):
        return "\n".join([
            "scrape_configs:",
            "  - job_name: mde-llm-proxy-console",
            "    metrics_path: /metrics",
            "    static_configs:",
            "      - targets: ['host.docker.internal:8080']",
            "",
        ])

    def docker_compose_snippet(self):
        return "\n".join([
            "services:",
            "  prometheus:",
            "    image: prom/prometheus:latest",
            "    ports: ['9090:9090']",
            "    volumes:",
            "      - ./config/prometheus/mde-llm-proxy-console.yml:/etc/prometheus/prometheus.yml:ro",
            "  grafana:",
            "    image: grafana/grafana-oss:latest",
            "    ports: ['3000:3000']",
            "    volumes:",
            "      - ./config/grafana/dashboards:/var/lib/grafana/dashboards:ro",
            "",
        ])
