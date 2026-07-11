"""v2 Create hero routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.model_showcase import ModelShowcaseService
from backend.v2.services.research_search import ResearchSearchService

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


router = APIRouter(prefix="/v2/create", tags=["create"]) if APIRouter else None
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
    def create_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "create.use")
        models = showcase_service.payload()["models"]
        research_service = ResearchSearchService()
        research_engines = research_service.engines()
        return {
            "image_models": [model for model in models if model.get("type") == "image" and model.get("enabled")],
            "text_models": [model for model in models if model.get("type") == "text" and model.get("route_enabled")],
            "wallpaper": legacy_adapter._safe_call("wallpaper_payload", {"source": "fallback"}, False),
            "modes": ["Chat", "Research", "Image"],
            "research_source_classes": research_service.source_classes(research_engines),
        }

    @router.post("/images")
    def generate_images(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "create.use")
        result = legacy_adapter._safe_call("generate_images", {}, payload or {})
        if isinstance(result, (tuple, list)) and len(result) == 2:
            status, data = result
            if int(status) >= 400:
                raise HTTPException(status_code=int(status), detail=data)
            return {"status": int(status), "response": data}
        return result if isinstance(result, dict) else {"response": result}
