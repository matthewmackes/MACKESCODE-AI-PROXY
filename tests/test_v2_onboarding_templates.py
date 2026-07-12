import json
import tempfile
import unittest
from pathlib import Path

from backend.v2.services.model_showcase import ModelShowcaseService
from backend.v2.services.onboarding_templates import OnboardingTemplateService
from backend.v2.services.run_store import RunStore


class V2OnboardingTemplateServiceTests(unittest.TestCase):
    def service(self, root: Path) -> OnboardingTemplateService:
        model_config = root / "models.json"
        access_state = root / "access.json"
        model_config.write_text(json.dumps({
            "schema_version": 1,
            "models": [
                {
                    "id": "alibaba-qwen3-32b",
                    "display_name": "Alibaba Qwen3 32b",
                    "type": "text",
                    "provider": "DigitalOcean",
                    "enabled": True,
                    "serverless": True,
                    "pricing": {"input": 0.1, "output": 0.2},
                },
                {
                    "id": "stable-diffusion-xl",
                    "display_name": "Stable Diffusion XL",
                    "type": "image",
                    "provider": "DigitalOcean",
                    "enabled": True,
                    "serverless": True,
                    "pricing": {"image": 0.01},
                },
            ],
        }), encoding="utf-8")
        access_state.write_text(json.dumps({"schema_version": 1, "models": {
            "alibaba-qwen3-32b": {"access_status": "ok"},
            "stable-diffusion-xl": {"access_status": "ok"},
        }}), encoding="utf-8")
        return OnboardingTemplateService(
            run_store=RunStore(root / "run.sqlite3", clock=lambda: 1000.0),
            showcase_service=ModelShowcaseService(model_config=model_config, model_access_state=access_state, clock=lambda: 1000.0),
        )

    def test_seed_missing_templates_is_idempotent_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp))

            first = service.seed_missing()
            second = service.seed_missing()

            self.assertEqual(first["summary"]["target"], 2)
            self.assertEqual(first["summary"]["seeded"], 2)
            self.assertEqual(second["summary"]["seeded"], 0)
            self.assertEqual(second["summary"]["existing"], 2)
            templates = service.run_store.list_prompt_templates()
            self.assertEqual(len(templates), 2)
            self.assertTrue(all(template["version"] == 1 for template in templates))
            text_template = [template for template in templates if "qwen3" in template["id"]][0]
            self.assertIn("Do not emit XML", text_template["body"])
            self.assertIn("output_format", text_template["variables"])

    def test_payload_reports_missing_without_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(Path(tmp))

            payload = service.payload()

            self.assertEqual(payload["summary"]["target"], 2)
            self.assertEqual(payload["summary"]["missing"], 2)
            self.assertEqual(service.run_store.list_prompt_templates(), [])


if __name__ == "__main__":
    unittest.main()
