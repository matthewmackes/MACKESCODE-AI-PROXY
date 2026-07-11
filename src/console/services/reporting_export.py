"""DuckDB/SQLite export for local reporting tools."""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path


class ReportingExportService:
    """Export redacted runtime data into a local SQL database."""

    schema_version = 1
    export_prefix = "mde-llm-proxy-reporting"
    legacy_export_prefix = "matts-reporting"
    sensitive_keys = {"authorization", "token", "api_key", "access_key", "secret", "password", "messages", "prompt", "input", "output", "screen", "raw", "text", "answer"}
    secret_pattern = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|dop_v1_[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{12,}|token[=:][A-Za-z0-9._-]{12,})", re.I)

    def __init__(
        self,
        output_dir,
        read_traces,
        dedicated_events,
        list_eval_runs,
        list_comparison_reports,
        audit_rows,
        review_queue_payload,
        release_candidate_payload,
        cost_summary_payload,
        source_files=None,
        clock=None,
    ):
        self.output_dir = Path(output_dir)
        self.read_traces = read_traces
        self.dedicated_events = dedicated_events
        self.list_eval_runs = list_eval_runs
        self.list_comparison_reports = list_comparison_reports
        self.audit_rows = audit_rows
        self.review_queue_payload = review_queue_payload
        self.release_candidate_payload = release_candidate_payload
        self.cost_summary_payload = cost_summary_payload
        self.source_files = source_files or {}
        self.clock = clock or time.time

    def export(self, request=None):
        request = request if isinstance(request, dict) else {}
        preferred = str(request.get("format") or "duckdb").lower()
        driver, warning = self.driver(preferred)
        suffix = ".duckdb" if driver == "duckdb" else ".sqlite"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / (self.export_prefix + suffix)
        if path.exists():
            path.unlink()
        conn = self.connect(driver, path)
        try:
            tables = self.write_tables(conn)
        finally:
            conn.close()
        result = {
            "export_id": "reporting_%d" % int(self.clock()),
            "schema_version": self.schema_version,
            "format": driver,
            "path": str(path),
            "tables": tables,
            "redaction_mode": "default_safe",
            "exported_at": float(self.clock()),
            "source_fingerprints": self.source_fingerprints(),
        }
        if warning:
            result["warnings"] = [warning]
        return result

    def status(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        files = []
        seen = set()
        for prefix in (self.export_prefix, self.legacy_export_prefix):
            for path in sorted(self.output_dir.glob(prefix + ".*")):
                if path in seen or path.suffix not in {".duckdb", ".sqlite"}:
                    continue
                seen.add(path)
                stat = path.stat()
                files.append({"path": str(path), "format": "duckdb" if path.suffix == ".duckdb" else "sqlite", "size_bytes": stat.st_size, "updated_at": stat.st_mtime})
        return {"available": bool(files), "exports": files, "output_dir": str(self.output_dir), "schema_version": self.schema_version}

    def driver(self, preferred):
        if preferred == "sqlite":
            return "sqlite", ""
        try:
            import duckdb  # noqa: F401
            return "duckdb", ""
        except Exception:
            return "sqlite", "DuckDB is not installed; wrote SQLite fallback."

    def connect(self, driver, path):
        if driver == "duckdb":
            import duckdb
            return duckdb.connect(str(path))
        return sqlite3.connect(str(path))

    def write_tables(self, conn):
        tables = {}
        writers = [
            ("metadata", self.write_metadata),
            ("source_fingerprints", self.write_source_fingerprints),
            ("trace_events", self.write_traces),
            ("usage_events", self.write_usage),
            ("eval_runs", self.write_eval_runs),
            ("eval_results", self.write_eval_results),
            ("comparison_reports", self.write_comparison_reports),
            ("dedicated_lifecycle_events", self.write_dedicated_events),
            ("audit_events_redacted", self.write_audit_events),
            ("review_items", self.write_review_items),
            ("release_checks", self.write_release_checks),
        ]
        for name, writer in writers:
            tables[name] = writer(conn)
        conn.commit()
        return tables

    def execute(self, conn, sql, params=()):
        conn.execute(sql, params)

    def create(self, conn, table, columns):
        self.execute(conn, "CREATE TABLE %s (%s)" % (table, ", ".join(columns)))

    def insert(self, conn, table, columns, rows):
        if not rows:
            return 0
        placeholders = ",".join(["?"] * len(columns))
        conn.executemany("INSERT INTO %s (%s) VALUES (%s)" % (table, ", ".join(columns), placeholders), rows)
        return len(rows)

    def write_metadata(self, conn):
        self.create(conn, "metadata", ["key TEXT", "value TEXT"])
        rows = [
            ("schema_version", str(self.schema_version)),
            ("exported_at", str(float(self.clock()))),
            ("redaction_mode", "default_safe"),
        ]
        return self.insert(conn, "metadata", ["key", "value"], rows)

    def write_source_fingerprints(self, conn):
        self.create(conn, "source_fingerprints", ["source TEXT", "path TEXT", "sha256 TEXT", "size_bytes INTEGER"])
        rows = [(name, item["path"], item["sha256"], item["size_bytes"]) for name, item in self.source_fingerprints().items()]
        return self.insert(conn, "source_fingerprints", ["source", "path", "sha256", "size_bytes"], rows)

    def write_traces(self, conn):
        self.create(conn, "trace_events", ["trace_id TEXT", "timestamp REAL", "status TEXT", "action TEXT", "requested_model TEXT", "routed_model TEXT", "provider TEXT", "endpoint_mode TEXT", "routing_reason TEXT", "error_category TEXT", "latency_ms REAL", "cost_usd REAL", "payload_json TEXT"])
        rows = []
        for row in self.safe_list(self.read_traces, limit=5000):
            rows.append((row.get("trace_id") or "", self.num(row.get("timestamp")), row.get("status") or "", row.get("action") or "", row.get("requested_model") or "", row.get("routed_model") or "", row.get("provider") or "", row.get("endpoint_mode") or "", row.get("routing_reason") or "", row.get("error_category") or "", self.num(row.get("latency_ms")), self.num(row.get("cost_usd")), self.json(row)))
        return self.insert(conn, "trace_events", ["trace_id", "timestamp", "status", "action", "requested_model", "routed_model", "provider", "endpoint_mode", "routing_reason", "error_category", "latency_ms", "cost_usd", "payload_json"], rows)

    def write_usage(self, conn):
        self.create(conn, "usage_events", ["window TEXT", "amount_usd REAL", "payload_json TEXT"])
        summary = self.safe_dict(self.cost_summary_payload)
        rows = [("24h", self.num(summary.get("last_24h_total_usd")), self.json(summary)), ("month", self.num(summary.get("month_total_usd")), self.json(summary))]
        return self.insert(conn, "usage_events", ["window", "amount_usd", "payload_json"], rows)

    def write_eval_runs(self, conn):
        self.create(conn, "eval_runs", ["id TEXT", "created_at REAL", "dataset TEXT", "models TEXT", "example_count INTEGER", "payload_json TEXT"])
        rows = []
        for run in self.safe_list(self.list_eval_runs, limit=5000):
            rows.append((run.get("id") or "", self.num(run.get("created_at")), run.get("dataset") or "", json.dumps(run.get("models") or []), int(run.get("example_count") or 0), self.json(run)))
        return self.insert(conn, "eval_runs", ["id", "created_at", "dataset", "models", "example_count", "payload_json"], rows)

    def write_eval_results(self, conn):
        self.create(conn, "eval_results", ["run_id TEXT", "dataset TEXT", "model TEXT", "requests INTEGER", "failures INTEGER", "total_cost_usd REAL", "avg_latency_ms REAL", "pass_rate REAL", "payload_json TEXT"])
        rows = []
        for run in self.safe_list(self.list_eval_runs, limit=5000):
            for summary in run.get("summary") or []:
                if isinstance(summary, dict):
                    rows.append((run.get("id") or "", run.get("dataset") or "", summary.get("model") or "", int(summary.get("requests") or 0), int(summary.get("failures") or 0), self.num(summary.get("total_cost_usd")), self.num(summary.get("avg_latency_ms")), self.num(summary.get("pass_rate")), self.json(summary)))
        return self.insert(conn, "eval_results", ["run_id", "dataset", "model", "requests", "failures", "total_cost_usd", "avg_latency_ms", "pass_rate", "payload_json"], rows)

    def write_comparison_reports(self, conn):
        self.create(conn, "comparison_reports", ["id TEXT", "title TEXT", "created_at REAL", "winner_model TEXT", "total_cost_usd REAL", "result_count INTEGER", "models TEXT", "payload_json TEXT"])
        rows = []
        for report in self.safe_list(self.list_comparison_reports):
            rows.append((report.get("id") or "", report.get("title") or "", self.num(report.get("created_at")), report.get("winner_model") or "", self.num(report.get("total_cost_usd")), int(report.get("result_count") or len(report.get("results") or [])), json.dumps(report.get("models") or []), self.json(report)))
        return self.insert(conn, "comparison_reports", ["id", "title", "created_at", "winner_model", "total_cost_usd", "result_count", "models", "payload_json"], rows)

    def write_dedicated_events(self, conn):
        self.create(conn, "dedicated_lifecycle_events", ["timestamp REAL", "type TEXT", "state TEXT", "severity TEXT", "model TEXT", "message TEXT", "payload_json TEXT"])
        rows = []
        for event in self.safe_list(self.dedicated_events, limit=5000):
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            rows.append((self.num(event.get("timestamp")), event.get("type") or "", event.get("state") or data.get("state") or "", event.get("severity") or "", data.get("model") or event.get("model") or "", event.get("message") or "", self.json(event)))
        return self.insert(conn, "dedicated_lifecycle_events", ["timestamp", "type", "state", "severity", "model", "message", "payload_json"], rows)

    def write_audit_events(self, conn):
        self.create(conn, "audit_events_redacted", ["timestamp REAL", "action TEXT", "actor_id TEXT", "permission TEXT", "outcome TEXT", "status INTEGER", "payload_json TEXT"])
        rows = []
        for row in self.safe_list(self.audit_rows, limit=5000):
            actor = row.get("actor") if isinstance(row.get("actor"), dict) else {}
            rows.append((self.num(row.get("timestamp")), row.get("action") or "", row.get("actor_id") or actor.get("id") or "", row.get("permission") or "", row.get("outcome") or "", int(row.get("status") or 0), self.json(row)))
        return self.insert(conn, "audit_events_redacted", ["timestamp", "action", "actor_id", "permission", "outcome", "status", "payload_json"], rows)

    def write_review_items(self, conn):
        self.create(conn, "review_items", ["id TEXT", "status TEXT", "severity TEXT", "reason TEXT", "title TEXT", "created_at REAL", "updated_at REAL", "payload_json TEXT"])
        payload = self.safe_dict(self.review_queue_payload)
        rows = [(row.get("id") or "", row.get("status") or "", row.get("severity") or "", row.get("reason") or "", row.get("title") or "", self.num(row.get("created_at")), self.num(row.get("updated_at")), self.json(row)) for row in payload.get("reviews") or [] if isinstance(row, dict)]
        return self.insert(conn, "review_items", ["id", "status", "severity", "reason", "title", "created_at", "updated_at", "payload_json"], rows)

    def write_release_checks(self, conn):
        self.create(conn, "release_checks", ["name TEXT", "status TEXT", "severity TEXT", "message TEXT", "payload_json TEXT"])
        payload = self.safe_dict(self.release_candidate_payload)
        rows = [(row.get("name") or row.get("id") or "", row.get("status") or "", row.get("severity") or "", row.get("message") or row.get("summary") or "", self.json(row)) for row in payload.get("checks") or [] if isinstance(row, dict)]
        return self.insert(conn, "release_checks", ["name", "status", "severity", "message", "payload_json"], rows)

    def safe_list(self, fn, *args, **kwargs):
        try:
            value = fn(*args, **kwargs)
        except Exception:
            return []
        return value if isinstance(value, list) else []

    def safe_dict(self, fn, *args, **kwargs):
        try:
            value = fn(*args, **kwargs)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def source_fingerprints(self):
        rows = {}
        for name, value in self.source_files.items():
            path = Path(value() if callable(value) else value)
            if not path.exists():
                rows[name] = {"path": str(path), "sha256": "", "size_bytes": 0}
                continue
            if path.is_dir():
                digest = hashlib.sha256()
                total = 0
                for item in sorted(child for child in path.rglob("*") if child.is_file()):
                    data = item.read_bytes()
                    total += len(data)
                    digest.update(str(item.relative_to(path)).encode("utf-8"))
                    digest.update(data)
                rows[name] = {"path": str(path), "sha256": digest.hexdigest(), "size_bytes": total}
                continue
            data = path.read_bytes()
            rows[name] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
        return rows

    def json(self, value):
        return json.dumps(self.redact(value), sort_keys=True)

    def redact(self, value):
        if isinstance(value, dict):
            return {str(key): ("[redacted]" if str(key).lower() in self.sensitive_keys else self.redact(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            return self.secret_pattern.sub("[redacted]", value)
        return value

    def num(self, value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
