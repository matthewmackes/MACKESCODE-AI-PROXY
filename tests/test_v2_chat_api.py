import os
import unittest

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app
from backend.v2.api import chat as chat_api


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2ChatApiTests(unittest.TestCase):
    def test_chat_payload_exposes_voice_profile(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
        try:
            client = TestClient(create_app())
            response = client.get("/v2/chat")
        finally:
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth

        self.assertEqual(response.status_code, 200)
        voice = response.json()["voice"]
        self.assertEqual(voice["mode"], "browser_speech_synthesis")
        self.assertEqual(voice["style"], "calm mission-computer")
        self.assertTrue(voice["enabled_by_default"])
        self.assertGreaterEqual(voice["max_chars"], 1000)
        self.assertIn("voice online", voice["preview"])

    def test_public_chat_route_strips_internal_trace_hints(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        old_adapter = chat_api.legacy_adapter
        captured = {}

        class FakeAdapter:
            def chat_completion(self, payload):
                captured.update(payload)
                return 200, {"text": "ok"}

        os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
        chat_api.legacy_adapter = FakeAdapter()
        try:
            client = TestClient(create_app())
            response = client.post("/v2/chat", json={
                "model": "model-a",
                "messages": [{"role": "user", "content": "hello"}],
                "trace_status_on_error": "fallback",
                "trace_origin": "research_llm",
            })
        finally:
            chat_api.legacy_adapter = old_adapter
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("trace_status_on_error", captured)
        self.assertNotIn("trace_origin", captured)
        self.assertEqual(captured["messages"][0]["content"], "hello")


if __name__ == "__main__":
    unittest.main()
