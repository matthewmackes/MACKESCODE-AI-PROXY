"""v2 Run Experience routes."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.run_store import RunStore
from src.console.services.eval_gates import EvalGateBlocked
from src.console.services.local_rag import LocalRagService

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


run_store = RunStore()
legacy_console = LegacyConsoleAdapter()
router = APIRouter(prefix="/v2/run", tags=["run"]) if APIRouter else None
PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_DIR = Path.home() / ".cache" / "matts-value-set" / "studio"


def local_rag_service() -> LocalRagService:
    config_file = Path(os.environ.get("MATTS_V2_RAG_CONFIG_FILE", DEFAULT_RUNTIME_DIR / "v2-rag-config.json"))
    index_file = Path(os.environ.get("MATTS_V2_RAG_INDEX_FILE", DEFAULT_RUNTIME_DIR / "v2-rag-index.json"))
    return LocalRagService(
        project_dir=Path(os.environ.get("MATTS_V2_RAG_PROJECT_DIR", PROJECT_DIR)),
        config_file=lambda: config_file,
        index_file=lambda: index_file,
    )


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


if router:

    @router.get("")
    def run_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        payload = run_store.payload()
        payload["local_rag"] = local_rag_service().payload()
        return payload

    @router.get("/rag")
    def rag_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"local_rag": local_rag_service().payload()}

    @router.post("/rag/config")
    def save_rag_config(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        return {"config": local_rag_service().save_config(payload)}

    @router.post("/rag/index")
    def index_rag(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        return {"index": local_rag_service().index(payload)}

    @router.post("/rag/search")
    def search_rag(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"results": local_rag_service().search(payload)}

    @router.get("/replays")
    def replay_records(
        request: Request,
        limit: Optional[int] = Query(default=50),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return legacy_console.replay_records(limit=int(limit or 50))

    @router.post("/replay/snapshot")
    def replay_snapshot(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        try:
            return legacy_console.replay_snapshot(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_replay_snapshot"})

    @router.post("/replay")
    def run_replay(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            return legacy_console.run_replay(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_replay"})

    @router.get("/workspace-bundles")
    def workspace_bundles(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return legacy_console.workspace_bundles()

    @router.post("/workspace-bundles/export")
    def export_workspace_bundle(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        payload = dict(payload or {})
        payload["actor"] = identity
        try:
            return legacy_console.export_workspace_bundle(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_workspace_bundle_export"})

    @router.post("/workspace-bundles/preview")
    def preview_workspace_bundle_import(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        try:
            return legacy_console.preview_workspace_bundle_import(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_workspace_bundle_preview"})

    @router.post("/workspace-bundles/import")
    def import_workspace_bundle(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        payload = dict(payload or {})
        payload["actor"] = identity
        try:
            return legacy_console.import_workspace_bundle(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_workspace_bundle_import"})

    @router.post("/context-window")
    def inspect_context_window(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        try:
            return legacy_console.context_window(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_context_window"})

    @router.post("/chat")
    def run_chat(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "chat.use")
        try:
            status, result = legacy_console.chat_completion(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_chat_run"})
        if status >= 400:
            raise HTTPException(status_code=status, detail=result)
        return {"status": status, "response": result}

    @router.get("/prompt-templates")
    def prompt_templates(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"prompt_templates": run_store.list_prompt_templates()}

    @router.post("/prompt-templates")
    def save_prompt_template(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            item = run_store.save_prompt_template(payload)
        except EvalGateBlocked as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "code": "eval_gate_blocked", "eval_gate": exc.gate})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_prompt_template"})
        return {"prompt_template": item}

    @router.post("/prompt-templates/preview")
    def preview_prompt_template(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"preview": run_store.preview_prompt_template(payload)}

    @router.get("/prompt-templates/{template_id}/versions")
    def prompt_template_versions(
        template_id: str,
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"versions": run_store.list_prompt_template_versions(template_id)}

    @router.post("/prompt-templates/{template_id}/rollback")
    def rollback_prompt_template(
        template_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            item = run_store.rollback_prompt_template(template_id, int(payload.get("version") or 0))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"message": str(exc), "code": "prompt_template_version_not_found"})
        return {"prompt_template": item}

    @router.get("/profiles")
    def run_profiles(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"run_profiles": run_store.list_run_profiles()}

    @router.post("/profiles")
    def save_run_profile(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            item = run_store.save_run_profile(payload)
        except EvalGateBlocked as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "code": "eval_gate_blocked", "eval_gate": exc.gate})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_run_profile"})
        return {"run_profile": item}

    @router.post("/eval-gates/preview")
    def preview_eval_gate(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"eval_gate": run_store.preview_eval_gate(payload)}

    @router.get("/eval-gates")
    def eval_gate_records(
        request: Request,
        target_id: Optional[str] = Query(default=""),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"eval_gate_records": run_store.list_eval_gate_records(target_id or "")}

    @router.get("/profiles/{profile_id}/versions")
    def run_profile_versions(
        profile_id: str,
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"versions": run_store.list_run_profile_versions(profile_id)}

    @router.post("/profiles/{profile_id}/activate")
    def activate_run_profile(
        profile_id: str,
        request: Request,
        payload: Optional[dict[str, Any]] = None,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            payload = payload if isinstance(payload, dict) else {}
            item = run_store.activate_run_profile(profile_id, payload.get("eval_gate") if isinstance(payload.get("eval_gate"), dict) else None)
        except EvalGateBlocked as exc:
            raise HTTPException(status_code=409, detail={"message": str(exc), "code": "eval_gate_blocked", "eval_gate": exc.gate})
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"message": str(exc), "code": "run_profile_not_found"})
        return {"run_profile": item}

    @router.post("/profiles/{profile_id}/rollback")
    def rollback_run_profile(
        profile_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            item = run_store.rollback_run_profile(profile_id, int(payload.get("version") or 0))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_run_profile_rollback"})
        return {"run_profile": item}

    @router.get("/records")
    def run_records(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"run_records": run_store.list_run_records()}

    @router.post("/records")
    def save_run_record(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            item = run_store.save_run_record(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_run_record"})
        return {"run_record": item}

    @router.get("/branches")
    def conversation_branches(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"conversation_branches": run_store.list_conversation_branches()}

    @router.post("/branches")
    def save_conversation_branch(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            item = run_store.save_conversation_branch(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_conversation_branch"})
        return {"conversation_branch": item}

    @router.get("/session-snapshots")
    def session_snapshots(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.view")
        return {"session_snapshots": run_store.list_session_snapshots()}

    @router.post("/session-snapshots")
    def save_session_snapshot(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "run.edit")
        try:
            item = run_store.save_session_snapshot(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_session_snapshot"})
        return {"session_snapshot": item}
