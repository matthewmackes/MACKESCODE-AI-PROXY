import datetime
import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.usage import UsageService, _TTLCache


class MutableClock:
    """A monkeypatchable time source for deterministic TTL-cache tests."""

    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class UsageServiceTests(unittest.TestCase):
    def service(self, tmp, rows=None, do_get=None, token="", account_urn="", clock=None, tail_jsonl=None):
        cost_path = Path(tmp) / "usage.jsonl"
        budget_path = Path(tmp) / "budget.json"
        rows = rows or []
        with cost_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        def default_tail_jsonl(path, limit=80):
            loaded = []
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                loaded.append(json.loads(line))
            return loaded

        return UsageService(
            cost_file=lambda: cost_path,
            budget_file=lambda: budget_path,
            tail_jsonl=tail_jsonl or default_tail_jsonl,
            do_get=do_get or (lambda path, token, query=None, timeout=30: (200, {})),
            digitalocean_token=lambda: token,
            digitalocean_account_urn=lambda: account_urn,
            digitalocean_health_snapshot=lambda: {"account": {"status": "active"}, "prepay": {"month_to_date_usage": 12.34}, "errors": []},
            load_dedicated_config=lambda: {"price_per_hour": 2.0},
            dedicated_runtime_cost_summary=lambda cfg, now: {"month_cost_usd": 3.0, "last_24h_cost_usd": 1.0, "month_seconds": 5400},
            clock=clock or (lambda: datetime.datetime(2026, 7, 8, 12, tzinfo=datetime.timezone.utc).timestamp()),
            # Fresh per-service caches so tests do not leak state through the
            # module-level singletons.
            insights_cache=_TTLCache(),
            usage_rows_cache=_TTLCache(),
        )

    def test_local_usage_report_groups_by_day_and_model(self):
        ts = datetime.datetime(2026, 7, 8, 16, tzinfo=datetime.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, rows=[
                {"ts": ts, "requested_model": "model-a", "cost": {"total_cost_usd": 0.25}},
                {"ts": ts, "upstream_model": "model-b", "cost": {"total_cost_usd": 0.75}},
            ])

            report = service.local_usage_report(datetime.date(2026, 7, 8), datetime.date(2026, 7, 8))

        self.assertEqual(report["total_usd"], 1.0)
        self.assertEqual(report["daily"], [{"date": "2026-07-08", "amount_usd": 1.0}])
        self.assertEqual(report["by_model"][0], {"model": "model-b", "amount_usd": 0.75})

    def test_cost_summary_uses_billing_insights_when_available(self):
        calls = []

        def do_get(path, token, query=None, timeout=30):
            calls.append((path, token, query, timeout))
            return 200, {"data": [{"amount_usd": "4.50"}]}

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, do_get=do_get, token="tok", account_urn="do:team:abc")
            summary = service.cost_summary_payload()

        self.assertEqual(summary["last_24h_total_usd"], 4.5)
        self.assertEqual(summary["last_24h_source"], "digitalocean_billing_insights")
        self.assertEqual(summary["month_to_date_total_usd"], 12.34)
        self.assertTrue(calls[0][0].startswith("/v2/billing/do:team:abc/insights/"))

    def test_digitalocean_report_gracefully_handles_missing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.service(tmp).digitalocean_report({"days": 3})

        self.assertFalse(report["digitalocean_configured"])
        self.assertEqual(report["days"], 3)
        self.assertIn("DIGITALOCEAN_TOKEN", report["errors"][0])

    def test_save_budget_persists_numeric_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            saved = service.save_budget({"daily_usd": "5", "monthly_usd": "", "total_usd": 20})
            data = json.loads((Path(tmp) / "budget.json").read_text(encoding="utf-8"))

        self.assertEqual(saved, {"daily_usd": 5.0, "total_usd": 20.0})
        self.assertEqual(data, saved)

    def test_cost_summary_caches_digitalocean_call_within_ttl(self):
        calls = []

        def do_get(path, token, query=None, timeout=30):
            calls.append(path)
            return 200, {"data": [{"amount_usd": "4.50"}]}

        clock = MutableClock(datetime.datetime(2026, 7, 8, 12, tzinfo=datetime.timezone.utc).timestamp())
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, do_get=do_get, token="tok", account_urn="do:team:abc", clock=clock)
            first = service.cost_summary_payload()
            clock.value += 30  # still inside the default 90s TTL, same UTC day
            second = service.cost_summary_payload()

        # Two consecutive polls, but only one live DigitalOcean billing call.
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["last_24h_total_usd"], 4.5)
        self.assertEqual(second["last_24h_total_usd"], 4.5)
        self.assertEqual(second["last_24h_source"], "digitalocean_billing_insights")

    def test_cost_summary_refreshes_digitalocean_call_after_ttl(self):
        calls = []

        def do_get(path, token, query=None, timeout=30):
            calls.append(path)
            return 200, {"data": [{"amount_usd": "4.50"}]}

        clock = MutableClock(datetime.datetime(2026, 7, 8, 12, tzinfo=datetime.timezone.utc).timestamp())
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, do_get=do_get, token="tok", account_urn="do:team:abc", clock=clock)
            service.cost_summary_payload()
            clock.value += 200  # past the 90s TTL, still the same UTC day
            service.cost_summary_payload()

        self.assertEqual(len(calls), 2)

    def test_cost_summary_returns_local_totals_when_digitalocean_fails(self):
        calls = []

        def do_get(path, token, query=None, timeout=30):
            calls.append(path)
            return 500, {"error": "boom"}

        now = datetime.datetime(2026, 7, 8, 12, tzinfo=datetime.timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(
                tmp,
                rows=[{"ts": now - 3600, "requested_model": "model-a", "cost": {"total_cost_usd": 0.5}}],
                do_get=do_get,
                token="tok",
                account_urn="do:team:abc",
            )
            summary = service.cost_summary_payload()

        # DO was attempted, but the failure falls back to local + dedicated totals.
        self.assertTrue(calls)
        self.assertEqual(summary["last_24h_source"], "local_proxy_plus_dedicated_estimate")
        self.assertEqual(summary["local_proxy_last_24h_usd"], 0.5)
        self.assertEqual(summary["last_24h_total_usd"], round(0.5 + 1.0, 8))

    def test_repeated_usage_reads_share_single_parse(self):
        parses = {"count": 0}
        now = datetime.datetime(2026, 7, 8, 12, tzinfo=datetime.timezone.utc).timestamp()

        def counting_tail(path, limit=80):
            parses["count"] += 1
            loaded = []
            for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
                loaded.append(json.loads(line))
            return loaded

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(
                tmp,
                rows=[{"ts": now - 3600, "requested_model": "model-a", "cost": {"total_cost_usd": 0.5}}],
                clock=lambda: now,
                tail_jsonl=counting_tail,
            )
            report = service.local_usage_report(datetime.date(2026, 7, 8), datetime.date(2026, 7, 8))
            since_total = service.local_usage_since(now - 86400, now)

        # SQLite backfill now serves both aggregates without using the legacy
        # tail parser at all.
        self.assertEqual(parses["count"], 0)
        self.assertEqual(report["total_usd"], 0.5)
        self.assertEqual(since_total, 0.5)


if __name__ == "__main__":
    unittest.main()
