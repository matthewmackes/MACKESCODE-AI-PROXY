"""v2 identity, capability, and policy-decision routes."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from backend.v2.services.capabilities import V2CapabilityService
from src.console.handlers.auth_handler import AuthHandler
from src.console.services.app_config import ConsoleConfigService
from src.console.services.runtime_config import RuntimeConfigService

try:
    from fastapi import APIRouter, Header, Query, Request
except ImportError:  # pragma: no cover - permits syntax checks before v2 deps.
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CONSOLE_CONFIG = PROJECT_DIR / "config" / "console.json"
CONSOLE_ENTRYPOINT = PROJECT_DIR / "image-studio.py"


def _read_console_config() -> dict[str, Any]:
    try:
        return ConsoleConfigService(file_path=CONSOLE_ENTRYPOINT, config_path=Path(os.environ.get("MATTS_CONSOLE_CONFIG_FILE", DEFAULT_CONSOLE_CONFIG))).load()
    except Exception:
        path = Path(os.environ.get("MATTS_CONSOLE_CONFIG_FILE", DEFAULT_CONSOLE_CONFIG))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        return data if isinstance(data, dict) else {}


def _runtime_config() -> RuntimeConfigService:
    return RuntimeConfigService(file_path=CONSOLE_ENTRYPOINT, config=_read_console_config())


def _auth_enabled() -> bool:
    raw = os.environ.get("MATTS_CONSOLE_AUTH_ENABLED")
    if raw is not None:
        return raw not in {"0", "false", "False", "no", "NO"}
    return _runtime_config().auth_enabled()


def _auth_token() -> str:
    raw = os.environ.get("MATTS_CONSOLE_AUTH_TOKEN", "") or os.environ.get("MATTS_CONSOLE_TOKEN", "")
    if raw:
        return raw
    return _runtime_config().auth_token()


def _role_tokens() -> dict[str, Any]:
    raw = os.environ.get("MATTS_CONSOLE_ROLE_TOKENS", "")
    if raw:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    config = _read_console_config()
    auth = config.get("auth") if isinstance(config.get("auth"), dict) else {}
    role_tokens = auth.get("role_tokens")
    return role_tokens if isinstance(role_tokens, dict) else {}


def _headers_for_auth(request: Request, authorization: Optional[str], console_token: Optional[str]) -> dict[str, str]:
    headers = {}
    if authorization:
        headers["authorization"] = authorization
    if console_token:
        headers["x-matts-console-token"] = console_token
    for key in ("authorization", "x-matts-console-token"):
        value = request.headers.get(key) if hasattr(request, "headers") else None
        if value and key not in headers:
            headers[key] = value
    return headers


def identity_from_values(path: str, headers: Optional[dict[str, str]] = None, query_token: Optional[str] = None) -> dict[str, Any]:
    auth = AuthHandler(
        auth_enabled=_auth_enabled,
        auth_token=_auth_token,
        role_tokens=_role_tokens,
        session_verifier=lambda token: None,
    )
    if query_token:
        joiner = "&" if "?" in path else "?"
        path = path + joiner + "token=" + query_token
    return auth.identity(path, headers or {})


def identity_from_request(request: Request, authorization: Optional[str] = None, console_token: Optional[str] = None, query_token: Optional[str] = None) -> dict[str, Any]:
    path = str(getattr(request, "url", "/") or "/")
    return identity_from_values(path, _headers_for_auth(request, authorization, console_token), query_token)


capability_service = V2CapabilityService()
router = APIRouter(prefix="/v2", tags=["identity"]) if APIRouter else None


if router:

    @router.get("/me")
    def me(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        return {"actor": identity_from_request(request, authorization, x_matts_console_token, token)}

    @router.get("/me/capabilities")
    def capabilities(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        return capability_service.capabilities_for(identity)

    @router.post("/policy/decide")
    def decide(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = identity_from_request(request, authorization, x_matts_console_token, token)
        action = str(payload.get("action") or "")
        return {"decision": capability_service.decide(identity, action).to_dict()}
