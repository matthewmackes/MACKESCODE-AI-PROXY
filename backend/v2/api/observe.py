"""v2 Observe, Govern, and Reporting routes."""
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


observe_adapter = LegacyConsoleAdapter()
router = APIRouter(prefix="/v2/observe", tags=["observe"]) if APIRouter else None


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


if router:

    @router.get("")
    def observe_payload(
        request: Request,
        days: Optional[int] = Query(default=7),
        trace_limit: Optional[int] = Query(default=50),
        audit_limit: Optional[int] = Query(default=50),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "billing.view")
        return observe_adapter.observe_payload(days=int(days or 7), trace_limit=int(trace_limit or 50), audit_limit=int(audit_limit or 50))

    @router.get("/traces")
    def traces(
        request: Request,
        limit: Optional[int] = Query(default=100),
        model: Optional[str] = Query(default=""),
        status: Optional[str] = Query(default=""),
        session: Optional[str] = Query(default=""),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "billing.view")
        return observe_adapter.observe_traces(limit=int(limit or 100), model=model or "", status=status or "", session=session or "")

    @router.post("/audit")
    def audit(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "billing.view")
        return observe_adapter.observe_audit(payload)

    @router.get("/evals")
    def evals(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "billing.view")
        return observe_adapter.eval_payload()

    @router.get("/telemetry")
    def telemetry(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "billing.view")
        return observe_adapter.telemetry_payload()

    @router.post("/reporting-export")
    def reporting_export(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "billing.view")
        try:
            return observe_adapter.export_reporting(payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"message": str(exc), "code": "reporting_export_unavailable"})

    @router.post("/decisions/explain")
    def explain_decision(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "billing.view")
        try:
            return observe_adapter.explain_decision(payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"message": str(exc), "code": "decision_explain_not_found"})
