import datetime
import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.cost_forecast import CostForecastService


class CostForecastServiceTests(unittest.TestCase):
    def service(self, tmp, budgets=None, summary=None, dedicated=None):
        budget_path = Path(tmp) / "budgets.json"
        if budgets is not None:
            budget_path.write_text(json.dumps(budgets), encoding="utf-8")
        models = [
            {"id": "model-a", "type": "text", "pricing": {"input": 1.0, "output": 2.0}, "max_output_tokens": 1000},
            {"id": "model-b", "type": "text", "pricing": {"input": 0.5, "output": 1.0}},
            {"id": "image-a", "type": "image", "pricing": {"image": 0.08}},
            {"id": "missing", "type": "text", "pricing": {}},
        ]
        dataset = {
            "id": "smoke",
            "examples": [
                {"id": "one", "input": "short prompt"},
                {"id": "two", "input": "another short prompt"},
            ],
        }
        now = datetime.datetime(2026, 7, 9, 12, tzinfo=datetime.timezone.utc).timestamp()
        return CostForecastService(
            model_registry=lambda: models,
            default_text_model=lambda: "model-a",
            default_image_model=lambda: "image-a",
            load_eval_dataset=lambda dataset_id: dataset,
            cost_summary_payload=lambda: summary or {"last_24h_total_usd": 0.25, "month_to_date_total_usd": 5.0, "last_24h_source": "local"},
            budget_file=lambda: budget_path,
            load_dedicated_config=lambda: dedicated or {"state": "active", "price_per_hour": 2.0},
            dedicated_runtime_cost_summary=lambda cfg, now: {"hourly_usd": float(cfg.get("price_per_hour") or 0)},
            clock=lambda: now,
        )

    def test_text_forecast_uses_model_pricing_and_max_output_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            forecast = self.service(tmp).forecast({"action": "chat", "payload": {"model": "model-a", "prompt": "hello world", "max_tokens": 10}})

        self.assertEqual(forecast["action"], "chat")
        self.assertGreater(forecast["estimated_total_usd"], 0)
        item = forecast["line_items"][0]
        self.assertEqual(item["model"], "model-a")
        self.assertEqual(item["output_tokens_est"], 10)
        self.assertEqual(item["pricing"], {"input": 1.0, "output": 2.0})

    def test_image_and_eval_forecasts_account_for_batch_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            image = service.forecast({"action": "image", "payload": {"model": "image-a", "count": 3}})
            eval_run = service.forecast({"action": "eval", "payload": {"dataset_id": "smoke", "models": ["model-a", "model-b"], "max_tokens": 20}})

        self.assertEqual(image["estimated_total_usd"], 0.24)
        self.assertEqual(image["line_items"][0]["images"], 3)
        self.assertEqual(len(eval_run["line_items"]), 2)
        self.assertEqual(sum(item["requests"] for item in eval_run["line_items"]), 4)
        self.assertGreater(eval_run["estimated_total_usd"], 0)

    def test_budget_warnings_distinguish_current_estimate_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, budgets={"daily_usd": 0.30, "monthly_usd": 6.0}, summary={"last_24h_total_usd": 0.25, "month_to_date_total_usd": 5.9})
            forecast = service.forecast({"action": "image", "payload": {"model": "image-a", "count": 2}})

        warnings = forecast["budget_impact"]["warnings"]
        self.assertTrue(any(item["scope"] == "daily" and item["severity"] == "error" for item in warnings))
        self.assertTrue(any(item["scope"] == "monthly" and item["severity"] == "error" for item in warnings))
        daily = next(item for item in warnings if item["scope"] == "daily")
        self.assertEqual(daily["current_usd"], 0.25)
        self.assertEqual(daily["estimate_usd"], 0.16)
        self.assertEqual(daily["limit_usd"], 0.3)

    def test_missing_pricing_adds_warning_and_zero_estimate(self):
        with tempfile.TemporaryDirectory() as tmp:
            forecast = self.service(tmp).forecast({"action": "chat", "payload": {"model": "missing", "prompt": "hello"}})

        self.assertEqual(forecast["estimated_total_usd"], 0.0)
        self.assertFalse(forecast["line_items"][0]["pricing_available"])
        self.assertTrue(any(item["scope"] == "pricing" for item in forecast["budget_impact"]["warnings"]))

    def test_dedicated_forecast_and_actual_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, dedicated={"state": "active", "price_per_hour": 4.0})
            forecast = service.forecast({"action": "dedicated", "payload": {"forecast_hours": 2}})
            actual = service.compare_actual(forecast, 7.5)

        self.assertEqual(forecast["estimated_total_usd"], 8.0)
        self.assertEqual(forecast["burn_rate"]["active_dedicated_hourly_usd"], 4.0)
        self.assertEqual(actual["estimated_usd"], 8.0)
        self.assertEqual(actual["actual_usd"], 7.5)
        self.assertEqual(actual["delta_usd"], -0.5)


if __name__ == "__main__":
    unittest.main()
