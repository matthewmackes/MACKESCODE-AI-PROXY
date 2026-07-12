import base64
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):  # pragma: no cover
    TestClient = None

from backend.v2.app import create_app
from backend.v2.api import speech as speech_api
from backend.v2.services import speech as speech_service_module
from backend.v2.services.speech import SpeechAudio


@contextmanager
def env_values(values):
    old_env = {key: os.environ.get(key) for key in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def console_auth_env():
    with env_values({
        "MATTS_CONSOLE_AUTH_ENABLED": "1",
        "MATTS_CONSOLE_AUTH_TOKEN": "owner-token-secret",
        "MATTS_CONSOLE_ROLE_TOKENS": json.dumps({
            "viewer-token": {"id": "viewer-user", "roles": ["viewer"]},
            "operator-token": {"id": "operator-user", "roles": ["operator"]},
        }),
    }):
        yield


def fake_status(max_chars=1200):
    return {
        "enabled": True,
        "configured": True,
        "available": True,
        "mode": "server_qwen3_tts",
        "engine": "qwen3_voice_design",
        "fallback_mode": "browser_speech_synthesis",
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "language": "Auto",
        "languages": ["Auto", "English"],
        "instruct": "calm test voice",
        "max_chars": max_chars,
        "mime_type": "audio/wav",
        "sample_rate": 0,
        "reason": "",
        "input": {"browser_speech_recognition": True},
    }


@unittest.skipIf(TestClient is None, "fastapi test client is not installed")
class V2SpeechApiTests(unittest.TestCase):
    def test_status_reports_browser_fallback_when_qwen_is_not_enabled(self):
        with env_values({
            "MATTS_CONSOLE_AUTH_ENABLED": "0",
            "MATTS_SPEECH_ENGINE": "browser",
            "MATTS_QWEN_TTS_PYTHON": None,
        }):
            client = TestClient(create_app())
            response = client.get("/v2/speech")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["mode"], "browser_speech_synthesis")
        self.assertEqual(payload["fallback_mode"], "browser_speech_synthesis")
        self.assertIn("MATTS_SPEECH_ENGINE", payload["reason"])

    def test_viewer_can_read_status_but_cannot_synthesize(self):
        class FakeSpeechService:
            def status(self):
                return fake_status()

            def synthesize(self, text, language=None, instruct=None):  # pragma: no cover - must not be called
                raise AssertionError("viewer should fail before synthesis")

        old_service = speech_api.speech_service
        speech_api.speech_service = FakeSpeechService()
        try:
            with console_auth_env():
                client = TestClient(create_app())
                headers = {"x-matts-console-token": "viewer-token"}
                status_response = client.get("/v2/speech", headers=headers)
                synth_response = client.post("/v2/speech/synthesize", json={"text": "hello"}, headers=headers)
        finally:
            speech_api.speech_service = old_service

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(synth_response.status_code, 403)
        self.assertEqual(synth_response.json()["detail"]["required_permission"], "model_use")

    def test_operator_can_synthesize_fake_wav(self):
        class FakeSpeechService:
            def status(self):
                return fake_status()

            def synthesize(self, text, language=None, instruct=None):
                self.last = {"text": text, "language": language, "instruct": instruct}
                return SpeechAudio(b"RIFF$\x00\x00\x00WAVEfmt ", sample_rate=24000)

        fake = FakeSpeechService()
        old_service = speech_api.speech_service
        speech_api.speech_service = fake
        try:
            with console_auth_env():
                client = TestClient(create_app())
                response = client.post(
                    "/v2/speech/synthesize",
                    json={"text": "hello speech", "language": "English", "instruct": "steady voice"},
                    headers={"x-matts-console-token": "operator-token"},
                )
        finally:
            speech_api.speech_service = old_service

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        self.assertTrue(response.content.startswith(b"RIFF"))
        self.assertEqual(fake.last["language"], "English")
        self.assertEqual(fake.last["instruct"], "steady voice")

    def test_synthesize_rejects_text_over_status_max_chars(self):
        class FakeSpeechService:
            def status(self):
                return fake_status(max_chars=5)

            def synthesize(self, text, language=None, instruct=None):  # pragma: no cover - must not be called
                raise AssertionError("oversized speech text should fail before synthesis")

        old_service = speech_api.speech_service
        speech_api.speech_service = FakeSpeechService()
        try:
            with console_auth_env():
                client = TestClient(create_app())
                response = client.post(
                    "/v2/speech/synthesize",
                    json={"text": "too long"},
                    headers={"x-matts-console-token": "operator-token"},
                )
        finally:
            speech_api.speech_service = old_service

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"]["code"], "speech_text_too_long")

    def test_status_reports_do_tts_missing_key(self):
        with env_values({
            "MATTS_CONSOLE_AUTH_ENABLED": "0",
            "MATTS_SPEECH_ENGINE": "do_qwen3_tts",
            "MODEL_ACCESS_KEY": None,
            "DIGITALOCEAN_MODEL_ACCESS_KEY": None,
            "MATTS_VALUE_SET_ACCESS_TOKEN": None,
        }), patch.object(speech_service_module, "_model_access_key_candidates", return_value=[]):
            payload = speech_service_module.speech_status_payload(speech_service_module.speech_settings())

        self.assertTrue(payload["enabled"])
        self.assertFalse(payload["configured"])
        self.assertFalse(payload["available"])
        self.assertEqual(payload["mode"], "browser_speech_synthesis")
        self.assertEqual(payload["engine"], "digitalocean_qwen3_tts")
        self.assertEqual(payload["model"], "qwen3-tts-voicedesign")
        self.assertIn("DigitalOcean model access key", payload["reason"])
        self.assertFalse(payload["input"]["digitalocean_speech_to_text"])

    def test_status_reports_do_tts_available_with_env_key(self):
        with env_values({
            "MATTS_CONSOLE_AUTH_ENABLED": "0",
            "MATTS_SPEECH_ENGINE": "do_qwen3_tts",
            "MODEL_ACCESS_KEY": "test-model-access-key",
            "DIGITALOCEAN_MODEL_ACCESS_KEY": None,
            "MATTS_VALUE_SET_ACCESS_TOKEN": None,
        }):
            payload = speech_service_module.speech_status_payload(speech_service_module.speech_settings())

        self.assertTrue(payload["configured"])
        self.assertTrue(payload["available"])
        self.assertEqual(payload["mode"], "server_do_qwen3_tts")
        self.assertEqual(payload["engine"], "digitalocean_qwen3_tts")
        self.assertEqual(payload["mime_type"], "audio/wav")

    def test_do_tts_synthesizes_mock_json_audio(self):
        captured = {}
        wav = b"RIFF$\x00\x00\x00WAVEfmt "

        class FakeResponse:
            headers = {"content-type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return json.dumps({"data": [{"b64_json": base64.b64encode(wav).decode("ascii")}]}).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["headers"] = {str(key).lower(): value for key, value in request.headers.items()}
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        service = speech_service_module.QwenSpeechService(urlopen_func=fake_urlopen)
        with env_values({
            "MATTS_SPEECH_ENGINE": "do_qwen3_tts",
            "MODEL_ACCESS_KEY": "test-model-access-key",
            "DIGITALOCEAN_MODEL_ACCESS_KEY": None,
            "MATTS_VALUE_SET_ACCESS_TOKEN": None,
            "MATTS_DO_TTS_TIMEOUT": "7",
            "MATTS_DO_TTS_FORMAT": "wav",
        }):
            audio = service.synthesize("hello speech", language="Chinese", instruct="Warm female voice.")

        self.assertEqual(captured["url"], "https://inference.do-ai.run/v1/audio/speech")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["headers"]["authorization"], "Bearer test-model-access-key")
        self.assertEqual(captured["payload"]["model"], "qwen3-tts-voicedesign")
        self.assertEqual(captured["payload"]["input"], "hello speech")
        self.assertEqual(captured["payload"]["voice"], "alloy")
        self.assertEqual(captured["payload"]["response_format"], "wav")
        self.assertIn("Chinese", captured["payload"]["instructions"])
        self.assertEqual(audio.data, wav)
        self.assertEqual(audio.mime_type, "audio/wav")
        self.assertEqual(audio.engine, "digitalocean_qwen3_tts")


if __name__ == "__main__":
    unittest.main()
