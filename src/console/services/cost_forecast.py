"""Pre-run cost forecast helpers for console actions."""
import datetime
import hashlib
import json
import time


class CostForecastService:
    """Estimate action cost from local model pricing and current budget state."""

    warning_threshold = 0.8

    def __init__(
        self,
        model_registry,
        default_text_model,
        default_image_model,
        load_eval_dataset,
        cost_summary_payload,
        budget_file,
        load_dedicated_config,
        dedicated_runtime_cost_summary,
        clock=None,
    ):
        self.model_registry = model_registry
        self.default_text_model = default_text_model
        self.default_image_model = default_image_model
        self.load_eval_dataset = load_eval_dataset
        self.cost_summary_payload = cost_summary_payload
        self.budget_file = budget_file
        self.load_dedicated_config = load_dedicated_config
        self.dedicated_runtime_cost_summary = dedicated_runtime_cost_summary
        self.clock = clock or time.time

    def models(self):
        rows = self.model_registry() if callable(self.model_registry) else self.model_registry
        result = {}
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            result[str(row["id"])] = row
            for alias in row.get("aliases") or []:
                result[str(alias)] = row
        return result

    def read_budgets(self):
        path = self.budget_file()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def token_estimate(self, value):
        if isinstance(value, list):
            text = " ".join(self.message_text(item) for item in value)
        elif isinstance(value, dict):
            text = self.message_text(value)
        else:
            text = str(value or "")
        words = len(text.split())
        return max(1, int(words * 1.3))

    def message_text(self, message):
        if not isinstance(message, dict):
            return str(message or "")
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item or ""))
            return " ".join(parts)
        return str(content or "")

    def max_output_tokens(self, data, model):
        raw = data.get("max_tokens") if isinstance(data, dict) else None
        if raw in (None, "") and isinstance(model, dict):
            raw = model.get("max_output_tokens")
        try:
            return max(1, int(raw or 512))
        except (TypeError, ValueError):
            return 512

    def text_prompt(self, data):
        if not isinstance(data, dict):
            return ""
        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        prompt = str(data.get("prompt") or "").strip()
        return " ".join([self.message_text(item) for item in messages] + ([prompt] if prompt else []))

    def pricing_status(self, pricing, required):
        pricing = pricing if isinstance(pricing, dict) else {}
        missing = [key for key in required if key not in pricing]
        zero = all(float(pricing.get(key) or 0) == 0 for key in required)
        return {
            "missing": missing,
            "available": not missing and not zero,
            "zero_priced": not missing and zero,
        }

    def estimate_text_request(self, model_id, prompt_text, max_output_tokens=512, multiplier=1):
        model = self.models().get(str(model_id or "")) or {}
        pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
        status = self.pricing_status(pricing, ("input", "output"))
        multiplier = max(1, int(multiplier or 1))
        input_tokens = self.token_estimate(prompt_text) * multiplier
        output_tokens = max(1, int(max_output_tokens or 512)) * multiplier
        input_cost = input_tokens * float(pricing.get("input") or 0.0) / 1_000_000
        output_cost = output_tokens * float(pricing.get("output") or 0.0) / 1_000_000
        return {
            "kind": "serverless_text",
            "model": str(model_id or ""),
            "display_name": model.get("display_name") or str(model_id or ""),
            "requests": multiplier,
            "input_tokens_est": input_tokens,
            "output_tokens_est": output_tokens,
            "input_cost_usd": round(input_cost, 8),
            "output_cost_usd": round(output_cost, 8),
            "estimated_cost_usd": round(input_cost + output_cost, 8),
            "pricing": {"input": pricing.get("input"), "output": pricing.get("output")},
            "pricing_available": status["available"] or status["zero_priced"],
            "pricing_missing": status["missing"],
            "zero_priced": status["zero_priced"],
        }

    def estimate_image_request(self, data):
        model_id = str((data or {}).get("model") or self.default_image_model())
        model = self.models().get(model_id) or {}
        pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
        try:
            count = max(1, min(100, int((data or {}).get("count") or (data or {}).get("n") or 1)))
        except (TypeError, ValueError):
            count = 1
        unit = float(pricing.get("image") or 0.0)
        status = self.pricing_status(pricing, ("image",))
        return {
            "kind": "serverless_image",
            "model": model_id,
            "display_name": model.get("display_name") or model_id,
            "images": count,
            "unit_cost_usd": round(unit, 8),
            "estimated_cost_usd": round(unit * count, 8),
            "pricing": {"image": pricing.get("image")},
            "pricing_available": status["available"] or status["zero_priced"],
            "pricing_missing": status["missing"],
            "zero_priced": status["zero_priced"],
        }

    def forecast_chat(self, data):
        model_id = str((data or {}).get("model") or self.default_text_model())
        model = self.models().get(model_id) or {}
        return [self.estimate_text_request(model_id, self.text_prompt(data), self.max_output_tokens(data or {}, model))]

    def forecast_comparison(self, data):
        models = (data or {}).get("models") if isinstance((data or {}).get("models"), list) else []
        if not models:
            models = [self.default_text_model()]
        prompt = self.text_prompt(data or {})
        registry = self.models()
        return [
            self.estimate_text_request(str(model), prompt, self.max_output_tokens(data or {}, registry.get(str(model)) or {}))
            for model in models[:5]
            if str(model or "").strip()
        ]

    def forecast_eval(self, data):
        data = data or {}
        dataset_id = data.get("dataset_id") or "smoke"
        dataset = self.load_eval_dataset(dataset_id)
        examples = dataset.get("examples") or []
        try:
            max_examples = max(1, int(data.get("max_examples") or len(examples)))
        except (TypeError, ValueError):
            max_examples = len(examples) or 1
        examples = examples[:max_examples]
        models = data.get("models") if isinstance(data.get("models"), list) else []
        if not models:
            models = [self.default_text_model()]
        max_tokens = self.max_output_tokens(data, {})
        prompt_by_model = {}
        for model in models:
            prompt_by_model[str(model)] = " ".join(str(example.get("input") or "") for example in examples)
        items = []
        for model, prompt in prompt_by_model.items():
            item = self.estimate_text_request(model, prompt, max_tokens, multiplier=1)
            item["kind"] = "eval_text"
            item["requests"] = len(examples)
            item["output_tokens_est"] = max_tokens * len(examples)
            pricing = item.get("pricing") or {}
            item["output_cost_usd"] = round(item["output_tokens_est"] * float(pricing.get("output") or 0.0) / 1_000_000, 8)
            item["estimated_cost_usd"] = round(item["input_cost_usd"] + item["output_cost_usd"], 8)
            items.append(item)
        return items

    def forecast_dedicated(self, data):
        cfg = dict(self.load_dedicated_config() or {})
        cfg.update(data or {})
        try:
            hourly = float(cfg.get("price_per_hour") or cfg.get("hourly_usd") or 0.0)
        except (TypeError, ValueError):
            hourly = 0.0
        try:
            hours = max(0.0, float(cfg.get("estimated_hours") or cfg.get("forecast_hours") or 1.0))
        except (TypeError, ValueError):
            hours = 1.0
        return [{
            "kind": "dedicated_runtime",
            "model": cfg.get("model_id") or "dedicated-inference",
            "display_name": cfg.get("display_name") or cfg.get("name") or "Dedicated Inference",
            "hours": round(hours, 4),
            "hourly_cost_usd": round(hourly, 8),
            "estimated_cost_usd": round(hourly * hours, 8),
            "pricing_available": hourly > 0,
            "pricing_missing": [] if hourly > 0 else ["price_per_hour"],
            "zero_priced": hourly == 0,
        }]

    def burn_rate_projection(self, estimate_usd):
        summary = self.cost_summary_payload() or {}
        now = self.clock()
        dedicated_cfg = self.load_dedicated_config() or {}
        dedicated_runtime = self.dedicated_runtime_cost_summary(dedicated_cfg, now) or {}
        hourly_dedicated = float(dedicated_runtime.get("hourly_usd") or 0.0)
        dedicated_active = str(dedicated_cfg.get("state") or "") in {"new", "creating", "provisioning", "active", "idle_warning", "draining", "cooldown", "tearing_down"}
        last_24h = float(summary.get("last_24h_total_usd") or 0.0)
        hourly_rate = (last_24h / 24.0) + (hourly_dedicated if dedicated_active else 0.0)
        today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
        next_month = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        days_left = max(1, (next_month - today).days)
        month_to_date = summary.get("month_to_date_total_usd")
        month_base = float(month_to_date or 0.0)
        return {
            "last_24h_usd": round(last_24h, 8),
            "active_dedicated_hourly_usd": round(hourly_dedicated if dedicated_active else 0.0, 8),
            "projected_daily_usd": round((hourly_rate * 24.0) + estimate_usd, 8),
            "projected_monthly_usd": round(month_base + (hourly_rate * 24.0 * days_left) + estimate_usd, 8),
            "month_to_date_usd": None if month_to_date is None else round(month_base, 8),
            "days_remaining_in_month": days_left,
            "source": summary.get("last_24h_source") or "local_estimate",
        }

    def budget_impact(self, estimate_usd, line_items):
        summary = self.cost_summary_payload() or {}
        budgets = self.read_budgets()
        current_day = float(summary.get("last_24h_total_usd") or 0.0)
        current_month = summary.get("month_to_date_total_usd")
        current_month = None if current_month is None else float(current_month)
        warnings = []
        missing = [item for item in line_items if item.get("pricing_missing") or item.get("zero_priced")]
        if missing:
            warnings.append({
                "severity": "warning",
                "scope": "pricing",
                "message": "One or more selected models have missing or zero pricing; the estimate may understate actual spend.",
                "models": [item.get("model") for item in missing],
            })
        for scope, current, limit in (
            ("daily", current_day, budgets.get("daily_usd")),
            ("monthly", current_month, budgets.get("monthly_usd") or budgets.get("total_usd")),
        ):
            if current is None or limit in (None, ""):
                continue
            try:
                limit = float(limit)
            except (TypeError, ValueError):
                continue
            if limit <= 0:
                continue
            projected = current + estimate_usd
            percent = projected / limit
            if percent >= 1.0 or percent >= self.warning_threshold:
                warnings.append({
                    "severity": "error" if percent >= 1.0 else "warning",
                    "scope": scope,
                    "message": "%s spend would be %s of the configured %s limit after this action." % (scope.title(), round(percent * 100, 2), scope),
                    "estimate_usd": round(estimate_usd, 8),
                    "current_usd": round(current, 8),
                    "projected_usd": round(projected, 8),
                    "limit_usd": round(limit, 8),
                    "percent": round(percent * 100, 2),
                })
        return {
            "estimate_usd": round(estimate_usd, 8),
            "current_last_24h_usd": round(current_day, 8),
            "current_month_to_date_usd": None if current_month is None else round(current_month, 8),
            "daily_limit_usd": budgets.get("daily_usd"),
            "monthly_limit_usd": budgets.get("monthly_usd") or budgets.get("total_usd"),
            "warnings": warnings,
        }

    def forecast_id(self, action, data, total):
        material = json.dumps({"action": action, "data": data, "total": total, "ts": int(self.clock())}, sort_keys=True, default=str)
        return "forecast_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def forecast(self, request):
        request = request if isinstance(request, dict) else {}
        action = str(request.get("action") or "chat").strip().lower()
        data = request.get("payload") if isinstance(request.get("payload"), dict) else request
        if action in {"chat", "message"}:
            line_items = self.forecast_chat(data)
        elif action in {"comparison", "compare", "chat_compare"}:
            line_items = self.forecast_comparison(data)
        elif action in {"eval", "eval_run"}:
            line_items = self.forecast_eval(data)
        elif action in {"image", "images", "generate", "image_generation"}:
            line_items = [self.estimate_image_request(data)]
        elif action in {"dedicated", "dedicated_build"}:
            line_items = self.forecast_dedicated(data)
        else:
            raise ValueError("Unsupported forecast action: %s" % action)
        total = round(sum(float(item.get("estimated_cost_usd") or 0.0) for item in line_items), 8)
        return {
            "forecast_id": self.forecast_id(action, data, total),
            "action": action,
            "estimated_total_usd": total,
            "line_items": line_items,
            "budget_impact": self.budget_impact(total, line_items),
            "burn_rate": self.burn_rate_projection(total),
            "approximate": True,
            "assumptions": [
                "Text input tokens are estimated from local word counts.",
                "Text output cost assumes max_tokens are fully used.",
                "Dedicated build estimates include one hour unless forecast_hours is provided.",
                "DigitalOcean billing data can lag behind local proxy traces.",
            ],
        }

    def compare_actual(self, forecast, actual_usd):
        if not isinstance(forecast, dict):
            return {}
        try:
            estimated = float(forecast.get("estimated_total_usd"))
        except (TypeError, ValueError):
            return {}
        try:
            actual = float(actual_usd or 0.0)
        except (TypeError, ValueError):
            actual = 0.0
        return {
            "forecast_id": forecast.get("forecast_id") or "",
            "estimated_usd": round(estimated, 8),
            "actual_usd": round(actual, 8),
            "delta_usd": round(actual - estimated, 8),
            "delta_percent": None if estimated == 0 else round(((actual - estimated) / estimated) * 100, 2),
        }
