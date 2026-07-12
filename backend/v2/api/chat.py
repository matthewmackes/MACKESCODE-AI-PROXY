"""v2 Chat hero routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.chat_response import normalize_chat_result
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.model_showcase import ModelShowcaseService
from backend.v2.services.speech import speech_service

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


router = APIRouter(prefix="/v2/chat", tags=["chat"]) if APIRouter else None
legacy_adapter = LegacyConsoleAdapter()
showcase_service = ModelShowcaseService()


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


if router:

    @router.get("")
    def chat_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "console.view")
        models = [model for model in showcase_service.payload()["models"] if model.get("type") == "text" and model.get("route_enabled")]
        speech_status = speech_service.status()
        server_available = bool(speech_status.get("available"))
        return {
            "models": models,
            "default_model": models[0]["id"] if models else "",
            "voice": {
                "mode": speech_status.get("mode") or "browser_speech_synthesis",
                "fallback_mode": speech_status.get("fallback_mode") or "browser_speech_synthesis",
                "style": "Qwen3 VoiceDesign" if server_available else "calm mission-computer",
                "server_engine": speech_status,
                "input_mode": "browser_speech_recognition",
                "enabled_by_default": True,
                "max_chars": int(speech_status.get("max_chars") or 1200),
                "language": speech_status.get("language") or "Auto",
                "languages": speech_status.get("languages") or [],
                "instruct": speech_status.get("instruct") or "",
                "preview": "MDE LLM-PROXY voice online. I will read concise model responses when voice is enabled.",
            },
        }

    @router.post("")
    def chat_completion(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "chat.use")
        payload = dict(payload or {})
        payload.pop("trace_status_on_error", None)
        payload.pop("trace_origin", None)
        try:
            status, result = legacy_adapter.chat_completion(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_chat"})
        if status >= 400:
            raise HTTPException(status_code=status, detail=result)
        return {"status": status, "response": normalize_chat_result(result, str(payload.get("client_selected_model_id") or ""))}
