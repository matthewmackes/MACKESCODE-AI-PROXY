"""v2 cost-control status, threshold, and pause override routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.legacy_console import LegacyConsoleAdapter

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


router = APIRouter(prefix="/v2/cost-control", tags=["cost-control"]) if APIRouter else None
cost_adapter = LegacyConsoleAdapter()


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


def enforce_cost_pause(action: str, category: str, identity: dict[str, Any] | None = None) -> None:
    allowed, payload = cost_adapter.cost_control_guard(action, category=category, actor=identity or {})
    if allowed:
        return
    raise HTTPException(status_code=402, detail=payload)


if router:

    @router.get("")
    def cost_control_status(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        _identity(request, authorization, x_matts_console_token, token)
        return cost_adapter.cost_control_status()

    @router.post("/thresholds")
    def update_thresholds(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "cost_control.edit")
        payload = dict(payload or {})
        payload["actor"] = identity
        return cost_adapter.update_cost_control(payload)

    @router.post("/override")
    def override_pause(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "cost_control.override")
        payload = dict(payload or {})
        payload["actor"] = identity
        return cost_adapter.override_cost_control(payload)
