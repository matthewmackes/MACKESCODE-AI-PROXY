"""v2 AI performance analyst routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.api.cost_control import enforce_cost_pause
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.performance_analyst import PerformanceAnalystService

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


router = APIRouter(prefix="/v2/analyst", tags=["analyst"]) if APIRouter else None
analyst_adapter = LegacyConsoleAdapter()


def analyst_service() -> PerformanceAnalystService:
    return PerformanceAnalystService(legacy_adapter=analyst_adapter)


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


if router:

    @router.get("")
    def analyst_payload(
        request: Request,
        force: Optional[bool] = Query(default=False),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "analyst.view")
        if force:
            enforce_cost_pause("analyst.run", "llm_service", identity)
        return analyst_service().payload(force=bool(force), actor=identity)

    @router.post("/run")
    def analyst_run(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "analyst.run")
        enforce_cost_pause("analyst.run", "llm_service", identity)
        force = bool((payload or {}).get("force", True))
        return analyst_service().payload(force=force, actor=identity)

    @router.post("/findings/{finding_id}/ack")
    def analyst_ack(
        finding_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "analyst.ack")
        result = analyst_service().store.acknowledge_finding(finding_id, actor=identity)
        if not result:
            raise HTTPException(status_code=404, detail={"message": "analyst finding not found", "code": "analyst_finding_not_found"})
        return {"finding": result}
