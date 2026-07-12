"""v2 speech routes."""
from __future__ import annotations

from io import BytesIO
from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.speech import SpeechBusyError, SpeechConfigError, SpeechSynthesisError, speech_service

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
    from fastapi.responses import StreamingResponse
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]
    StreamingResponse = None  # type: ignore[assignment]


router = APIRouter(prefix="/v2/speech", tags=["speech"]) if APIRouter else None


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


def _detail(message: str, code: str, **extra: Any) -> dict[str, Any]:
    payload = {"message": message, "code": code}
    payload.update(extra)
    return payload


if router:

    @router.get("")
    def speech_status(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "console.view")
        return speech_service.status()

    @router.post(
        "/synthesize",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "WAV speech audio",
                "content": {
                    "audio/wav": {
                        "schema": {"type": "string", "format": "binary"},
                    },
                },
            },
        },
    )
    def synthesize_speech(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ):
        if StreamingResponse is None:
            raise RuntimeError("FastAPI responses are unavailable")
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "speech.synthesize")
        status = speech_service.status()
        text = str((payload or {}).get("text") or "").strip()
        max_chars = int(status.get("max_chars") or 1200)
        if not text:
            raise HTTPException(status_code=400, detail=_detail("speech text is required", "speech_text_required"))
        if len(text) > max_chars:
            raise HTTPException(
                status_code=413,
                detail=_detail("speech text exceeds %d characters" % max_chars, "speech_text_too_long", max_chars=max_chars),
            )
        try:
            audio = speech_service.synthesize(
                text,
                language=str((payload or {}).get("language") or status.get("language") or ""),
                instruct=str((payload or {}).get("instruct") or status.get("instruct") or ""),
            )
        except SpeechBusyError as exc:
            raise HTTPException(status_code=429, detail=_detail(str(exc), "speech_engine_busy"))
        except SpeechConfigError as exc:
            raise HTTPException(status_code=503, detail=_detail(str(exc), "speech_unavailable"))
        except SpeechSynthesisError as exc:
            raise HTTPException(status_code=502, detail=_detail(str(exc), "speech_synthesis_failed"))
        return StreamingResponse(
            BytesIO(audio.data),
            media_type=audio.mime_type,
            headers={
                "x-matts-speech-engine": audio.engine,
                "x-matts-speech-sample-rate": str(audio.sample_rate),
            },
        )
