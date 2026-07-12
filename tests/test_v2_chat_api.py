import json
import os
import unittest
from contextlib import contextmanager

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app
from backend.v2.api import chat as chat_api


@contextmanager
def console_auth_env():
    keys = ("MATTS_CONSOLE_AUTH_ENABLED", "MATTS_CONSOLE_AUTH_TOKEN", "MATTS_CONSOLE_ROLE_TOKENS")
    old_env = {key: os.environ.get(key) for key in keys}
    os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "1"
    os.environ["MATTS_CONSOLE_AUTH_TOKEN"] = "owner-token-secret"
    os.environ["MATTS_CONSOLE_ROLE_TOKENS"] = json.dumps({
        "viewer-token": {"id": "viewer-user", "roles": ["viewer"]},
        "operator-token": {"id": "operator-user", "roles": ["operator"]},
    })
    try:
        yield
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2ChatApiTests(unittest.TestCase):
    def test_chat_payload_exposes_voice_profile(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        old_speech_engine = os.environ.get("MATTS_SPEECH_ENGINE")
        os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
        os.environ["MATTS_SPEECH_ENGINE"] = "browser"
        try:
            client = TestClient(create_app())
            response = client.get("/v2/chat")
        finally:
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth
            if old_speech_engine is None:
                os.environ.pop("MATTS_SPEECH_ENGINE", None)
            else:
                os.environ["MATTS_SPEECH_ENGINE"] = old_speech_engine

        self.assertEqual(response.status_code, 200)
        voice = response.json()["voice"]
        self.assertEqual(voice["mode"], "browser_speech_synthesis")
        self.assertEqual(voice["fallback_mode"], "browser_speech_synthesis")
        self.assertEqual(voice["style"], "calm mission-computer")
        self.assertEqual(voice["server_engine"]["engine"], "browser_speech_synthesis")
        self.assertEqual(voice["input_mode"], "browser_speech_recognition")
        self.assertTrue(voice["enabled_by_default"])
        self.assertGreaterEqual(voice["max_chars"], 1000)
        self.assertIn("language", voice)
        self.assertIn("instruct", voice)
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

    def test_viewer_can_load_chat_payload_but_cannot_spend_model_use(self):
        old_adapter = chat_api.legacy_adapter

        class FailingAdapter:
            def chat_completion(self, payload):  # pragma: no cover - must not be called
                raise AssertionError("viewer POST should fail before adapter dispatch")

        chat_api.legacy_adapter = FailingAdapter()
        try:
            with console_auth_env():
                client = TestClient(create_app())
                headers = {"x-matts-console-token": "viewer-token"}
                payload_response = client.get("/v2/chat", headers=headers)
                post_response = client.post("/v2/chat", json={"model": "model-a", "messages": []}, headers=headers)
        finally:
            chat_api.legacy_adapter = old_adapter

        self.assertEqual(payload_response.status_code, 200)
        self.assertIn("models", payload_response.json())
        self.assertEqual(post_response.status_code, 403)
        self.assertEqual(post_response.json()["detail"]["required_permission"], "model_use")

    def test_operator_can_complete_chat_with_model_use(self):
        old_adapter = chat_api.legacy_adapter

        class FakeAdapter:
            def chat_completion(self, payload):
                return 200, {"text": "operator ok"}

        chat_api.legacy_adapter = FakeAdapter()
        try:
            with console_auth_env():
                client = TestClient(create_app())
                response = client.post(
                    "/v2/chat",
                    json={"model": "model-a", "messages": [{"role": "user", "content": "hello"}]},
                    headers={"x-matts-console-token": "operator-token"},
                )
        finally:
            chat_api.legacy_adapter = old_adapter

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["response"]["text"], "operator ok")

    def test_chat_response_normalizes_xml_leak_diagnostics(self):
        old_auth = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
        old_adapter = chat_api.legacy_adapter

        class FakeAdapter:
            def chat_completion(self, payload):
                return 200, {
                    "text": "You are a function calling AI model. <tools></tools>",
                    "raw": {"stop_reason": "end_turn", "trace_id": "upstream-trace"},
                }

        os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = "0"
        chat_api.legacy_adapter = FakeAdapter()
        try:
            client = TestClient(create_app())
            response = client.post("/v2/chat", json={
                "model": "model-a",
                "client_selected_model_id": "model-a",
                "messages": [{"role": "user", "content": "hello"}],
            })
        finally:
            chat_api.legacy_adapter = old_adapter
            if old_auth is None:
                os.environ.pop("MATTS_CONSOLE_AUTH_ENABLED", None)
            else:
                os.environ["MATTS_CONSOLE_AUTH_ENABLED"] = old_auth

        self.assertEqual(response.status_code, 200)
        body = response.json()["response"]
        self.assertEqual(body["diagnostics"]["output_format_issue"], "tool_prompt_leak")
        self.assertEqual(body["routing"]["client_selected"], "model-a")
        self.assertEqual(body["trace"]["upstream_trace_id"], "upstream-trace")


if __name__ == "__main__":
    unittest.main()
