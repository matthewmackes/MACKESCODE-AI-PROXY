import unittest

from src.console.services.failure_taxonomy import FailureTaxonomyService
from src.console.services.provider_health import ProviderHealthService


class ProviderHealthServiceTests(unittest.TestCase):
    def service(self, **kwargs):
        return ProviderHealthService(
            digitalocean_health_snapshot=kwargs.get("digitalocean_health_snapshot") or (lambda: {
                "configured": True,
                "platform": {"indicator": "none", "description": "ok", "unresolved_incidents": []},
                "account": {"status": "active"},
                "prepay": {"status": "settled"},
            }),
            read_traces=kwargs.get("read_traces") or (lambda **_kw: []),
            dedicated_status_payload=kwargs.get("dedicated_status_payload") or (lambda poll=False: {"dedicated": {"state": "not_configured"}}),
            models_payload=kwargs.get("models_payload") or (lambda refresh_catalog=False: {"text_model_options": [], "image_model_options": []}),
            proxy_sync_payload=kwargs.get("proxy_sync_payload") or (lambda force=False: {"listening": True, "in_sync": True}),
            active_model_access_key_info=kwargs.get("active_model_access_key_info") or (lambda: {"configured": True}),
            failure_taxonomy=kwargs.get("failure_taxonomy") or FailureTaxonomyService(),
            clock=lambda: 1000.0,
        )

    def test_payload_combines_provider_account_proxy_and_incidents(self):
        service = self.service(
            digitalocean_health_snapshot=lambda: {
                "configured": True,
                "platform": {"indicator": "major", "description": "Major outage", "unresolved_incidents": [{"name": "Inference outage", "impact": "major", "shortlink": "https://stspg.io/x"}]},
                "account": {"status": "active"},
                "prepay": {"status": "settled"},
            },
            proxy_sync_payload=lambda force=False: {"listening": True, "in_sync": False, "details": {"reason": "registry stale"}},
        )

        payload = service.payload()

        self.assertEqual(payload["providers"][0]["issue_type"], "provider_outage")
        self.assertTrue(any(item["type"] == "provider_outage" for item in payload["findings"]))
        self.assertTrue(any(item["action"] == "sync_proxy" for item in payload["actions"]))

    def test_model_health_tracks_failure_rate_rate_limits_and_access(self):
        service = self.service(
            models_payload=lambda refresh_catalog=False: {"text_model_options": [
                {"id": "model-a", "display_name": "Model A"},
                {"id": "model-b", "display_name": "Model B", "access_status": "forbidden"},
            ]},
            read_traces=lambda **_kw: [
                {"requested_model": "model-a", "status": "error", "timestamp": 10, "latency_ms": 100, "error": "upstream service unavailable"},
                {"requested_model": "model-a", "status": "error", "timestamp": 20, "latency_ms": 120, "gateway_policy": {"decision": "rate_limited"}},
                {"requested_model": "model-a", "status": "ok", "timestamp": 30, "latency_ms": 80},
            ],
        )

        payload = service.payload()
        model_a = next(row for row in payload["models"] if row["id"] == "model-a")
        model_b = next(row for row in payload["models"] if row["id"] == "model-b")

        self.assertEqual(model_a["rate_limits"], 1)
        self.assertEqual(model_a["issue_type"], "rate_limit")
        self.assertEqual(model_a["failure_categories"]["provider_outage"], 1)
        self.assertEqual(model_a["failure_categories"]["rate_limit"], 1)
        self.assertTrue(any(row["category"] == "rate_limit" for row in payload["failure_categories"]))
        self.assertEqual(model_b["issue_type"], "model_access_issue")

    def test_missing_token_and_dedicated_failure_are_classified(self):
        service = self.service(
            digitalocean_health_snapshot=lambda: {"configured": False, "platform": {"indicator": "none", "unresolved_incidents": []}, "errors": ["missing token"]},
            active_model_access_key_info=lambda: {"configured": False},
            dedicated_status_payload=lambda poll=False: {"dedicated": {"state": "failed", "token_configured": False}},
        )

        payload = service.payload()

        self.assertEqual(payload["providers"][0]["issue_type"], "auth_account_issue")
        self.assertEqual(payload["dedicated"]["issue_type"], "auth_account_issue")
        self.assertTrue(any(item["action"] == "audit_model_access_key" for item in payload["actions"]))

    def test_model_access_drift_events_become_findings(self):
        service = self.service(
            models_payload=lambda refresh_catalog=False: {
                "text_model_options": [{"id": "model-a", "display_name": "Model A", "access_status": "forbidden"}],
                "model_access_drift": {"events": [{"id": "event-a", "model_id": "model-a", "title": "Model access regressed", "previous_status": "ok", "access_status": "forbidden", "severity": "high"}]},
            },
        )

        payload = service.payload()

        self.assertTrue(any(item["type"] == "model_access_drift" for item in payload["findings"]))
        self.assertTrue(any(item["action"] == "acknowledge_model_access_drift" for item in payload["actions"]))


if __name__ == "__main__":
    unittest.main()
