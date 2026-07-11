import datetime
import re
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
        otel_exporter=None,
        read_traces=None,
        dedicated_events=None,
        list_eval_runs=None,
        cost_summary_payload=None,
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
        self.otel_exporter = otel_exporter
        self.read_traces = read_traces or (lambda limit=2000: [])
        self.dedicated_events = dedicated_events or (lambda limit=200: [])
        self.list_eval_runs = list_eval_runs or (lambda limit=50: [])
        self.cost_summary_payload = cost_summary_payload or (lambda: {})

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
        lines.extend(self.runtime_metrics())
        if self.otel_exporter is not None:
            try:
                self.otel_exporter.export_metrics(status, self.request_counts, len(self.tmux_sessions()))
            except Exception:
                pass
        return "\n".join(lines) + "\n"

    def runtime_metrics(self):
        traces = self.safe_call(self.read_traces, limit=2000)
        dedicated = self.safe_call(self.dedicated_events, limit=200)
        eval_runs = self.safe_call(self.list_eval_runs, limit=50)
        cost_summary = self.safe_call(self.cost_summary_payload)
        lines = []
        lines.extend(self.model_trace_metrics(traces))
        lines.extend(self.dedicated_metrics(dedicated))
        lines.extend(self.eval_metrics(eval_runs))
        lines.extend(self.cost_metrics(cost_summary))
        return lines

    def safe_call(self, fn, *args, **kwargs):
        try:
            value = fn(*args, **kwargs)
        except Exception:
            return [] if kwargs.get("limit") is not None else {}
        return value

    def model_trace_metrics(self, traces):
        request_counts = {}
        cost_totals = {}
        token_totals = {}
        latency = {}
        fallbacks = {}
        provider_errors = {}
        rate_blocks = {}
        for trace in traces if isinstance(traces, list) else []:
            if not isinstance(trace, dict):
                continue
            requested = self.label_value(trace.get("requested_model") or trace.get("model") or "unknown")
            routed = self.label_value(trace.get("routed_model") or requested)
            route = self.label_value(trace.get("endpoint_mode") or trace.get("routing_backend") or trace.get("provider") or "default")
            status = self.label_value(trace.get("status") or ("error" if int(trace.get("http_status") or 0) >= 400 else "success"))
            model = routed or requested
            request_counts[(model, route, status)] = request_counts.get((model, route, status), 0) + 1
            cost_totals[(model, route)] = cost_totals.get((model, route), 0.0) + self.number(trace.get("cost_usd"))
            latency_ms = self.number(trace.get("latency_ms"))
            if latency_ms:
                latency.setdefault((model, route), []).append(latency_ms)
            for token_type, value in self.trace_tokens(trace).items():
                token_totals[(model, token_type)] = token_totals.get((model, token_type), 0.0) + value
            reason = self.label_value(trace.get("routing_reason") or trace.get("fallback_reason") or "")
            if reason and ("fallback" in reason or requested != routed):
                fallbacks[(reason, requested, routed)] = fallbacks.get((reason, requested, routed), 0) + 1
            failure = trace.get("failure") if isinstance(trace.get("failure"), dict) else {}
            category = self.label_value(trace.get("error_category") or failure.get("category") or "")
            if status == "error":
                provider = self.label_value(trace.get("provider") or "local")
                provider_errors[(provider, model, category or "unknown")] = provider_errors.get((provider, model, category or "unknown"), 0) + 1
            if category in {"rate_limit", "rate_limited", "quota_exceeded"} or int(trace.get("http_status") or 0) == 429:
                action = self.label_value(trace.get("action") or "unknown")
                rate_blocks[(action, "operator")] = rate_blocks.get((action, "operator"), 0) + 1
        lines = [
            "# HELP matts_model_requests_total Model requests by bounded model, route, and status labels.",
            "# TYPE matts_model_requests_total counter",
        ]
        for labels, count in sorted(request_counts.items()):
            lines.append(self.metric("matts_model_requests_total", count, {"model": labels[0], "route": labels[1], "status": labels[2]}))
        lines += ["# HELP matts_model_latency_ms Model request latency histogram.", "# TYPE matts_model_latency_ms histogram"]
        for labels, values in sorted(latency.items()):
            total = 0
            for bucket in (1000, 3000, 10000):
                total = len([value for value in values if value <= bucket])
                lines.append(self.metric("matts_model_latency_ms_bucket", total, {"model": labels[0], "route": labels[1], "le": str(bucket)}))
            lines.append(self.metric("matts_model_latency_ms_bucket", len(values), {"model": labels[0], "route": labels[1], "le": "+Inf"}))
            lines.append(self.metric("matts_model_latency_ms_sum", round(sum(values), 4), {"model": labels[0], "route": labels[1]}))
            lines.append(self.metric("matts_model_latency_ms_count", len(values), {"model": labels[0], "route": labels[1]}))
        lines += ["# HELP matts_model_tokens_total Model token totals by bounded model and token type.", "# TYPE matts_model_tokens_total counter"]
        for labels, value in sorted(token_totals.items()):
            lines.append(self.metric("matts_model_tokens_total", round(value, 4), {"model": labels[0], "type": labels[1]}))
        lines += ["# HELP matts_model_cost_usd_total Model cost totals in USD.", "# TYPE matts_model_cost_usd_total counter"]
        for labels, value in sorted(cost_totals.items()):
            lines.append(self.metric("matts_model_cost_usd_total", round(value, 8), {"model": labels[0], "route": labels[1]}))
        lines += ["# HELP matts_gateway_fallbacks_total Gateway fallback decisions.", "# TYPE matts_gateway_fallbacks_total counter"]
        for labels, count in sorted(fallbacks.items()):
            lines.append(self.metric("matts_gateway_fallbacks_total", count, {"reason": labels[0], "from_model": labels[1], "to_model": labels[2]}))
        lines += ["# HELP matts_provider_errors_total Provider or local request errors.", "# TYPE matts_provider_errors_total counter"]
        for labels, count in sorted(provider_errors.items()):
            lines.append(self.metric("matts_provider_errors_total", count, {"provider": labels[0], "model": labels[1], "category": labels[2]}))
        lines += ["# HELP matts_rate_limit_blocks_total Rate-limit or quota blocks by action.", "# TYPE matts_rate_limit_blocks_total counter"]
        for labels, count in sorted(rate_blocks.items()):
            lines.append(self.metric("matts_rate_limit_blocks_total", count, {"path": labels[0], "actor_type": labels[1]}))
        return lines

    def trace_tokens(self, trace):
        usage = trace.get("usage") if isinstance(trace.get("usage"), dict) else {}
        cost = trace.get("cost") if isinstance(trace.get("cost"), dict) else {}
        return {
            "input": self.number(usage.get("input_tokens") or usage.get("prompt_tokens") or cost.get("input_tokens") or cost.get("input_tokens_est")),
            "output": self.number(usage.get("output_tokens") or usage.get("completion_tokens") or cost.get("output_tokens") or cost.get("output_tokens_est")),
            "total": self.number(usage.get("total_tokens") or cost.get("total_tokens_est")),
        }

    def dedicated_metrics(self, events):
        latest = {}
        runtime = {}
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            model = self.label_value(data.get("model") or event.get("model") or "dedicated")
            state = self.label_value(event.get("state") or event.get("type") or data.get("state") or "unknown")
            latest[model] = state
            runtime[model] = max(runtime.get(model, 0.0), self.number(data.get("runtime_seconds") or event.get("runtime_seconds")))
        lines = ["# HELP matts_dedicated_state Latest Dedicated lifecycle state.", "# TYPE matts_dedicated_state gauge"]
        for model, state in sorted(latest.items()):
            lines.append(self.metric("matts_dedicated_state", 1, {"model": model, "state": state}))
        lines += ["# HELP matts_dedicated_runtime_seconds_total Dedicated runtime seconds observed.", "# TYPE matts_dedicated_runtime_seconds_total counter"]
        for model, seconds in sorted(runtime.items()):
            lines.append(self.metric("matts_dedicated_runtime_seconds_total", round(seconds, 4), {"model": model}))
        return lines

    def eval_metrics(self, runs):
        run_counts = {}
        pass_rates = {}
        for run in runs if isinstance(runs, list) else []:
            if not isinstance(run, dict):
                continue
            dataset = self.label_value(run.get("dataset") or "unknown")
            status = "failed" if any(int(row.get("failures") or 0) for row in run.get("summary") or []) else "passed"
            run_counts[(dataset, status)] = run_counts.get((dataset, status), 0) + 1
            for row in run.get("summary") or []:
                if not isinstance(row, dict):
                    continue
                model = self.label_value(row.get("model") or "unknown")
                if row.get("pass_rate") is not None:
                    pass_rates[(dataset, model)] = self.number(row.get("pass_rate"))
        lines = ["# HELP matts_eval_runs_total Eval runs by dataset and status.", "# TYPE matts_eval_runs_total counter"]
        for labels, count in sorted(run_counts.items()):
            lines.append(self.metric("matts_eval_runs_total", count, {"dataset": labels[0], "status": labels[1]}))
        lines += ["# HELP matts_eval_pass_rate Latest eval pass rate by dataset and model.", "# TYPE matts_eval_pass_rate gauge"]
        for labels, value in sorted(pass_rates.items()):
            lines.append(self.metric("matts_eval_pass_rate", round(value, 4), {"dataset": labels[0], "model": labels[1]}))
        return lines

    def cost_metrics(self, summary):
        summary = summary if isinstance(summary, dict) else {}
        budget = summary.get("budgets") if isinstance(summary.get("budgets"), dict) else {}
        values = {
            ("used", "24h"): summary.get("last_24h_total_usd"),
            ("used", "month"): summary.get("month_total_usd"),
            ("limit", "daily"): budget.get("daily_usd"),
            ("limit", "monthly"): budget.get("monthly_usd") or budget.get("total_usd"),
        }
        lines = [
            "# HELP matts_budget_used_usd Budget spend gauges by window.",
            "# TYPE matts_budget_used_usd gauge",
            "# HELP matts_budget_limit_usd Budget limit gauges by window.",
            "# TYPE matts_budget_limit_usd gauge",
        ]
        for (kind, window), value in sorted(values.items()):
            if value in (None, ""):
                continue
            name = "matts_budget_used_usd" if kind == "used" else "matts_budget_limit_usd"
            lines.append(self.metric(name, round(self.number(value), 8), {"window": self.label_value(window)}))
        return lines

    def number(self, value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def label_value(self, value):
        value = str(value or "").strip().lower()[:64]
        value = re.sub(r"[^a-z0-9_.:-]+", "_", value)
        return value.strip("_") or "unknown"

    def metric(self, name, value, labels=None):
        labels = labels or {}
        if not labels:
            return "%s %s" % (name, value)
        label_text = ",".join('%s="%s"' % (key, str(val).replace("\\", "\\\\").replace('"', '\\"')) for key, val in sorted(labels.items()))
        return "%s{%s} %s" % (name, label_text, value)
