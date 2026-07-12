"""v2 Research hero routes."""
from __future__ import annotations

import time
from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.research_dossier_store import ResearchDossierStore
from backend.v2.services.research_search import ResearchSearchService

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


router = APIRouter(prefix="/v2/research", tags=["research"]) if APIRouter else None
legacy_adapter = LegacyConsoleAdapter()
dossier_store = ResearchDossierStore()


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


def _research_service() -> ResearchSearchService:
    return ResearchSearchService(chat_completion=legacy_adapter.chat_completion)


def _research_catalog_payload(service: ResearchSearchService) -> dict[str, Any]:
    engines = service.engines()
    return {
        "engines": engines,
        "source_classes": service.source_classes(engines),
        "modes": ["Fast", "Balanced", "Deep"],
        "model_strategy": service.model_strategy(),
        "generated_at": time.time(),
    }


if router:

    @router.get("")
    def research_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "research.use")
        return _research_catalog_payload(_research_service())

    @router.get("/engines")
    def research_engines(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "research.use")
        return _research_catalog_payload(_research_service())

    @router.post("/search")
    def search(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "research.use")
        try:
            dossier = _research_service().search(payload)
            return dossier_store.save_dossier(dossier)
        except ValueError as exc:
            message = str(exc) or "research search request is invalid"
            code = "missing_query" if "query" in message.lower() else "invalid_engines"
            raise HTTPException(status_code=400, detail={"message": message, "code": code})

    @router.get("/dossiers/{dossier_id}")
    def get_dossier(
        dossier_id: str,
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "research.use")
        dossier = dossier_store.get_dossier(dossier_id)
        if not dossier:
            raise HTTPException(status_code=404, detail={"message": "research dossier not found", "code": "research_dossier_not_found"})
        return dossier

    @router.patch("/dossiers/{dossier_id}/pins")
    def update_pins(
        dossier_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "research.use")
        try:
            evidence_ids = payload.get("evidence_ids") if isinstance(payload, dict) else []
            return dossier_store.update_pins(dossier_id, evidence_ids)
        except KeyError:
            raise HTTPException(status_code=404, detail={"message": "research dossier not found", "code": "research_dossier_not_found"})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_evidence_pin"})

    @router.get("/dossiers/{dossier_id}/report")
    def get_report(
        dossier_id: str,
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "research.use")
        report = dossier_store.report_packet(dossier_id)
        if not report:
            raise HTTPException(status_code=404, detail={"message": "research dossier not found", "code": "research_dossier_not_found"})
        return report
