"""FastAPI routes for the React Console TUI bridge."""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Optional

from backend.v2.services.tui_session import GlobalTuiSession
from backend.v2.api.auth import capability_service, identity_from_request, identity_from_values

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
except ImportError:  # pragma: no cover - allows syntax checks before dependencies are installed.
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]
    WebSocket = object  # type: ignore[assignment]
    WebSocketDisconnect = Exception  # type: ignore[assignment]


tui_session = GlobalTuiSession()
router = APIRouter(prefix="/v2/console/tui", tags=["console-tui"]) if APIRouter else None


if router:

    def require_action(identity: dict[str, object], action: str) -> None:
        decision = capability_service.decide(identity, action)
        if not decision.allowed:
            raise HTTPException(status_code=403, detail=decision.to_dict())

    @router.get("/status")
    def status(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tui.view")
        tui_session.ensure_started()
        return tui_session.status()

    @router.post("/control/acquire")
    def acquire_control(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tui.control")
        client_id = str(payload.get("client_id") or "")
        force = bool(payload.get("force"))
        return {"lease": tui_session.acquire_control(client_id, force=force)}

    @router.post("/control/release")
    def release_control(
        payload: dict[str, object],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tui.control")
        client_id = str(payload.get("client_id") or "")
        force = bool(payload.get("force"))
        return {"lease": tui_session.release_control(client_id, force=force)}

    @router.post("/restart")
    def restart(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, object]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        require_action(identity, "tui.control")
        return tui_session.restart()

    @router.websocket("/ws")
    async def websocket_tui(websocket: WebSocket) -> None:
        await websocket.accept()
        client_id = websocket.query_params.get("client_id") or str(uuid.uuid4())
        token = websocket.query_params.get("token") or ""
        headers = {
            "authorization": websocket.headers.get("authorization") or "",
            "x-matts-console-token": websocket.headers.get("x-matts-console-token") or "",
        }
        identity = identity_from_values(str(websocket.url), headers, token)
        view_decision = capability_service.decide(identity, "tui.view")
        control_decision = capability_service.decide(identity, "tui.control")
        if not view_decision.allowed:
            await websocket.send_text(json.dumps({"type": "denied", "decision": view_decision.to_dict()}))
            await websocket.close(code=4403)
            return
        tui_session.ensure_started()
        await websocket.send_text(json.dumps({"type": "status", "client_id": client_id, "can_control": control_decision.allowed, "status": tui_session.status()}))

        async def pump_output() -> None:
            while True:
                chunk = await asyncio.to_thread(tui_session.read_available, 0.1)
                if chunk:
                    await websocket.send_bytes(chunk)
                await asyncio.sleep(0.01)

        output_task = asyncio.create_task(pump_output())
        try:
            while True:
                message = await websocket.receive()
                if "bytes" in message and message["bytes"] is not None:
                    if not control_decision.allowed:
                        await websocket.send_text(json.dumps({"type": "readonly", "message": "tui.control permission required"}))
                        continue
                    if not tui_session.write(client_id, message["bytes"]):
                        await websocket.send_text(json.dumps({"type": "readonly", "message": "control lease required"}))
                elif "text" in message and message["text"] is not None:
                    payload = json.loads(message["text"])
                    if payload.get("type") == "input":
                        if not control_decision.allowed:
                            await websocket.send_text(json.dumps({"type": "readonly", "message": "tui.control permission required"}))
                            continue
                        data = str(payload.get("data") or "").encode("utf-8")
                        if not tui_session.write(client_id, data):
                            await websocket.send_text(json.dumps({"type": "readonly", "message": "control lease required"}))
        except WebSocketDisconnect:
            pass
        finally:
            output_task.cancel()
