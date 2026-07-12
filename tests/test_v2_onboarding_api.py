import os
import unittest

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app
from backend.v2.api import onboarding as onboarding_api


class FakeLegacy:
    def __init__(self):
        self.completed = []

    def onboarding_payload(self):
        return {"checks": [{"id": "model_access_token", "status": "passed"}], "summary": {"checks": 1}}

    def complete_onboarding_item(self, payload):
        self.completed.append(payload)
        return {"checks": [], "summary": {"checks": 0}, "completed": payload.get("id")}


class FakeTemplates:
    def __init__(self):
        self.seed_count = 0

    def payload(self):
        return {"generator": "fake", "summary": {"target": 1, "existing": 0, "missing": 1, "seeded": 0}, "items": []}

    def seed_missing(self):
        self.seed_count += 1
        return {"generator": "fake", "summary": {"target": 1, "existing": 1, "missing": 0, "seeded": 1}, "items": []}


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2OnboardingApiTests(unittest.TestCase):
    def test_get_onboarding_is_read_only_and_seed_post_seeds(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        old_legacy = onboarding_api.legacy_adapter
        old_templates = onboarding_api.template_service
        fake_templates = FakeTemplates()
        os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
        onboarding_api.legacy_adapter = FakeLegacy()
        onboarding_api.template_service = fake_templates
        try:
            client = TestClient(create_app())
            get_response = client.get("/v2/onboarding")
            seed_response = client.post("/v2/onboarding/model-templates/seed")
        finally:
            onboarding_api.legacy_adapter = old_legacy
            onboarding_api.template_service = old_templates
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["model_templates"]["summary"]["missing"], 1)
        self.assertEqual(fake_templates.seed_count, 1)
        self.assertEqual(seed_response.status_code, 200)
        self.assertEqual(seed_response.json()["model_templates"]["summary"]["seeded"], 1)


if __name__ == "__main__":
    unittest.main()
