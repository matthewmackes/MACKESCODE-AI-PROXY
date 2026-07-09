import json
import tempfile
import unittest
from pathlib import Path

from src.console.services.model_hero import ModelHeroService


class ModelHeroServiceTests(unittest.TestCase):
    def service(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "families.json").write_text(json.dumps({
            "families": {
                "qwen": {
                    "summary": "Qwen is good for coding and multilingual reasoning.",
                    "best_for": ["coding"],
                    "strengths": ["Strong code profile"],
                    "weaknesses": ["Watch dedicated cost"],
                    "alternatives": ["DeepSeek"]
                },
                "deepseek": {
                    "summary": "DeepSeek is a practical coding model.",
                    "best_for": ["reasoning"],
                    "strengths": ["Good value"],
                    "weaknesses": ["Validate claims"],
                    "alternatives": ["Qwen"]
                },
                "general": {
                    "summary": "General fallback.",
                    "best_for": ["experiments"],
                    "strengths": ["Available"],
                    "weaknesses": ["Validate"],
                    "alternatives": []
                }
            }
        }), encoding="utf-8")
        return ModelHeroService(root)

    def test_hero_cards_include_registry_facts_and_curated_sections(self):
        cards = self.service().hero_cards([
            {
                "id": "qwen3-coder-flash",
                "display_name": "Qwen3 Coder Flash",
                "type": "text",
                "brand": "Alibaba Qwen",
                "family": "Qwen",
                "origin": "China",
                "cost_label": "$0.05 input / 1M tokens",
                "status": "Available",
                "use_case": "Fast coding work.",
                "pricing": {"input": 0.05},
                "style": {"accent": "#123456"},
            },
            {
                "id": "deepseek-r1",
                "display_name": "DeepSeek R1",
                "type": "text",
                "brand": "DeepSeek",
                "family": "DeepSeek",
                "origin": "China",
                "cost_label": "$0.1 input / 1M tokens",
                "status": "Available",
            },
        ])

        card = cards["model_info"]["qwen3-coder-flash"]
        self.assertEqual(card["origin"], "China")
        self.assertEqual(card["cost_label"], "$0.05 input / 1M tokens")
        self.assertIn("Strong code profile", card["strengths"])
        self.assertIn("Watch dedicated cost", card["weaknesses"])
        self.assertEqual(card["alternatives"][0]["id"], "deepseek-r1")
        self.assertIn("families.json:qwen", card["description_source"])

    def test_unknown_family_uses_general_profile(self):
        card = self.service().hero_card({"id": "mystery", "display_name": "Mystery", "family": "Other"})

        self.assertEqual(card["family"], "Other")
        self.assertIn("General fallback", card["summary"])
        self.assertEqual(card["best_for"], ["experiments"])


if __name__ == "__main__":
    unittest.main()
