"""Cost and usage anomaly detection over local telemetry."""
import hashlib
import json
import time
from pathlib import Path


class CostAnomalyService:
    """Detect cost, token, request, eval, image, and Dedicated runtime spikes."""

    STATUSES = {"new", "acknowledged", "suppressed", "resolved"}

    def __init__(
        self,
        state_file,
        read_traces,
        list_eval_runs,
        load_dedicated_config,
        dedicated_runtime_cost_summary,
        create_review_item=None,
        append_audit=None,
        clock=None,
    ):
        self.state_file = state_file
        self.read_traces = read_traces
        self.list_eval_runs = list_eval_runs
        self.load_dedicated_config = load_dedicated_config
        self.dedicated_runtime_cost_summary = dedicated_runtime_cost_summary
        self.create_review_item = create_review_item or (lambda payload: {"review": payload})
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.clock = clock or time.time

    def path(self):
        path = Path(self.state_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def load_state(self):
        path = self.path()
        if not path.exists():
            return {"schema_version": 1, "states": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema_version": 1, "states": {}}
        return {"schema_version": 1, "states": data.get("states") if isinstance(data.get("states"), dict) else {}}

    def save_state(self, state):
        self.path().write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state

    def stable_id(self, metric):
        return "cost_anomaly_%s" % hashlib.sha256(str(metric).encode("utf-8")).hexdigest()[:16]

    def trace_ts(self, row):
        try:
            return float(row.get("timestamp") or row.get("ts") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def trace_cost(self, row):
        try:
            return float(row.get("cost_usd") if row.get("cost_usd") is not None else (row.get("cost") or {}).get("total_cost_usd") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def trace_tokens(self, row):
        cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
        for key in ("total_tokens_est", "total_tokens"):
            try:
                if cost.get(key) is not None:
                    return int(cost.get(key) or 0)
            except (TypeError, ValueError):
                pass
        total = 0
        for key in ("prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"):
            try:
                total += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                pass
        return total

    def route(self, row):
        routing = row.get("routing") if isinstance(row.get("routing"), dict) else {}
        return row.get("endpoint_mode") or row.get("backend") or routing.get("backend") or row.get("routing_reason") or "unknown"

    def action(self, row):
        return row.get("action") or row.get("type") or "request"

    def is_image(self, row):
        text = " ".join(str(item or "").lower() for item in (self.action(row), row.get("requested_model"), row.get("routed_model")))
        return "image" in text or "generate" in text or "stable-diffusion" in text or "flux" in text

    def bucket_metrics(self, rows):
        metrics = {
            "spend_usd": 0.0,
            "tokens": 0,
            "requests": 0,
            "image_requests": 0,
            "by_model": {},
            "by_session": {},
            "by_actor": {},
            "by_route": {},
            "by_action": {},
        }
        for row in rows:
            cost = self.trace_cost(row)
            model = row.get("routed_model") or row.get("requested_model") or "unknown"
            session = row.get("session") or row.get("session_id") or row.get("chat_id") or "unknown"
            actor = row.get("actor_id") or row.get("actor") or "unknown"
            if isinstance(actor, dict):
                actor = actor.get("id") or actor.get("name") or "unknown"
            route = self.route(row)
            action = self.action(row)
            metrics["spend_usd"] += cost
            metrics["tokens"] += self.trace_tokens(row)
            metrics["requests"] += 1
            metrics["image_requests"] += 1 if self.is_image(row) else 0
            self.add_bucket(metrics["by_model"], model, cost)
            self.add_bucket(metrics["by_session"], session, cost)
            self.add_bucket(metrics["by_actor"], actor, cost)
            self.add_bucket(metrics["by_route"], route, cost)
            self.add_bucket(metrics["by_action"], action, cost)
        metrics["spend_usd"] = round(metrics["spend_usd"], 8)
        return metrics

    def add_bucket(self, target, key, cost):
        row = target.setdefault(str(key or "unknown"), {"count": 0, "cost_usd": 0.0})
        row["count"] += 1
        row["cost_usd"] = round(row["cost_usd"] + float(cost or 0.0), 8)

    def eval_count(self, start, end):
        count = 0
        for run in self.list_eval_runs(limit=200) or []:
            try:
                ts = float(run.get("created_at") or run.get("started_at") or run.get("ts") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            if start <= ts < end:
                count += 1
        return count

    def dedicated_metrics(self):
        try:
            summary = self.dedicated_runtime_cost_summary(self.load_dedicated_config(), self.clock()) or {}
        except Exception:
            summary = {}
        month_seconds = int(summary.get("month_seconds") or 0)
        last_24h_seconds = int(summary.get("last_24h_seconds") or 0)
        day_count = max(1.0, (self.clock() - (self.clock() - month_seconds)) / 86400.0) if month_seconds else 1.0
        return {
            "dedicated_runtime_seconds": last_24h_seconds,
            "dedicated_cost_usd": float(summary.get("last_24h_cost_usd") or 0.0),
            "baseline_daily_seconds": month_seconds / day_count if month_seconds else 0.0,
            "summary": summary,
        }

    def top_bucket(self, buckets):
        if not buckets:
            return {"key": "unknown", "cost_usd": 0.0, "count": 0}
        key, row = sorted(buckets.items(), key=lambda item: (item[1].get("cost_usd", 0.0), item[1].get("count", 0)), reverse=True)[0]
        return {"key": key, **row}

    def anomaly(self, metric, current, baseline, unit, evidence, minimum=1.0, multiplier=3.0):
        threshold = max(float(minimum), float(baseline or 0.0) * float(multiplier))
        if current <= threshold:
            return None
        ratio = round((float(current) / float(baseline)) if baseline else 999.0, 4)
        severity = "critical" if ratio >= multiplier * 2 or current >= threshold * 2 else "high"
        return {
            "id": self.stable_id(metric),
            "metric": metric,
            "title": "%s anomaly" % metric.replace("_", " ").title(),
            "severity": severity,
            "status": "new",
            "current": round(float(current), 8),
            "baseline": round(float(baseline or 0.0), 8),
            "threshold": round(threshold, 8),
            "ratio": ratio,
            "unit": unit,
            "evidence": evidence,
            "created_at": self.clock(),
        }

    def apply_state(self, rows):
        states = self.load_state().get("states") or {}
        result = []
        for row in rows:
            state = states.get(row["id"]) if isinstance(states.get(row["id"]), dict) else {}
            row = dict(row)
            row["status"] = state.get("status") or row.get("status") or "new"
            row["notes"] = state.get("notes") or ""
            row["actor"] = state.get("actor") or {}
            if row["status"] != "suppressed":
                result.append(row)
        return result

    def payload(self, config=None):
        config = config if isinstance(config, dict) else {}
        now = self.clock()
        window = int(config.get("window_seconds") or 86400)
        baseline_days = int(config.get("baseline_days") or 7)
        multiplier = float(config.get("multiplier") or 3.0)
        traces = self.read_traces(limit=10000) or []
        current_rows = [row for row in traces if now - window <= self.trace_ts(row) <= now]
        baseline_start = now - window - baseline_days * 86400
        baseline_rows = [row for row in traces if baseline_start <= self.trace_ts(row) < now - window]
        current = self.bucket_metrics(current_rows)
        baseline_total = self.bucket_metrics(baseline_rows)
        baseline_daily = {key: (value / max(1, baseline_days) if isinstance(value, (int, float)) else value) for key, value in baseline_total.items() if key not in {"by_model", "by_session", "by_actor", "by_route", "by_action"}}
        eval_current = self.eval_count(now - window, now)
        eval_baseline = self.eval_count(baseline_start, now - window) / max(1, baseline_days)
        dedicated = self.dedicated_metrics()
        evidence = {
            "top_model": self.top_bucket(current["by_model"]),
            "top_session": self.top_bucket(current["by_session"]),
            "top_actor": self.top_bucket(current["by_actor"]),
            "top_route": self.top_bucket(current["by_route"]),
            "top_action": self.top_bucket(current["by_action"]),
            "window_seconds": window,
            "baseline_days": baseline_days,
        }
        anomalies = [
            self.anomaly("spend_usd", current["spend_usd"], baseline_daily.get("spend_usd", 0.0), "usd", evidence, minimum=1.0, multiplier=multiplier),
            self.anomaly("tokens", current["tokens"], baseline_daily.get("tokens", 0.0), "tokens", evidence, minimum=20000, multiplier=multiplier),
            self.anomaly("requests", current["requests"], baseline_daily.get("requests", 0.0), "requests", evidence, minimum=50, multiplier=multiplier),
            self.anomaly("image_requests", current["image_requests"], baseline_daily.get("image_requests", 0.0), "requests", evidence, minimum=10, multiplier=multiplier),
            self.anomaly("eval_runs", eval_current, eval_baseline, "runs", {**evidence, "eval_current": eval_current}, minimum=5, multiplier=multiplier),
            self.anomaly("dedicated_runtime_seconds", dedicated["dedicated_runtime_seconds"], dedicated["baseline_daily_seconds"], "seconds", {**evidence, "dedicated": dedicated["summary"]}, minimum=3600, multiplier=multiplier),
            self.anomaly("dedicated_cost_usd", dedicated["dedicated_cost_usd"], 0.0, "usd", {**evidence, "dedicated": dedicated["summary"]}, minimum=float(config.get("dedicated_cost_minimum_usd") or 10.0), multiplier=multiplier),
        ]
        rows = self.apply_state([row for row in anomalies if row])
        return {
            "generated_at": now,
            "window_seconds": window,
            "baseline_days": baseline_days,
            "current": current,
            "baseline_daily": baseline_daily,
            "evals": {"current": eval_current, "baseline_daily": round(eval_baseline, 4)},
            "dedicated": dedicated,
            "anomalies": rows,
            "summary": {"count": len(rows), "critical": len([row for row in rows if row.get("severity") == "critical"]), "high": len([row for row in rows if row.get("severity") == "high"])},
        }

    def update(self, data):
        data = data if isinstance(data, dict) else {}
        anomaly_id = str(data.get("id") or data.get("anomaly_id") or "").strip()
        action = str(data.get("action") or data.get("status") or "acknowledged").strip().lower()
        if not anomaly_id:
            raise ValueError("anomaly id is required")
        if action == "review":
            payload = self.payload()
            anomaly = next((row for row in (payload.get("anomalies") or []) if row.get("id") == anomaly_id), None)
            if not anomaly:
                raise ValueError("anomaly not found")
            review = self.create_review_item({
                "severity": anomaly.get("severity") or "high",
                "reason": "cost_anomaly",
                "title": anomaly.get("title") or "Cost anomaly",
                "source": {"type": "cost_anomaly", "id": anomaly_id},
                "evidence": anomaly,
                "actor": data.get("actor") if isinstance(data.get("actor"), dict) else {},
            })
            self.append_audit("cost_anomaly.review", actor=data.get("actor") or {}, outcome="completed", permission="cost_anomaly.update", request={"id": anomaly_id}, status=200)
            return {"review": review, "anomaly_id": anomaly_id}
        if action not in self.STATUSES:
            raise ValueError("anomaly status must be new, acknowledged, suppressed, resolved, or review")
        state = self.load_state()
        states = state.setdefault("states", {})
        states[anomaly_id] = {
            "status": action,
            "notes": str(data.get("notes") or ""),
            "actor": data.get("actor") if isinstance(data.get("actor"), dict) else {},
            "updated_at": self.clock(),
        }
        self.save_state(state)
        self.append_audit("cost_anomaly.update", actor=data.get("actor") or {}, outcome="completed", permission="cost_anomaly.update", request={"id": anomaly_id, "status": action}, status=200)
        return self.payload()
