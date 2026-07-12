import tempfile
import unittest
from pathlib import Path

from src.console.services.cost_control import CostControlService


class CostControlServiceTests(unittest.TestCase):
    def service(
        self,
        root: Path,
        *,
        now=1_735_000_000.0,
        summary=None,
        local_usage=None,
        dedicated_config=None,
        dedicated_runtime=None,
        teardowns=None,
    ):
        teardown_calls = teardowns if teardowns is not None else []
        return CostControlService(
            state_file=lambda: root / "cost-control.json",
            cost_summary_payload=lambda: dict(summary or {}),
            local_usage_since=local_usage or (lambda since, current: 0.0),
            load_dedicated_config=lambda: dict(dedicated_config or {}),
            dedicated_runtime_cost_summary=lambda cfg, current: dict(dedicated_runtime or {}),
            dedicated_teardown=lambda payload: teardown_calls.append(payload) or (200, {"ok": True}),
            clock=lambda: now,
        )

    def test_status_splits_provider_total_between_dedicated_and_llm(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(
                Path(tmp),
                summary={
                    "last_24h_total_usd": 10.0,
                    "last_24h_source": "provider_billing_api",
                    "month_to_date_total_usd": 50.0,
                    "digitalocean_configured": True,
                    "account_urn_configured": True,
                },
                local_usage=lambda since, current: 1.25,
                dedicated_config={"state": "active", "price_per_hour": 1.2, "run_started_at": 1_734_999_000.0},
                dedicated_runtime={"last_24h_cost_usd": 2.0, "month_cost_usd": 8.0},
            )

            payload = service.status()

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["costs"]["daily_total_usd"], 10.0)
        self.assertEqual(payload["costs"]["monthly_total_usd"], 50.0)
        self.assertEqual(payload["costs"]["categories"]["dedicated_instances"]["monthly_usd"], 8.0)
        self.assertEqual(payload["costs"]["categories"]["llm_service"]["monthly_usd"], 42.0)
        self.assertEqual(payload["costs"]["sources"]["monthly"], "provider_billing_api")
        self.assertTrue(payload["provider"]["billing_api_configured"])

    def test_hard_threshold_pauses_and_tears_down_dedicated_once(self):
        teardowns = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.service(
                root,
                summary={"local_proxy_last_24h_usd": 110.0},
                local_usage=lambda since, current: 110.0,
                dedicated_config={"state": "active", "price_per_hour": 0.0, "run_started_at": 1_734_999_000.0},
                teardowns=teardowns,
            )
            state = service.default_state()
            state["thresholds"]["workspace:default"]["monthly_threshold_usd"] = 100.0
            service.save_state(state)

            first = service.status()
            second = service.status()

        self.assertEqual(first["status"], "paused")
        self.assertTrue(first["pause"]["active"])
        self.assertEqual(first["pause"]["reason"], "hard_monthly_threshold")
        self.assertEqual(len(teardowns), 1)
        self.assertEqual(teardowns[0]["reason"], "monthly_cost_hard_pause")
        self.assertTrue(second["pause"]["active"])
        self.assertEqual(len(teardowns), 1)

    def test_override_suppresses_hard_pause_until_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = self.service(
                root,
                now=1_735_000_000.0,
                summary={"local_proxy_last_24h_usd": 110.0},
                local_usage=lambda since, current: 110.0,
                dedicated_config={"state": "active"},
            )
            state = service.default_state()
            state["thresholds"]["workspace:default"]["monthly_threshold_usd"] = 100.0
            service.save_state(state)

            payload = service.override({"duration_minutes": 30}, actor={"id": "model-admin"})

        self.assertEqual(payload["status"], "hard")
        self.assertFalse(payload["pause"]["active"])
        self.assertTrue(payload["pause"]["override"]["active"])
        self.assertEqual(payload["pause"]["override"]["override_by"], "model-admin")


if __name__ == "__main__":
    unittest.main()
