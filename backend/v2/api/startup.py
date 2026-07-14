"""v2 boot/startup service management routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.startup_services import StartupServiceManager

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


router = APIRouter(prefix="/v2/startup", tags=["startup"]) if APIRouter else None
manager = StartupServiceManager()


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


if router:

    @router.get("")
    def startup_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "startup.view")
        return manager.status_payload()

    @router.post("/config")
    def update_startup_config(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "startup.admin")
        return manager.update_config(payload or {})

    @router.post("/services/{service_id}/{action}")
    def service_action(
        service_id: str,
        action: str,
        request: Request,
        payload: Optional[dict[str, Any]] = None,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "startup.admin")
        try:
            return manager.action(service_id, action, payload or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_startup_action"})
