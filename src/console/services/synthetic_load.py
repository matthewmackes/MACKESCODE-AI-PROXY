"""Bounded synthetic load testing for model routes."""
import json
import statistics
import time
import uuid
from pathlib import Path


class SyntheticLoadTesterService:
    """Run controlled sequential load probes through the existing chat path."""

    DEFAULT_PROMPTS = [
        "Reply with one concise sentence about system readiness.",
        "Summarize this route check in exactly five words.",
    ]
    MAX_REQUESTS = 50
    MAX_CONCURRENCY = 1
    MAX_DURATION_SECONDS = 120
    MAX_BUDGET_USD = 5.0

    def __init__(
        self,
        runs_file,
        chat_completion,
        text_models,
        default_text_model,
        cost_forecast_payload=None,
        quota_planner_preview=None,
        append_audit=None,
        append_trace=None,
        clock=None,
        uuid_factory=None,
    ):
        self.runs_file = runs_file
        self.chat_completion = chat_completion
        self.text_models = text_models
        self.default_text_model = default_text_model
        self.cost_forecast_payload = cost_forecast_payload or (lambda payload: {"estimated_total_usd": 0.0})
        self.quota_planner_preview = quota_planner_preview or (lambda path, data: {"allowed": True})
        self.append_audit = append_audit or (lambda *args, **kwargs: None)
        self.append_trace = append_trace or (lambda record: record)
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4

    def path(self):
        path = Path(self.runs_file())
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def list_runs(self, limit=20):
        path = self.path()
        if not path.exists():
            return []
        rows = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-int(limit or 20):]:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
        except OSError:
            return []
        return list(reversed(rows))

    def append_run(self, run):
        with self.path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(run, sort_keys=True) + "\n")
        return run

    def request(self, data):
        data = data if isinstance(data, dict) else {}
        models = data.get("models") if isinstance(data.get("models"), list) else []
        if not models:
            models = [data.get("model") or self.default_text_model()]
        models = [str(model).strip() for model in models if str(model or "").strip()]
        prompts = data.get("prompts") if isinstance(data.get("prompts"), list) else []
        prompts = [str(prompt).strip() for prompt in prompts if str(prompt or "").strip()] or list(self.DEFAULT_PROMPTS)
        try:
            request_count = int(data.get("request_count") or len(prompts) * len(models))
        except (TypeError, ValueError):
            request_count = len(prompts) * len(models)
        try:
            concurrency = int(data.get("concurrency") or 1)
        except (TypeError, ValueError):
            concurrency = 1
        try:
            max_tokens = int(data.get("max_tokens") or 64)
        except (TypeError, ValueError):
            max_tokens = 64
        try:
            budget_cap = float(data.get("budget_cap_usd") if data.get("budget_cap_usd") not in (None, "") else self.MAX_BUDGET_USD)
        except (TypeError, ValueError):
            budget_cap = self.MAX_BUDGET_USD
        try:
            duration_cap = int(data.get("duration_cap_seconds") or self.MAX_DURATION_SECONDS)
        except (TypeError, ValueError):
            duration_cap = self.MAX_DURATION_SECONDS
        return {
            "models": models,
            "prompts": prompts,
            "request_count": max(1, request_count),
            "concurrency": max(1, concurrency),
            "max_tokens": max(1, min(max_tokens, 4096)),
            "budget_cap_usd": max(0.0, budget_cap),
            "duration_cap_seconds": max(1, duration_cap),
            "route": str(data.get("route") or "chat"),
        }

    def safety(self, request):
        errors = []
        warnings = []
        active = set(self.text_models() or [])
        unavailable = [model for model in request["models"] if model not in active]
        if unavailable:
            errors.append("Unavailable models: " + ", ".join(unavailable))
        if request["request_count"] > self.MAX_REQUESTS:
            errors.append("request_count exceeds hard limit %s" % self.MAX_REQUESTS)
        if request["concurrency"] > self.MAX_CONCURRENCY:
            errors.append("concurrency above %s is not supported by the local sequential runner" % self.MAX_CONCURRENCY)
        if request["duration_cap_seconds"] > self.MAX_DURATION_SECONDS:
            errors.append("duration_cap_seconds exceeds hard limit %s" % self.MAX_DURATION_SECONDS)
        if request["budget_cap_usd"] > self.MAX_BUDGET_USD:
            errors.append("budget_cap_usd exceeds hard limit %.2f" % self.MAX_BUDGET_USD)
        if request["request_count"] > 10:
            warnings.append("Synthetic load can consume provider quota and should be run sparingly.")
        return {"ok": not errors, "errors": errors, "warnings": warnings}

    def forecast(self, request):
        payload = {
            "action": "eval",
            "models": request["models"],
            "max_examples": request["request_count"],
            "max_tokens": request["max_tokens"],
            "dataset_id": "synthetic-load",
        }
        try:
            forecast = self.cost_forecast_payload(payload) or {}
        except Exception as exc:
            forecast = {"estimated_total_usd": 0.0, "warnings": ["Forecast unavailable: %s" % exc]}
        try:
            quota = self.quota_planner_preview("/api/chat", {"forecast": forecast, "action": "synthetic_load"}) or {}
        except Exception as exc:
            quota = {"allowed": True, "warnings": ["Quota preview unavailable: %s" % exc]}
        estimated = float(forecast.get("estimated_total_usd") or 0.0)
        if estimated > request["budget_cap_usd"]:
            quota = dict(quota)
            quota["allowed"] = False
            quota.setdefault("warnings", []).append("Forecast %.4f exceeds budget cap %.4f" % (estimated, request["budget_cap_usd"]))
        return {"forecast": forecast, "quota": quota, "estimated_total_usd": estimated}

    def preview(self, data):
        request = self.request(data)
        safety = self.safety(request)
        forecast = self.forecast(request)
        blocking = (not safety["ok"]) or (not forecast["quota"].get("allowed", True))
        return {
            "dry_run": True,
            "blocking": blocking,
            "request": request,
            "safety": safety,
            "forecast": forecast["forecast"],
            "quota": forecast["quota"],
            "estimated_total_usd": round(forecast["estimated_total_usd"], 8),
        }

    def plan_sequence(self, request):
        rows = []
        for index in range(request["request_count"]):
            model = request["models"][index % len(request["models"])]
            prompt = request["prompts"][index % len(request["prompts"])]
            rows.append({"index": index + 1, "model": model, "prompt": prompt})
        return rows

    def percentile(self, values, pct):
        if not values:
            return 0
        values = sorted(values)
        index = min(len(values) - 1, max(0, int(round((pct / 100.0) * (len(values) - 1)))))
        return values[index]

    def summarize(self, results, started_at, ended_at):
        ok = [row for row in results if row.get("ok")]
        errors = [row for row in results if not row.get("ok")]
        latencies = [float(row.get("latency_ms") or 0.0) for row in results]
        total_cost = round(sum(float(row.get("cost_usd") or 0.0) for row in results), 8)
        duration = max(0.0001, ended_at - started_at)
        categories = {}
        routes = {}
        for row in results:
            category = row.get("error_category") or ("ok" if row.get("ok") else "unknown")
            categories[category] = categories.get(category, 0) + 1
            route = row.get("route") or "unknown"
            routes[route] = routes.get(route, 0) + 1
        return {
            "requests": len(results),
            "ok": len(ok),
            "errors": len(errors),
            "error_rate": round(len(errors) / max(1, len(results)), 6),
            "latency_ms": {
                "min": round(min(latencies), 3) if latencies else 0,
                "avg": round(statistics.mean(latencies), 3) if latencies else 0,
                "p50": round(self.percentile(latencies, 50), 3),
                "p95": round(self.percentile(latencies, 95), 3),
                "max": round(max(latencies), 3) if latencies else 0,
            },
            "total_cost_usd": total_cost,
            "requests_per_second": round(len(results) / duration, 6),
            "error_categories": categories,
            "routes": routes,
        }

    def run(self, data):
        preview = self.preview(data)
        if preview["blocking"]:
            raise ValueError("synthetic load test is blocked by safety or quota policy")
        request = preview["request"]
        run_id = "load_%d_%s" % (int(self.clock()), self.uuid_factory().hex[:8])
        started_at = self.clock()
        deadline = started_at + request["duration_cap_seconds"]
        results = []
        for item in self.plan_sequence(request):
            if self.clock() >= deadline:
                results.append({"index": item["index"], "model": item["model"], "ok": False, "status": 408, "error": "duration cap reached", "error_category": "duration_cap"})
                break
            req = {
                "model": item["model"],
                "messages": [{"role": "user", "content": item["prompt"]}],
                "max_tokens": request["max_tokens"],
                "temperature": 0,
                "session_id": run_id,
            }
            before = self.clock()
            status, payload = self.chat_completion(req)
            after = self.clock()
            payload = payload if isinstance(payload, dict) else {"raw": payload}
            routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
            cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            results.append({
                "index": item["index"],
                "model": item["model"],
                "status": int(status),
                "ok": int(status) < 400,
                "latency_ms": round((after - before) * 1000, 3),
                "cost_usd": round(float(cost.get("total_cost_usd") or payload.get("cost_usd") or 0.0), 8),
                "input_tokens": usage.get("prompt_tokens") or usage.get("input_tokens") or 0,
                "output_tokens": usage.get("completion_tokens") or usage.get("output_tokens") or 0,
                "route": routing.get("backend") or routing.get("reason") or "serverless",
                "routed_model": routing.get("used") or payload.get("model") or item["model"],
                "trace_id": payload.get("trace_id"),
                "error": payload.get("message") or payload.get("error") or "",
                "error_category": payload.get("category") or payload.get("code") or ("" if int(status) < 400 else "http_%s" % status),
            })
        ended_at = self.clock()
        run = {
            "id": run_id,
            "schema_version": 1,
            "created_at": started_at,
            "ended_at": ended_at,
            "request": request,
            "preview": preview,
            "summary": self.summarize(results, started_at, ended_at),
            "results": results,
        }
        self.append_run(run)
        self.append_audit("synthetic_load.run", actor=(data or {}).get("actor") if isinstance(data, dict) else {}, outcome="completed", permission="synthetic_load_run", request={"run_id": run_id, "request": request}, status=200)
        self.append_trace({
            "action": "synthetic_load.run",
            "status": "success" if run["summary"]["errors"] == 0 else "error",
            "requested_model": ",".join(request["models"]),
            "routed_model": ",".join(sorted({row.get("routed_model") or row.get("model") for row in results})),
            "endpoint_mode": "synthetic_load",
            "session_id": run_id,
            "cost_usd": run["summary"]["total_cost_usd"],
            "usage": {"requests": run["summary"]["requests"]},
            "human_message": "Synthetic load test %s" % run_id,
            "error_category": ",".join(sorted(key for key in run["summary"]["error_categories"] if key != "ok")),
        })
        return run

    def payload(self):
        return {
            "limits": {
                "max_requests": self.MAX_REQUESTS,
                "max_concurrency": self.MAX_CONCURRENCY,
                "max_duration_seconds": self.MAX_DURATION_SECONDS,
                "max_budget_usd": self.MAX_BUDGET_USD,
            },
            "runs": self.list_runs(limit=20),
        }
