"""v2 routes for read-only Console operational state."""
from __future__ import annotations

from typing import Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.services.legacy_console import LegacyConsoleAdapter

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover - allows syntax checks before v2 deps are installed.
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


console_adapter = LegacyConsoleAdapter()
router = APIRouter(prefix="/v2/console", tags=["console"]) if APIRouter else None


if router:

    def require_action(identity: dict[str, object], action: str) -> None:
        decision = capability_service.decide(identity, action)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.to_dict())

    @router.get("/overview")
    def overview(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "console.view")
        return console_adapter.overview()

    @router.get("/commands")
    def commands(
        request: Request,
        q: Optional[str] = Query(default=""),
        session: Optional[str] = Query(default=""),
        trace_id: Optional[str] = Query(default=""),
        model: Optional[str] = Query(default=""),
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "console.view")
        return console_adapter.command_palette(q or "", actor=identity, context={"session": session or "", "trace_id": trace_id or "", "model": model or ""})

    @router.post("/commands/dispatch")
    def dispatch_command(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "console.view")
        payload = dict(payload or {})
        payload["actor"] = identity
        try:
            return console_adapter.dispatch_command(payload)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"message": str(exc), "code": "command_permission_denied"})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"message": str(exc), "code": "invalid_command"})

    @router.get("/code-sessions/defaults")
    def code_session_defaults(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "console.view")
        return console_adapter.code_session_defaults()

    @router.get("/code-sessions")
    def code_sessions(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "console.view")
        return {"sessions": console_adapter.tmux_sessions()[0]}

    def service_response(status: int, payload: dict[str, object]) -> dict[str, object]:
        if status >= 400:
            raise HTTPException(status_code=status, detail=payload)
        return payload

    @router.get("/tmux")
    def tmux_workspace(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "console.view")
        return console_adapter.tmux_workspace()

    @router.post("/tmux/start")
    def start_tmux_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.start_tmux_session(payload)
        return service_response(status, data)

    @router.post("/tmux/capture")
    def capture_tmux_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.capture_tmux_session(str(payload.get("name") or ""))
        return service_response(status, data)

    @router.post("/tmux/send")
    def send_tmux_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.send_tmux_text(
            str(payload.get("name") or ""),
            str(payload.get("text") or ""),
            enter=bool(payload.get("enter", True)),
        )
        return service_response(status, data)

    @router.post("/tmux/key")
    def key_tmux_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.send_tmux_key(str(payload.get("name") or ""), str(payload.get("key") or ""))
        return service_response(status, data)

    @router.post("/tmux/rename")
    def rename_tmux_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.rename_tmux_session(
            str(payload.get("old_name") or payload.get("name") or ""),
            str(payload.get("new_name") or payload.get("name") or ""),
            str(payload.get("display_name") or "") or None,
        )
        return service_response(status, data)

    @router.post("/tmux/stop")
    def stop_tmux_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.stop_tmux_session(str(payload.get("name") or ""))
        return service_response(status, data)

    @router.post("/code-sessions/start")
    def start_code_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.start_code_session(payload)
        return service_response(status, data)

    @router.post("/code-sessions/permissions")
    def preview_code_session_permissions(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        return {"permission_preview": console_adapter.preview_code_session_permissions(payload)}

    @router.post("/code-sessions/capture")
    def capture_code_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.capture_code_session(str(payload.get("name") or ""))
        return service_response(status, data)

    @router.post("/code-sessions/send")
    def send_code_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.send_code_session(
            str(payload.get("name") or ""),
            str(payload.get("text") or ""),
            enter=bool(payload.get("enter", True)),
        )
        return service_response(status, data)

    @router.post("/code-sessions/stop")
    def stop_code_session(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tmux.control")
        status, data = console_adapter.stop_code_session(str(payload.get("name") or ""))
        return service_response(status, data)
