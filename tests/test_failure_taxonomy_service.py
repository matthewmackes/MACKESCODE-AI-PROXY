import unittest

from src.console.services.failure_taxonomy import FailureTaxonomyService


class FailureTaxonomyServiceTests(unittest.TestCase):
    def test_classifies_provider_and_local_failures(self):
        service = FailureTaxonomyService()

        self.assertEqual(service.classify({"error": "Too many requests from provider"}, status=429)["category"], "rate_limit")
        self.assertEqual(service.classify({"message": "context length exceeded for model"})["category"], "context_overflow")
        self.assertEqual(service.classify({"routing_reason": "rate_limit_exceeded"})["category"], "rate_limit")
        self.assertEqual(service.classify({"issue_type": "model_access_drift"})["category"], "registry_drift")
        self.assertEqual(service.classify({"error": "local proxy connection refused"})["category"], "local_proxy")
        self.assertEqual(service.classify({"error": "Dedicated endpoint not ready"})["category"], "dedicated_not_ready")
        self.assertEqual(service.classify({"error": "invalid JSON in tool call"})["category"], "malformed_tool_call")

    def test_decorate_adds_hint_and_redacts_diagnostics(self):
        service = FailureTaxonomyService()
        payload = service.decorate({
            "message": "missing token",
            "details": {"authorization": "Bearer secret", "prompt": "private prompt", "safe": "ok"},
        }, status=401, trace_id="trace-a")

        self.assertEqual(payload["category"], "auth")
        self.assertEqual(payload["failure"]["category"], "auth")
        self.assertEqual(payload["failure"]["trace_id"], "trace-a")
        self.assertIn("suggested_fix", payload["failure"])
        raw = payload["diagnostics"]["raw"]
        self.assertEqual(raw["details"]["authorization"], "[redacted]")
        self.assertEqual(raw["details"]["prompt"], "[redacted]")
        self.assertEqual(raw["details"]["safe"], "ok")

    def test_summarize_counts_failure_categories(self):
        service = FailureTaxonomyService()
        rows = [
            {"status": "error", "error_category": "rate_limit"},
            {"status": "error", "error": "budget blocked"},
            {"status": "error", "http_status": 429},
        ]

        summary = service.summarize(rows)

        self.assertEqual(summary[0]["category"], "rate_limit")
        self.assertEqual(summary[0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
