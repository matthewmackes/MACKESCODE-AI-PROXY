"""Optional server-side speech synthesis for v2 Chat."""
from __future__ import annotations

import base64
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_QWEN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
DEFAULT_DO_TTS_MODEL = "qwen3-tts-voicedesign"
DEFAULT_DO_TTS_BASE_URL = "https://inference.do-ai.run"
DEFAULT_DO_TTS_FORMAT = "wav"
DEFAULT_DO_TTS_VOICE = "alloy"
DEFAULT_LANGUAGE = "Auto"
DEFAULT_INSTRUCT = "calm, clear mission-control voice with concise pacing"
DEFAULT_MAX_CHARS = 1200
DEFAULT_TIMEOUT_SECONDS = 600
DEFAULT_DO_TIMEOUT_SECONDS = 120
DO_TTS_ENGINES = {"do_qwen3_tts", "digitalocean_qwen3_tts"}
SUPPORTED_LANGUAGES = [
    "Auto",
    "English",
    "Chinese",
    "French",
    "German",
    "Italian",
    "Japanese",
    "Korean",
    "Portuguese",
    "Russian",
    "Spanish",
]


class SpeechBusyError(Exception):
    """Raised when the single speech worker is already handling a request."""


class SpeechConfigError(Exception):
    """Raised when server-side speech is not enabled or configured."""


class SpeechSynthesisError(Exception):
    """Raised when the worker cannot synthesize audio."""


