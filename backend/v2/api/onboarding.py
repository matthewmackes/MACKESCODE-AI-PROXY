"""v2 onboarding checklist and prepared model-template routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.onboarding_templates import OnboardingTemplateService

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


router = APIRouter(prefix="/v2/onboarding", tags=["onboarding"]) if APIRouter else None
legacy_adapter = LegacyConsoleAdapter()
template_service = OnboardingTemplateService()


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


def _payload(model_templates: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "onboarding": legacy_adapter.onboarding_payload(),
        "model_templates": model_templates or template_service.payload(),
    }


if router:

    @router.get("")
    def onboarding_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "console.view")
        return _payload()

    @router.post("/model-templates/seed")
    def seed_model_templates(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        return _payload(template_service.seed_missing())

    @router.post("/complete")
    def complete_onboarding(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.config_drift.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        try:
            return {"onboarding": legacy_adapter.complete_onboarding_item(payload), "model_templates": template_service.payload()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "onboarding_invalid"})
