"""v2 Code hero routes, including session-scoped image attachments."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.code_attachments import CodeAttachmentStore
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


router = APIRouter(prefix="/v2/code", tags=["code"]) if APIRouter else None
legacy_adapter = LegacyConsoleAdapter()
attachment_store = CodeAttachmentStore()
showcase_service = ModelShowcaseService()


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


if router:

    @router.get("")
    def code_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "code.view")
        models = [model for model in showcase_service.payload()["models"] if model.get("type") == "text" and model.get("route_enabled")]
        return {
            "defaults": legacy_adapter.code_session_defaults(),
            "sessions": legacy_adapter.tmux_sessions()[0],
            "models": models,
            "attachment_policy": {
                "supported_types": ["image/png", "image/jpeg", "image/webp", "image/gif"],
                "storage": "session_scoped",
                "send_policy": "send_anyway_provider_decides",
            },
        }

    @router.post("/sessions/start")
    def start_session(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "tmux.control")
        status, data = legacy_adapter.start_code_session(payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=data)
        return data

    @router.post("/sessions/send")
    def send_session(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "tmux.control")
        status, data = legacy_adapter.send_code_session(str(payload.get("name") or ""), str(payload.get("text") or ""), enter=bool(payload.get("enter", True)))
        if status >= 400:
            raise HTTPException(status_code=status, detail=data)
        return data

    @router.post("/attachments")
    def create_attachment(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "code.attachments")
        try:
            return {"attachment": attachment_store.create(payload, actor=identity)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_attachment"})

    @router.get("/attachments")
    def list_attachments(
        request: Request,
        session_id: Optional[str] = Query(default="default"),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "code.view")
        return {"attachments": attachment_store.list(session_id or "default")}

    @router.delete("/attachments/{attachment_id}")
    def delete_attachment(
        attachment_id: str,
        request: Request,
        session_id: Optional[str] = Query(default="default"),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "code.attachments")
        return attachment_store.delete(session_id or "default", attachment_id)

    @router.post("/review")
    def review_images(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "chat.use")
        session_id = str(payload.get("session_id") or "default")
        prompt = str(payload.get("prompt") or "Review the attached image for the coding task.")
        attachment_ids = [str(item) for item in payload.get("attachment_ids", []) if item]
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for attachment_id in attachment_ids:
            try:
                content.append({"type": "image_url", "image_url": {"url": attachment_store.data_uri(session_id, attachment_id)}})
            except ValueError as exc:
                raise HTTPException(status_code=404, detail={"message": str(exc), "code": "attachment_not_found"})
        request_payload = {
            "model": payload.get("model"),
            "messages": [{"role": "user", "content": content}],
            "max_tokens": payload.get("max_tokens") or 1024,
        }
        status, result = legacy_adapter.chat_completion(request_payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=result)
        return {"status": status, "response": result, "attachments": attachment_ids}