@dataclass(frozen=True)
class SpeechAudio:
    data: bytes
    mime_type: str = "audio/wav"
    sample_rate: int = 0
    engine: str = "qwen3_voice_design"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_value(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def _home_dir() -> Path:
    return Path(os.environ.get("HOME") or "/root")


def _token_file() -> Path:
    return Path(os.environ.get("MATTS_VALUE_SET_TOKEN_FILE", _home_dir() / ".mcnf-do-model-access-token"))


def _model_access_key_candidates() -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for name in ("MODEL_ACCESS_KEY", "DIGITALOCEAN_MODEL_ACCESS_KEY", "MATTS_VALUE_SET_ACCESS_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            candidates.append({"source": "env:%s" % name, "token": value, "path": ""})
    for path in (
        _token_file(),
        _home_dir() / ".mcnf-do-model-access-token",
        PROJECT_DIR / ".mcnf-do-model-access-token",
        Path("/root/.mcnf-do-model-access-token"),
    ):
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if token:
            candidates.append({"source": "file:%s" % path, "token": token, "path": str(path)})
    return candidates


def _model_access_key() -> tuple[str, str]:
    candidates = _model_access_key_candidates()
    if not candidates:
        return "", ""
    item = candidates[0]
    return item["token"], item["source"]


def _python_command(raw: str) -> str:
    path = Path(raw).expanduser()
    if path.exists():
        return str(path)
    return raw


def _python_available(raw: str) -> bool:
    if not raw:
        return False
    path = Path(raw).expanduser()
    return path.exists() or shutil.which(raw) is not None


def speech_settings() -> dict[str, Any]:
    common_max_chars = _env_int("MATTS_QWEN_TTS_MAX_CHARS", DEFAULT_MAX_CHARS, minimum=200)
    token, token_source = _model_access_key()
    return {
        "engine": _env_value("MATTS_SPEECH_ENGINE", "browser").lower(),
        "python": _env_value("MATTS_QWEN_TTS_PYTHON", sys.executable),
        "model": _env_value("MATTS_QWEN_TTS_MODEL", DEFAULT_QWEN_MODEL),
        "device": _env_value("MATTS_QWEN_TTS_DEVICE", "auto"),
        "dtype": _env_value("MATTS_QWEN_TTS_DTYPE", "bfloat16"),
        "attn": _env_value("MATTS_QWEN_TTS_ATTN", ""),
        "language": _env_value("MATTS_SPEECH_LANGUAGE", _env_value("MATTS_QWEN_TTS_LANGUAGE", DEFAULT_LANGUAGE)),
        "instruct": _env_value("MATTS_SPEECH_INSTRUCT", _env_value("MATTS_QWEN_TTS_INSTRUCT", DEFAULT_INSTRUCT)),
        "max_chars": _env_int("MATTS_SPEECH_MAX_CHARS", common_max_chars, minimum=200),
        "timeout_seconds": _env_int("MATTS_QWEN_TTS_TIMEOUT", DEFAULT_TIMEOUT_SECONDS, minimum=30),
        "do_base_url": _env_value("MATTS_DO_TTS_BASE_URL", DEFAULT_DO_TTS_BASE_URL).rstrip("/"),
        "do_model": _env_value("MATTS_DO_TTS_MODEL", DEFAULT_DO_TTS_MODEL),
        "do_voice": _env_value("MATTS_DO_TTS_VOICE", DEFAULT_DO_TTS_VOICE),
        "do_response_format": _env_value("MATTS_DO_TTS_FORMAT", DEFAULT_DO_TTS_FORMAT).lower(),
        "do_timeout_seconds": _env_int("MATTS_DO_TTS_TIMEOUT", DEFAULT_DO_TIMEOUT_SECONDS, minimum=5),
        "do_token": token,
        "do_token_source": token_source,
    }


def _mime_for_format(response_format: str) -> str:
    return {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "mpeg": "audio/mpeg",
        "opus": "audio/opus",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "aac": "audio/aac",
    }.get(response_format.lower(), "application/octet-stream")


def _speech_input_status() -> dict[str, Any]:
    return {
        "browser_speech_recognition": True,
        "browser_speech_synthesis": True,
        "digitalocean_speech_to_text": False,
        "server_speech_to_text": False,
        "note": "Speech input is browser-native best effort; no DigitalOcean speech-to-text model is configured.",
    }


def speech_status_payload(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or speech_settings()
    engine = str(settings["engine"])
    if engine in DO_TTS_ENGINES:
        configured = bool(settings["do_token"])
        available = configured
        reason = "" if configured else "DigitalOcean model access key is not configured"
        return {
            "enabled": True,
            "configured": configured,
            "available": available,
            "mode": "server_do_qwen3_tts" if available else "browser_speech_synthesis",
            "engine": "digitalocean_qwen3_tts",
            "fallback_mode": "browser_speech_synthesis",
            "model": settings["do_model"],
            "language": settings["language"],
            "languages": SUPPORTED_LANGUAGES,
            "instruct": settings["instruct"],
            "max_chars": settings["max_chars"],
            "mime_type": _mime_for_format(str(settings["do_response_format"])),
            "sample_rate": 0,
            "reason": reason,
            "input": _speech_input_status(),
        }

    enabled = engine == "qwen3"
    configured = bool(settings["python"])
    python_available = _python_available(str(settings["python"]))
    available = enabled and configured and python_available
    if not enabled:
        reason = "MATTS_SPEECH_ENGINE is not qwen3 or do_qwen3_tts"
    elif not configured:
        reason = "MATTS_QWEN_TTS_PYTHON is not configured"
    elif not python_available:
        reason = "MATTS_QWEN_TTS_PYTHON does not resolve to an executable"
    else:
        reason = ""
    return {
        "enabled": enabled,
        "configured": configured,
        "available": available,
        "mode": "server_qwen3_tts" if available else "browser_speech_synthesis",
        "engine": "qwen3_voice_design" if enabled else "browser_speech_synthesis",
        "fallback_mode": "browser_speech_synthesis",
        "model": settings["model"],
        "language": settings["language"],
        "languages": SUPPORTED_LANGUAGES,
        "instruct": settings["instruct"],
        "max_chars": settings["max_chars"],
        "mime_type": "audio/wav",
        "sample_rate": 0,
        "reason": reason,
        "input": _speech_input_status(),
    }


class QwenSpeechService:
    """Manages one optional Qwen3-TTS worker process."""

    def __init__(self, worker_script: Path | None = None, urlopen_func: Callable[..., Any] | None = None) -> None:
        self.worker_script = worker_script or PROJECT_DIR / "scripts" / "qwen_tts_worker.py"
        self.urlopen = urlopen_func or urlopen
        self._request_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._settings_key: tuple[str, ...] | None = None

    def status(self) -> dict[str, Any]:
        return speech_status_payload()

    def synthesize(self, text: str, language: str | None = None, instruct: str | None = None) -> SpeechAudio:
        settings = speech_settings()
        status = speech_status_payload(settings)
        if not status["available"]:
            raise SpeechConfigError(status["reason"] or "server speech is unavailable")
        if not text.strip():
            raise SpeechSynthesisError("speech text is empty")
        if len(text) > int(status["max_chars"]):
            raise SpeechSynthesisError("speech text exceeds configured maximum")
        if not self._request_lock.acquire(blocking=False):
            raise SpeechBusyError("speech engine is already synthesizing")
        try:
            if str(settings["engine"]) in DO_TTS_ENGINES:
                return self._synthesize_do(settings, text, language, instruct)
            return self._synthesize_locked(settings, text, language, instruct)
        finally:
            self._request_lock.release()

    def _audio_from_json(self, payload: Any, fallback_mime: str) -> SpeechAudio:
        def decode_candidate(value: Any) -> SpeechAudio | None:
            if not isinstance(value, str) or not value.strip():
                return None
            raw = value.strip()
            mime_type = fallback_mime
            if raw.startswith("data:") and ";base64," in raw:
                header, raw = raw.split(",", 1)
                mime_type = header[5:].split(";", 1)[0] or fallback_mime
            try:
                return SpeechAudio(
                    data=base64.b64decode(raw),
                    mime_type=mime_type,
                    engine="digitalocean_qwen3_tts",
                )
            except (ValueError, TypeError):
                return None

        def walk(value: Any) -> SpeechAudio | None:
            if isinstance(value, dict):
                for key in ("b64_json", "audio", "audio_base64"):
                    audio = decode_candidate(value.get(key))
                    if audio is not None:
                        return audio
                for key in ("data", "content", "output"):
                    audio = walk(value.get(key))
                    if audio is not None:
                        return audio
            elif isinstance(value, list):
                for item in value:
                    audio = walk(item)
                    if audio is not None:
                        return audio
            elif isinstance(value, str):
                return decode_candidate(value)
            return None

        audio = walk(payload)
        if audio is None:
            raise SpeechSynthesisError("DigitalOcean speech response did not include audio data")
        return audio

    def _response_content_type(self, response: Any, fallback: str) -> str:
        headers = getattr(response, "headers", {}) or {}
        if hasattr(headers, "get"):
            return str(headers.get("content-type") or headers.get("Content-Type") or fallback).split(";", 1)[0]
        return fallback

    def _error_message(self, data: bytes, fallback: str) -> str:
        if not data:
            return fallback
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return data[:500].decode("utf-8", "replace") or fallback
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if payload.get("message"):
                return str(payload["message"])
            if payload.get("detail"):
                return str(payload["detail"])
        return fallback

    def _synthesize_do(self, settings: dict[str, Any], text: str, language: str | None, instruct: str | None) -> SpeechAudio:
        response_format = str(settings["do_response_format"] or DEFAULT_DO_TTS_FORMAT).lower()
        fallback_mime = _mime_for_format(response_format)
        instructions = instruct or settings["instruct"]
        requested_language = language or settings["language"]
        if requested_language and str(requested_language).lower() != "auto":
            instructions = "%s Speak in %s." % (instructions, requested_language)
        payload = {
            "model": str(settings["do_model"]),
            "input": text,
            "voice": str(settings["do_voice"] or DEFAULT_DO_TTS_VOICE),
            "response_format": response_format,
            "instructions": instructions,
        }
        request = Request(
            str(settings["do_base_url"]) + "/v1/audio/speech",
            data=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            headers={
                "authorization": "Bearer " + str(settings["do_token"]),
                "content-type": "application/json",
                "accept": "audio/*, application/json",
                "user-agent": "mde-llm-proxy/1.0",
            },
            method="POST",
        )
        try:
            with self.urlopen(request, timeout=int(settings["do_timeout_seconds"])) as response:
                data = response.read()
                content_type = self._response_content_type(response, fallback_mime)
        except HTTPError as exc:
            error_data = exc.read()
            message = self._error_message(error_data, "DigitalOcean speech request failed")
            if exc.code in (401, 403):
                raise SpeechConfigError("DigitalOcean speech access was denied: %s" % message)
            if exc.code in (400, 404, 422):
                raise SpeechConfigError("DigitalOcean speech request was rejected: %s" % message)
            if exc.code == 429:
                raise SpeechBusyError("DigitalOcean speech engine is rate limited: %s" % message)
            raise SpeechSynthesisError("DigitalOcean speech request failed with HTTP %d: %s" % (exc.code, message))
        except (TimeoutError, URLError, OSError) as exc:
            raise SpeechSynthesisError("DigitalOcean speech request failed: %s" % exc)

        if not data:
            raise SpeechSynthesisError("DigitalOcean speech response was empty")
        if content_type == "application/json":
            try:
                return self._audio_from_json(json.loads(data.decode("utf-8")), fallback_mime)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SpeechSynthesisError("DigitalOcean speech response JSON could not be decoded: %s" % exc)
        return SpeechAudio(
            data=data,
            mime_type=content_type or fallback_mime,
            engine="digitalocean_qwen3_tts",
        )

    def _settings_tuple(self, settings: dict[str, Any]) -> tuple[str, ...]:
        return (
            str(settings["python"]),
            str(settings["model"]),
            str(settings["device"]),
            str(settings["dtype"]),
            str(settings["attn"]),
        )

    def _stop_worker_locked(self) -> None:
        process = self._process
        self._process = None
        self._settings_key = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _ensure_worker(self, settings: dict[str, Any]) -> subprocess.Popen[str]:
        settings_key = self._settings_tuple(settings)
        with self._process_lock:
            if self._process is not None and self._process.poll() is None and self._settings_key == settings_key:
                return self._process
            self._stop_worker_locked()
            env = os.environ.copy()
            env.update({
                "MATTS_QWEN_TTS_MODEL": str(settings["model"]),
                "MATTS_QWEN_TTS_DEVICE": str(settings["device"]),
                "MATTS_QWEN_TTS_DTYPE": str(settings["dtype"]),
                "MATTS_QWEN_TTS_ATTN": str(settings["attn"]),
            })
            command = [_python_command(str(settings["python"])), str(self.worker_script)]
            self._process = subprocess.Popen(
                command,
                cwd=str(PROJECT_DIR),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            self._settings_key = settings_key
            return self._process

    def _readline(self, stream: TextIO, timeout: int) -> str:
        ready, _, _ = select.select([stream], [], [], timeout)
        if not ready:
            raise SpeechSynthesisError("speech worker timed out")
        return stream.readline()

    def _synthesize_locked(self, settings: dict[str, Any], text: str, language: str | None, instruct: str | None) -> SpeechAudio:
        process = self._ensure_worker(settings)
        if process.stdin is None or process.stdout is None:
            raise SpeechSynthesisError("speech worker pipes are unavailable")
        with tempfile.NamedTemporaryFile(prefix="mde-qwen-tts-", suffix=".wav", delete=False) as handle:
            output_path = Path(handle.name)
        request = {
            "id": "speech-%d-%d" % (int(time.time() * 1000), os.getpid()),
            "text": text,
            "language": language or settings["language"],
            "instruct": instruct or settings["instruct"],
            "output_path": str(output_path),
        }
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
            process.stdin.flush()
            line = self._readline(process.stdout, int(settings["timeout_seconds"]))
            if not line:
                raise SpeechSynthesisError("speech worker exited without a response")
            response = json.loads(line)
            if not response.get("ok"):
                raise SpeechSynthesisError(str(response.get("error") or "speech worker failed"))
            audio_path = Path(str(response.get("path") or output_path))
            audio = audio_path.read_bytes()
            return SpeechAudio(
                data=audio,
                sample_rate=int(response.get("sample_rate") or 0),
                engine=str(response.get("engine") or "qwen3_voice_design"),
            )
        except (BrokenPipeError, OSError, json.JSONDecodeError) as exc:
            with self._process_lock:
                self._stop_worker_locked()
            raise SpeechSynthesisError(str(exc))
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass


speech_service = QwenSpeechService()
