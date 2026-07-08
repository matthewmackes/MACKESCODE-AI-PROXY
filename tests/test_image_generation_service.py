import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services.image_generation import ImageGenerationService


class FixedUuid:
    hex = "imageid123"


class ImageGenerationServiceTests(unittest.TestCase):
    def service(self, request_json=None, models=None):
        saved_items = []
        history = []
        proxy_started = []

        def save_image_item(item, image_id):
            saved_items.append((item, image_id))
            return Path(tempfile.gettempdir()) / ("%s.png" % image_id)

        service = ImageGenerationService(
            styles={"none": "", "technical": "precise technical visualization"},
            sizes=["512x512", "1024x1024"],
            image_models=lambda: models or ["image-a"],
            image_cost_usd=lambda: {"image-a": 0.08},
            default_image_model=lambda: "image-a",
            start_proxy_if_needed=lambda: proxy_started.append(True),
            request_json=request_json or (lambda url, payload: (200, {"data": [{"b64_json": "abc"}]})),
            proxy_url=lambda path: "http://proxy.local" + path,
            save_image_item=save_image_item,
            append_history=history.append,
            clock=lambda: 1000,
            uuid_factory=lambda: FixedUuid(),
        )
        return service, saved_items, history, proxy_started

    def test_build_prompt_combines_builder_style_negative_and_iteration(self):
        service, _, _, _ = self.service()
        prompt = service.build_prompt({
            "prompt": "A server",
            "builder": {"environment": "rack room", "lighting": "blue light"},
            "style": "technical",
            "negative_prompt": "clutter",
        })
        revision = service.build_prompt({"source_prompt": "Original", "iteration": "make it smaller"})

        self.assertEqual(prompt, "A server, rack room, blue light, precise technical visualization. Avoid: clutter")
        self.assertEqual(revision, "Original. Revise with: make it smaller")

    def test_generate_rejects_unknown_model_and_empty_prompt(self):
        service, _, _, started = self.service(models=["image-a"])
        unknown_status, unknown_payload = service.generate({"model": "missing", "prompt": "hi"})
        empty_status, empty_payload = service.generate({"model": "image-a", "prompt": ""})

        self.assertEqual(unknown_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(unknown_payload["error"], "unknown image model")
        self.assertEqual(empty_status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(empty_payload["error"], "prompt is required")
        self.assertEqual(started, [True, True])

    def test_generate_clamps_count_defaults_size_records_history(self):
        requests = []

        def request_json(url, payload):
            requests.append((url, payload))
            return 200, {"data": [{"b64_json": "abc"}, {"b64_json": "def"}]}

        service, saved_items, history, started = self.service(request_json=request_json)
        status, payload = service.generate({
            "prompt": "diagram",
            "count": "9",
            "size": "bad-size",
            "seed": "42",
            "style": "technical",
            "negative_prompt": "noise",
        })

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(requests[0][0], "http://proxy.local/v1/images/generations")
        self.assertEqual(requests[0][1]["n"], 4)
        self.assertEqual(requests[0][1]["size"], "1024x1024")
        self.assertEqual(requests[0][1]["seed"], "42")
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(saved_items[0][1], "imageid123")
        self.assertEqual(history[0]["cost_usd"], 0.08)
        self.assertEqual(history[0]["created_at"], 1000)
        self.assertEqual(started, [True])

    def test_generate_returns_upstream_error_without_history(self):
        service, saved_items, history, _ = self.service(request_json=lambda url, payload: (502, {"error": "bad upstream"}))
        status, payload = service.generate({"prompt": "diagram"})

        self.assertEqual(status, 502)
        self.assertEqual(payload, {"error": "bad upstream"})
        self.assertEqual(saved_items, [])
        self.assertEqual(history, [])


if __name__ == "__main__":
    unittest.main()
