"""Optional server-side speech synthesis for v2 Chat."""
from __future__ import annotations

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
from typing import Any, TextIO


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_QWEN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
DEFAULT_LANGUAGE = "Auto"
DEFAULT_INSTRUCT = "calm, clear mission-control voice with concise pacing"
DEFAULT_MAX_CHARS = 1200
DEFAULT_TIMEOUT_SECONDS = 600
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
    return {
        "engine": _env_value("MATTS_SPEECH_ENGINE", "browser").lower(),
        "python": _env_value("MATTS_QWEN_TTS_PYTHON", sys.executable),
        "model": _env_value("MATTS_QWEN_TTS_MODEL", DEFAULT_QWEN_MODEL),
        "device": _env_value("MATTS_QWEN_TTS_DEVICE", "auto"),
        "dtype": _env_value("MATTS_QWEN_TTS_DTYPE", "bfloat16"),
        "attn": _env_value("MATTS_QWEN_TTS_ATTN", ""),
        "language": _env_value("MATTS_QWEN_TTS_LANGUAGE", DEFAULT_LANGUAGE),
        "instruct": _env_value("MATTS_QWEN_TTS_INSTRUCT", DEFAULT_INSTRUCT),
        "max_chars": _env_int("MATTS_QWEN_TTS_MAX_CHARS", DEFAULT_MAX_CHARS, minimum=200),
        "timeout_seconds": _env_int("MATTS_QWEN_TTS_TIMEOUT", DEFAULT_TIMEOUT_SECONDS, minimum=30),
    }


def speech_status_payload(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or speech_settings()
    enabled = settings["engine"] == "qwen3"
    configured = bool(settings["python"])
    python_available = _python_available(str(settings["python"]))
    available = enabled and configured and python_available
    if not enabled:
        reason = "MATTS_SPEECH_ENGINE is not qwen3"
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
        "input": {
            "browser_speech_recognition": True,
            "browser_speech_synthesis": True,
        },
    }


class QwenSpeechService:
    """Manages one optional Qwen3-TTS worker process."""

    def __init__(self, worker_script: Path | None = None) -> None:
        self.worker_script = worker_script or PROJECT_DIR / "scripts" / "qwen_tts_worker.py"
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
            return self._synthesize_locked(settings, text, language, instruct)
        finally:
            self._request_lock.release()

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
