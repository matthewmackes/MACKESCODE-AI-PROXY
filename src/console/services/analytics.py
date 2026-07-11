"""Analytics aggregation for Console usage, cost, and latency."""
import csv
import datetime
import io
import time


class AnalyticsService:
    """Build dashboard-friendly analytics from trace and local usage records."""

    def __init__(self, read_traces, local_usage_report, cost_summary_payload, failure_taxonomy=None, clock=None):
        self.read_traces = read_traces
        self.local_usage_report = local_usage_report
        self.cost_summary_payload = cost_summary_payload
        self.failure_taxonomy = failure_taxonomy
        self.clock = clock or time.time

    def payload(self, days=7):
        days = max(1, min(31, int(days or 7)))
        now = self.clock()
        start = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date() - datetime.timedelta(days=days - 1)
        end = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
        since = now - (days * 86400)
        traces = [row for row in self.read_traces(limit=2000) if float(row.get("timestamp") or 0) >= since]
        local_usage = self.local_usage_report(start, end)
        by_model = {}
        by_day = {item["date"]: {"date": item["date"], "requests": 0, "cost_usd": float(item.get("amount_usd") or 0)} for item in local_usage.get("daily", [])}
        latency_values = []
        errors = 0
        failure_categories = {}
        for row in traces:
            model = row.get("routed_model") or row.get("requested_model") or "unknown"
            model_row = by_model.setdefault(model, {"model": model, "requests": 0, "errors": 0, "cost_usd": 0.0, "failure_categories": {}, "latency_total_ms": 0, "latency_count": 0})
            model_row["requests"] += 1
            status = str(row.get("status") or "")
            if status == "error":
                errors += 1
                model_row["errors"] += 1
                failure = self.classify_failure(row)
                category = failure.get("category") or "unknown"
                failure_row = failure_categories.setdefault(category, {"category": category, "title": failure.get("title") or category, "count": 0, "suggested_fix": failure.get("suggested_fix") or ""})
                failure_row["count"] += 1
                model_row["failure_categories"][category] = model_row["failure_categories"].get(category, 0) + 1
            cost = float(row.get("cost_usd") or 0)
            model_row["cost_usd"] = round(model_row["cost_usd"] + cost, 8)
            try:
                latency = int(row.get("latency_ms"))
            except (TypeError, ValueError):
                latency = 0
            if latency:
                latency_values.append(latency)
                model_row["latency_total_ms"] += latency
                model_row["latency_count"] += 1
            try:
                day = datetime.datetime.fromtimestamp(float(row.get("timestamp") or 0), datetime.timezone.utc).date().isoformat()
            except (TypeError, ValueError, OSError):
                day = end.isoformat()
            day_row = by_day.setdefault(day, {"date": day, "requests": 0, "cost_usd": 0.0})
            day_row["requests"] += 1
        model_rows = []
        for item in by_model.values():
            count = item.pop("latency_count")
            total = item.pop("latency_total_ms")
            item["avg_latency_ms"] = int(total / count) if count else 0
            model_rows.append(item)
        model_rows.sort(key=lambda item: (item["cost_usd"], item["requests"]), reverse=True)
        daily_rows = [dict(item, cost_usd=round(float(item.get("cost_usd") or 0), 8)) for item in sorted(by_day.values(), key=lambda item: item["date"])]
        avg_latency = int(sum(latency_values) / len(latency_values)) if latency_values else 0
        summary = {
            "days": days,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "requests": len(traces),
            "errors": errors,
            "success_rate": round((len(traces) - errors) / len(traces), 4) if traces else 1,
            "avg_latency_ms": avg_latency,
            "local_cost_usd": float(local_usage.get("total_usd") or 0),
            "estimated_total_cost_usd": self.cost_summary_payload().get("last_24h_total_usd"),
        }
        result = {
            "summary": summary,
            "daily": daily_rows,
            "models": model_rows,
            "latency_buckets": self.latency_buckets(latency_values),
            "failure_categories": sorted(failure_categories.values(), key=lambda item: (-item["count"], item["category"])),
        }
        result["export_csv"] = self.to_csv(result)
        return result

    def classify_failure(self, row):
        if self.failure_taxonomy is not None:
            return self.failure_taxonomy.classify(row, status=row.get("http_status") or row.get("status_code"))
        failure = row.get("failure") if isinstance(row.get("failure"), dict) else {}
        category = failure.get("category") or row.get("error_category") or "unknown"
        return {"category": category, "title": category, "suggested_fix": ""}

    def latency_buckets(self, values):
        buckets = [("0-1s", 0, 1000), ("1-3s", 1001, 3000), ("3-10s", 3001, 10000), ("10s+", 10001, None)]
        rows = []
        for label, low, high in buckets:
            rows.append({"bucket": label, "count": len([value for value in values if value >= low and (high is None or value <= high)])})
        return rows

    def to_csv(self, payload):
        handle = io.StringIO()
        writer = csv.writer(handle)
        writer.writerow(["type", "key", "requests", "errors", "cost_usd", "avg_latency_ms"])
        for row in payload.get("models", []):
            writer.writerow(["model", row.get("model"), row.get("requests"), row.get("errors"), row.get("cost_usd"), row.get("avg_latency_ms")])
        for row in payload.get("daily", []):
            writer.writerow(["day", row.get("date"), row.get("requests"), "", row.get("cost_usd"), ""])
        return handle.getvalue()
