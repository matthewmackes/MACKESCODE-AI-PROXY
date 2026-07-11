"""Saved local model-comparison reports and exports."""
import csv
import io
import json
import re
import time
import uuid


class ComparisonReportService:
    """Persist comparison reports with simple redacted exports."""

    schema_version = 1
    secret_pattern = re.compile(
        r"(sk-[A-Za-z0-9_-]{8,}|dop_v1_[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{12,}|token[=:][A-Za-z0-9._-]{12,})",
        re.I,
    )

    def __init__(self, reports_dir, clock=None, uuid_factory=None):
        self.reports_dir = reports_dir
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def directory(self):
        path = self.reports_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def report_path(self, report_id):
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(report_id or ""))
        return self.directory() / ("%s.json" % (safe or "report"))

    def redact_text(self, value):
        return self.secret_pattern.sub("[redacted]", str(value or ""))

    def redact_obj(self, value):
        if isinstance(value, dict):
            return {key: self.redact_obj(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact_obj(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def normalize_result(self, item, index):
        item = item if isinstance(item, dict) else {"error": "missing comparison result"}
        routing = item.get("routing") if isinstance(item.get("routing"), dict) else {}
        cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        streaming = item.get("streaming_metrics") if isinstance(item.get("streaming_metrics"), dict) else {}
        latency = item.get("latency_ms")
        if latency is None:
            latency = streaming.get("elapsed_ms") or streaming.get("duration_ms")
        return {
            "index": int(item.get("index") or index),
            "model": str(item.get("model") or routing.get("requested") or "model-%s" % index),
            "routed_model": str(routing.get("used") or item.get("routed_model") or item.get("model") or ""),
            "ok": bool(item.get("ok", not item.get("error"))),
            "status": int(item.get("status") or (200 if not item.get("error") else 500)),
            "text": self.redact_text(item.get("text") or ""),
            "error": self.redact_text(item.get("error") or ""),
            "routing": self.redact_obj(routing),
            "usage": self.redact_obj(usage),
            "cost": self.redact_obj(cost),
            "latency_ms": latency,
            "trace_id": str(item.get("trace_id") or ""),
            "streaming_metrics": self.redact_obj(streaming),
            "notes": self.redact_text(item.get("notes") or ""),
            "rank": item.get("rank"),
        }

    def normalize_report(self, data):
        if not isinstance(data, dict):
            raise ValueError("Comparison report must be a JSON object.")
        now = self.clock()
        prompt = self.redact_text(data.get("prompt") or "")
        results = data.get("results") if isinstance(data.get("results"), list) else []
        normalized = [self.normalize_result(item, index) for index, item in enumerate(results, start=1)]
        report_id = data.get("id") or "comparison_%d_%s" % (now, self.uuid_factory().hex[:10])
        title = self.redact_text(data.get("title") or ("Comparison: " + prompt[:60]) or "Comparison Report")
        models = [str(model) for model in (data.get("models") or []) if str(model or "").strip()]
        if not models:
            models = [result["model"] for result in normalized]
        winner = str(data.get("winner_model") or "")
        return {
            "schema_version": self.schema_version,
            "id": str(report_id),
            "title": title,
            "prompt": prompt,
            "models": models,
            "results": normalized,
            "notes": self.redact_text(data.get("notes") or ""),
            "winner_model": winner,
            "tags": [str(tag) for tag in (data.get("tags") or []) if str(tag or "").strip()],
            "chat_id": str(data.get("chat_id") or ""),
            "trace_ids": [result["trace_id"] for result in normalized if result.get("trace_id")],
            "total_cost_usd": round(sum(float((result.get("cost") or {}).get("total_cost_usd") or 0.0) for result in normalized), 8),
            "scorecard_links": [{"model": model, "report_id": str(report_id)} for model in sorted(set(models))],
            "dataset_builder_examples": self.dataset_examples(prompt, normalized, winner, str(report_id)),
            "created_at": data.get("created_at") or now,
            "updated_at": now,
        }

    def dataset_examples(self, prompt, results, winner, report_id):
        examples = []
        for result in results:
            if not result.get("ok"):
                continue
            examples.append({
                "source_type": "comparison",
                "redaction_reviewed": True,
                "input": prompt,
                "expected": result.get("text") or "",
                "requested_model": result.get("model"),
                "routed_model": result.get("routed_model"),
                "routing_reason": (result.get("routing") or {}).get("reason") or (result.get("routing") or {}).get("backend"),
                "cost_usd": (result.get("cost") or {}).get("total_cost_usd"),
                "trace_id": result.get("trace_id"),
                "tags": ["comparison-report", "winner" if result.get("model") == winner else "candidate"],
                "notes": result.get("notes") or "",
                "comparison": {"report_id": report_id, "requested_model": result.get("model"), "routed_model": result.get("routed_model")},
            })
        return examples

    def save_report(self, data):
        report = self.normalize_report(data)
        self.report_path(report["id"]).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return report

    def load_report(self, report_id):
        path = self.report_path(report_id)
        if not path.exists():
            return None
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return report if isinstance(report, dict) else None

    def list_reports(self):
        rows = []
        for path in sorted(self.directory().glob("*.json"), reverse=True):
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows.append({
                "id": report.get("id", path.stem),
                "title": report.get("title", "Comparison Report"),
                "models": report.get("models") or [],
                "result_count": len(report.get("results") or []),
                "winner_model": report.get("winner_model") or "",
                "total_cost_usd": report.get("total_cost_usd", 0),
                "updated_at": report.get("updated_at", report.get("created_at", 0)),
                "tags": report.get("tags") or [],
            })
        return rows

    def markdown_export(self, report):
        lines = ["# %s" % report.get("title", "Comparison Report"), ""]
        lines.append("Prompt: %s" % self.redact_text(report.get("prompt") or ""))
        if report.get("winner_model"):
            lines.append("Winner: %s" % report["winner_model"])
        if report.get("notes"):
            lines.extend(["", "Notes: %s" % self.redact_text(report["notes"])])
        lines.append("")
        lines.append("| Model | Routed | Cost | Latency | Trace | Status |")
        lines.append("| --- | --- | ---: | ---: | --- | --- |")
        for result in report.get("results") or []:
            cost = (result.get("cost") or {}).get("total_cost_usd")
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                result.get("model") or "",
                result.get("routed_model") or "",
                cost if cost is not None else "",
                result.get("latency_ms") if result.get("latency_ms") is not None else "",
                result.get("trace_id") or "",
                "ok" if result.get("ok") else "error",
            ))
        for result in report.get("results") or []:
            lines.extend(["", "## %s" % (result.get("model") or "Model"), ""])
            lines.append(self.redact_text(result.get("text") or result.get("error") or ""))
        return "\n".join(lines) + "\n"

    def csv_export(self, report):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["model", "routed_model", "ok", "status", "cost_usd", "latency_ms", "trace_id", "routing_reason", "text", "error"])
        writer.writeheader()
        for result in report.get("results") or []:
            routing = result.get("routing") or {}
            cost = result.get("cost") or {}
            writer.writerow({
                "model": result.get("model") or "",
                "routed_model": result.get("routed_model") or "",
                "ok": result.get("ok"),
                "status": result.get("status"),
                "cost_usd": cost.get("total_cost_usd", ""),
                "latency_ms": result.get("latency_ms", ""),
                "trace_id": result.get("trace_id") or "",
                "routing_reason": routing.get("reason") or routing.get("backend") or "",
                "text": self.redact_text(result.get("text") or ""),
                "error": self.redact_text(result.get("error") or ""),
            })
        return out.getvalue()

    def export_report(self, report_id, fmt):
        report = self.load_report(report_id)
        if report is None:
            raise ValueError("comparison report not found")
        fmt = str(fmt or "json").lower()
        if fmt == "md":
            fmt = "markdown"
        if fmt == "markdown":
            return {"format": "markdown", "filename": report["id"] + ".md", "content_type": "text/markdown", "content": self.markdown_export(report)}
        if fmt == "csv":
            return {"format": "csv", "filename": report["id"] + ".csv", "content_type": "text/csv", "content": self.csv_export(report)}
        if fmt == "json":
            return {"format": "json", "filename": report["id"] + ".json", "content_type": "application/json", "content": json.dumps(self.redact_obj(report), indent=2, ensure_ascii=False) + "\n"}
        raise ValueError("unsupported comparison report export format")
