"""Model scorecard aggregation from registry, traces, evals, and usage."""
import datetime
import time


class ModelScorecardService:
    """Build per-model quality and operations scorecards."""

    stale_after_seconds = 7 * 86400

    def __init__(self, load_model_registry, read_traces, list_eval_runs, local_usage_report, clock=None):
        self.load_model_registry = load_model_registry
        self.read_traces = read_traces
        self.list_eval_runs = list_eval_runs
        self.local_usage_report = local_usage_report
        self.clock = clock or time.time

    def registry_rows(self):
        return [row for row in (self.load_model_registry(include_disabled=True) or []) if isinstance(row, dict) and row.get("id")]

    def payload(self, days=30):
        days = max(1, min(90, int(days or 30)))
        now = self.clock()
        since = now - (days * 86400)
        today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
        usage = self.local_usage_report(today - datetime.timedelta(days=days - 1), today)
        traces = [row for row in (self.read_traces(limit=5000) or []) if self.trace_ts(row) >= since]
        eval_runs = self.list_eval_runs(limit=50)
        trace_metrics = self.trace_metrics(traces)
        eval_metrics = self.eval_metrics(eval_runs)
        usage_by_model = {row.get("model"): float(row.get("amount_usd") or 0.0) for row in usage.get("by_model") or []}
        scorecards = []
        for model in self.registry_rows():
            model_id = model["id"]
            traces_for_model = trace_metrics.get(model_id, {})
            evals_for_model = eval_metrics.get(model_id, {})
            scorecards.append(self.scorecard(model, traces_for_model, evals_for_model, usage_by_model.get(model_id, 0.0), now))
        scorecards.sort(key=lambda row: (row["enabled"] is False, -row["score"], row["model"]))
        return {
            "generated_at": now,
            "days": days,
            "stale_after_seconds": self.stale_after_seconds,
            "scorecards": scorecards,
            "by_model": {row["model"]: row for row in scorecards},
            "sources": ["model_registry", "trace_records", "eval_runs", "local_usage"],
        }

    def trace_ts(self, row):
        try:
            return float(row.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def trace_metrics(self, traces):
        metrics = {}
        for row in traces:
            model = row.get("routed_model") or row.get("requested_model")
            if not model:
                continue
            item = metrics.setdefault(model, {"requests": 0, "errors": 0, "cost_usd": 0.0, "latencies": [], "latest_ts": 0.0})
            item["requests"] += 1
            item["errors"] += 1 if str(row.get("status") or "") == "error" else 0
            item["cost_usd"] += float(row.get("cost_usd") or 0.0)
            item["latest_ts"] = max(item["latest_ts"], self.trace_ts(row))
            try:
                latency = int(row.get("latency_ms"))
            except (TypeError, ValueError):
                latency = 0
            if latency:
                item["latencies"].append(latency)
        for item in metrics.values():
            latencies = sorted(item.pop("latencies"))
            item["cost_usd"] = round(item["cost_usd"], 8)
            item["error_rate"] = round(item["errors"] / item["requests"], 4) if item["requests"] else None
            item["avg_latency_ms"] = int(sum(latencies) / len(latencies)) if latencies else None
            item["p95_latency_ms"] = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
            successes = max(0, item["requests"] - item["errors"])
            item["cost_per_success_usd"] = round(item["cost_usd"] / successes, 8) if successes else None
        return metrics

    def eval_metrics(self, runs):
        metrics = {}
        for run in runs or []:
            created_at = float(run.get("created_at") or 0.0)
            for row in run.get("summary") or []:
                if not isinstance(row, dict) or not row.get("model"):
                    continue
                item = metrics.setdefault(row["model"], {"runs": 0, "requests": 0, "failures": 0, "pass_rates": [], "cost_usd": 0.0, "latencies": [], "latest_ts": 0.0})
                item["runs"] += 1
                item["requests"] += int(row.get("requests") or 0)
                item["failures"] += int(row.get("failures") or 0)
                item["cost_usd"] += float(row.get("total_cost_usd") or 0.0)
                item["latest_ts"] = max(item["latest_ts"], created_at)
                if row.get("pass_rate") is not None:
                    item["pass_rates"].append(float(row.get("pass_rate") or 0.0))
                if row.get("avg_latency_ms") is not None:
                    item["latencies"].append(int(row.get("avg_latency_ms") or 0))
        for item in metrics.values():
            item["cost_usd"] = round(item["cost_usd"], 8)
            item["pass_rate"] = round(sum(item["pass_rates"]) / len(item["pass_rates"]), 4) if item["pass_rates"] else None
            item["failure_rate"] = round(item["failures"] / item["requests"], 4) if item["requests"] else None
            item["avg_latency_ms"] = int(sum(item["latencies"]) / len(item["latencies"])) if item["latencies"] else None
            item.pop("pass_rates", None)
            item.pop("latencies", None)
        return metrics

    def scorecard(self, model, trace_metrics, eval_metrics, local_usage_usd, now):
        trace_requests = int(trace_metrics.get("requests") or 0)
        eval_requests = int(eval_metrics.get("requests") or 0)
        latest = max(float(trace_metrics.get("latest_ts") or 0), float(eval_metrics.get("latest_ts") or 0))
        sample_count = trace_requests + eval_requests
        measured = sample_count > 0
        stale = bool(measured and latest and now - latest > self.stale_after_seconds)
        confidence = "measured" if measured and not stale else ("stale" if stale else "unavailable")
        score = self.score(trace_metrics, eval_metrics, sample_count)
        pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
        dedicated = model.get("dedicated") if isinstance(model.get("dedicated"), dict) else {}
        return {
            "model": model["id"],
            "display_name": model.get("display_name") or model["id"],
            "enabled": model.get("enabled") is not False,
            "type": model.get("type") or "unknown",
            "provider": model.get("provider") or "",
            "route": "dedicated" if dedicated.get("managed") else ("serverless" if model.get("serverless") else "custom"),
            "access_status": model.get("access_status") or "not_checked",
            "context_window": int(model.get("context_window") or 0),
            "max_output_tokens": int(model.get("max_output_tokens") or 0),
            "tool_support": bool(model.get("tool_support")),
            "pricing": pricing,
            "trace": trace_metrics or {"requests": 0, "errors": 0, "error_rate": None, "avg_latency_ms": None, "p95_latency_ms": None, "cost_per_success_usd": None},
            "eval": eval_metrics or {"runs": 0, "requests": 0, "pass_rate": None, "failure_rate": None, "avg_latency_ms": None},
            "usage": {"local_cost_usd": round(float(local_usage_usd or 0.0), 8)},
            "score": score,
            "confidence": confidence,
            "sample_count": sample_count,
            "latest_measurement_at": latest or None,
            "stale": stale,
            "recommendation": self.recommendation(model, score, confidence),
        }

    def score(self, trace_metrics, eval_metrics, sample_count):
        if sample_count <= 0:
            return 0
        eval_pass = eval_metrics.get("pass_rate")
        trace_error = trace_metrics.get("error_rate")
        latency = trace_metrics.get("avg_latency_ms") or eval_metrics.get("avg_latency_ms")
        score = 65.0
        if eval_pass is not None:
            score = 40.0 + (float(eval_pass) * 45.0)
        if trace_error is not None:
            score -= float(trace_error) * 30.0
        if latency:
            if latency <= 1000:
                score += 10
            elif latency > 10000:
                score -= 15
            elif latency > 3000:
                score -= 7
        if sample_count < 5:
            score -= 5
        return int(max(0, min(100, round(score))))

    def recommendation(self, model, score, confidence):
        if confidence == "unavailable":
            return "No recent quality data; run evals or trace traffic before making this a default."
        if confidence == "stale":
            return "Metrics are stale; refresh with a small eval or smoke run before relying on this model."
        if score >= 80:
            return "Strong measured option for its current workload."
        if score >= 60:
            return "Usable with monitoring; compare against alternatives for critical workflows."
        return "Use cautiously; failures, latency, or eval results need attention."
