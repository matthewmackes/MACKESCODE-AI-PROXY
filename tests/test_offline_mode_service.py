import unittest

from src.console.services.offline_mode import OfflineModeService


class OfflineModeServiceTests(unittest.TestCase):
    def service(self, *, provider=None, catalog=None, now=1000):
        return OfflineModeService(
            provider_health_payload=lambda: provider if provider is not None else {"providers": [{"status": "healthy", "issue_type": "none"}], "findings": []},
            serverless_catalog_payload=lambda force=False: catalog if catalog is not None else {"ok": True, "source": "https://inference.do-ai.run/v1/models", "fetched_at": 990, "payload": {"data": [{"id": "model-a"}]}, "error": ""},
            models_payload=lambda refresh_catalog=False: {"models": [{"id": "model-a"}]},
            list_eval_datasets=lambda: [{"id": "smoke"}],
            list_eval_runs=lambda limit=10: [{"id": "run-a"}],
            clock=lambda: now,
        )

    def test_online_payload_reports_fresh_cache_and_local_workflows(self):
        payload = self.service().payload()

        self.assertEqual(payload["mode"], "online")
        self.assertEqual(payload["cache"]["serverless_catalog"]["confidence"], "fresh")
        self.assertFalse(payload["ui_policy"]["disable_live_cloud_actions"])
        self.assertTrue(all(row["available"] for row in payload["local_workflows"]))

    def test_degraded_when_provider_uses_stale_catalog_cache(self):
        payload = self.service(
            provider={"providers": [{"status": "degraded", "issue_type": "provider_outage"}], "findings": [{"type": "provider_outage"}]},
            catalog={"ok": False, "source": "cache_after_fetch_error", "fetched_at": 1, "payload": {"data": [{"id": "cached"}]}, "error": "offline"},
            now=200000,
        ).payload()

        self.assertEqual(payload["mode"], "degraded")
        self.assertIn("using_stale_serverless_cache", payload["reasons"])
        self.assertEqual(payload["cache"]["serverless_catalog"]["confidence"], "stale")
        self.assertTrue(payload["ui_policy"]["confirm_live_cloud_actions"])

    def test_offline_when_provider_and_catalog_are_unavailable_without_cache(self):
        payload = self.service(
            provider={"providers": [{"status": "degraded", "issue_type": "auth_account_issue"}], "findings": []},
            catalog={"ok": False, "source": "fallback", "fetched_at": 0, "payload": {"data": []}, "error": "network down"},
        ).payload()

        self.assertEqual(payload["mode"], "offline")
        self.assertTrue(payload["ui_policy"]["disable_live_cloud_actions"])
        self.assertTrue(all(row["guarded"] for row in payload["live_cloud_actions"]))
        self.assertEqual(payload["cache"]["serverless_catalog"]["confidence"], "empty")


if __name__ == "__main__":
    unittest.main()
