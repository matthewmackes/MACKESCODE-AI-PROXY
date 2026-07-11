"""v2 Chat hero routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.model_showcase import ModelShowcaseService

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
        return {
            "models": models,
            "default_model": models[0]["id"] if models else "",
            "voice": {
                "mode": "browser_speech_synthesis",
                "style": "calm mission-computer",
                "enabled_by_default": True,
                "max_chars": 1200,
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
        return {"status": status, "response": result}
