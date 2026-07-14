import unittest

from src.console.services.digitalocean import DigitalOceanHealthService
from src.console.services.operational_store import OperationalStore


class DigitalOceanHealthServiceTests(unittest.TestCase):
    def service(self, public_json=None, do_get=None, token="do-token", cache=None, now=1000, load_dedicated_config=None, operational_store=None):
        return DigitalOceanHealthService(
            public_json_url=public_json or (lambda url, timeout=12: (200, {})),
            do_get=do_get or (lambda path, token, query=None, timeout=30: (200, {})),
            digitalocean_token=lambda: token,
            cache=cache if cache is not None else {"ts": 0, "payload": None},
            clock=lambda: now,
            load_dedicated_config=load_dedicated_config,
            operational_store=operational_store,
        )

    def test_mask_email_preserves_domain_and_masks_name(self):
        service = self.service()
        self.assertEqual(service.mask_email("m@example.com"), "m*@example.com")
        self.assertEqual(service.mask_email("matt@example.com"), "ma***t@example.com")
        self.assertEqual(service.mask_email("not-an-email"), "not-an-email")

    def test_platform_status_collects_status_and_incidents(self):
        def public_json(url, timeout=12):
            if url.endswith("/status.json"):
                return 200, {
                    "page": {"updated_at": "2026-07-08T00:00:00Z"},
                    "status": {"indicator": "minor", "description": "Partial outage"},
                }
            return 200, {"incidents": [
                {"name": "Incident A", "status": "investigating", "impact": "minor", "updated_at": "now", "shortlink": "https://stspg.io/a"},
                "bad-row",
            ]}

        payload = self.service(public_json=public_json).platform_status()

        self.assertTrue(payload["reachable"])
        self.assertEqual(payload["indicator"], "minor")
        self.assertEqual(payload["description"], "Partial outage")
        self.assertEqual(payload["unresolved_incidents"][0]["name"], "Incident A")

    def test_platform_status_reports_errors(self):
        service = self.service(public_json=lambda url, timeout=12: (503, {"error": "down"}))
        payload = service.platform_status()

        self.assertFalse(payload["reachable"])
        self.assertEqual(len(payload["errors"]), 2)

    def test_snapshot_handles_missing_token_and_caches_result(self):
        calls = []

        def public_json(url, timeout=12):
            calls.append(url)
            return 200, {"status": {"indicator": "none", "description": "All Systems Operational"}}

        cache = {"ts": 0, "payload": None}
        first = self.service(public_json=public_json, token="", cache=cache, now=1000).snapshot()
        second = self.service(public_json=public_json, token="", cache=cache, now=1030).snapshot()

        self.assertFalse(first["configured"])
        self.assertIn("DigitalOcean token", first["errors"][0])
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 2)

    def test_missing_token_snapshot_is_persisted(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            store = OperationalStore(Path(tmp) / "ops.sqlite3", clock=lambda: 1000)
            self.service(token="", operational_store=store).snapshot()
            snapshots = store.latest_digitalocean_snapshots(limit=5)

        self.assertEqual(len(snapshots), 1)
        self.assertFalse(snapshots[0]["configured"])

    def test_snapshot_loads_account_and_prepay_status(self):
        calls = []

        def do_get(path, token, query=None, timeout=30):
            calls.append((path, token, timeout))
            if path == "/v2/account":
                return 200, {"account": {
                    "status": "active",
                    "status_message": "ok",
                    "email": "matt@example.com",
                    "email_verified": True,
                    "droplet_limit": 25,
                    "floating_ip_limit": 3,
                    "team_uuid": "team-1",
                }}
            return 200, {
                "account_balance": "-5.25",
                "month_to_date_balance": "2.50",
                "month_to_date_usage": "12.75",
                "generated_at": "2026-07-08T00:00:00Z",
            }

        service = self.service(
            public_json=lambda url, timeout=12: (200, {"status": {"indicator": "none", "description": "ok"}}),
            do_get=do_get,
        )
        payload = service.snapshot()

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["account"]["email"], "ma***t@example.com")
        self.assertEqual(payload["prepay"]["account_balance"], -5.25)
        self.assertEqual(payload["prepay"]["status"], "credit_available")
        self.assertEqual([call[0] for call in calls], ["/v2/account", "/v2/customers/my/balance"])

    def test_monitoring_metrics_parse_prometheus_values(self):
        calls = []

        def do_get(path, token, query=None, timeout=30):
            calls.append((path, query))
            return 200, {"data": {"result": [{"values": [[900, "1.5"], [1000, "2.5"]]}]}}

        payload = self.service(
            do_get=do_get,
            load_dedicated_config=lambda: {"server_id": "droplet-1", "state": "active"},
        ).monitoring_metrics("do-token", now=1000)

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["metrics"]["cpu"]["samples"], 2)
        self.assertEqual(payload["metrics"]["cpu"]["average"], 2.0)
        self.assertEqual(calls[0][1], {"host_id": "droplet-1", "start": -2600, "end": 1000})

    def test_monitoring_metrics_degrades_without_host_id(self):
        payload = self.service(load_dedicated_config=lambda: {"state": "deleted"}).monitoring_metrics("do-token", now=1000)

        self.assertFalse(payload["configured"])
        self.assertIn("No Dedicated Inference host id", payload["errors"][0])

    def test_snapshot_records_account_and_balance_errors(self):
        service = self.service(
            public_json=lambda url, timeout=12: (200, {}),
            do_get=lambda path, token, query=None, timeout=30: (403, {"id": "forbidden"}),
        )
        payload = service.snapshot()

        self.assertEqual(payload["errors"], [
            {"account_status": 403, "response": {"id": "forbidden"}},
            {"balance_status": 403, "response": {"id": "forbidden"}},
        ])


if __name__ == "__main__":
    unittest.main()
