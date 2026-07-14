"""FastAPI application factory for the React v2 platform."""
from __future__ import annotations

import os
import threading

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException
except ImportError:  # pragma: no cover - dependency is installed by the v2 setup.
    FastAPI = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
    CORSMiddleware = None  # type: ignore[assignment]
    StaticFiles = None  # type: ignore[assignment]
    StarletteHTTPException = Exception  # type: ignore[assignment]

from backend.v2.api import analyst, auth, chat, code, console, cost_control, create, irc, models, observe, onboarding, operate, research, run, speech, startup, tmux_ws, tui
from backend.v2.services.performance_analyst import PerformanceAnalystService, analyst_worker
from backend.v2.services.startup_services import ensure_console_runtime
from src.console.services.app_config import ConsoleConfigService
from src.console.services.runtime_config import RuntimeConfigService
from src.console.utils.errors import error_payload, route_not_found_details


PROJECT_DIR = __import__("pathlib").Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"
BRANDING_DIR = PROJECT_DIR / "branding"


def generated_images_dir():
    config_path = PROJECT_DIR / "image-studio.py"
    config = ConsoleConfigService(file_path=config_path).load()
    return RuntimeConfigService(file_path=config_path, config=config).app_dir() / "images"


def v2_route_methods(app) -> dict[str, list[str]]:
    routes: dict[str, set[str]] = {}
    for route in getattr(app, "routes", []):
        path = str(getattr(route, "path", "") or "")
        if not path.startswith("/v2/"):
            continue
        methods = {str(method).upper() for method in (getattr(route, "methods", []) or []) if method}
        if not methods:
            continue
        routes.setdefault(path, set()).update(methods)
    return {path: sorted(methods) for path, methods in routes.items()}


def cors_origins() -> list[str]:
    raw = os.environ.get("MATTS_V2_CORS_ORIGINS", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return ["*"]


def create_app():
    if FastAPI is None:
        raise RuntimeError("FastAPI is required for the v2 backend. Install dependencies before starting it.")
    origins = cors_origins()
    app = FastAPI(title="MDE LLM-PROXY Console API", version="2.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/v2/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "2.2.0"}

    analyst_stop_event = threading.Event()

    @app.on_event("startup")
    def start_analyst_worker() -> None:
        if str(os.environ.get("MATTS_ANALYST_WORKER_ENABLED", "1")).lower() in {"0", "false", "no", "off"}:
            return
        thread = threading.Thread(
            target=analyst_worker,
            args=(lambda: PerformanceAnalystService(), analyst_stop_event),
            name="performance-analyst-worker",
            daemon=True,
        )
        thread.start()
        app.state.analyst_worker = thread
        app.state.analyst_stop_event = analyst_stop_event

    @app.on_event("startup")
    def start_enabled_console_runtime() -> None:
        if str(os.environ.get("MATTS_STARTUP_CONSOLE_RUNTIME_ENABLED", "1")).lower() in {"0", "false", "no", "off"}:
            return
        try:
            app.state.startup_console_runtime = ensure_console_runtime()
        except Exception as exc:
            app.state.startup_console_runtime = {"ok": False, "error": str(exc)}

    @app.on_event("shutdown")
    def stop_analyst_worker() -> None:
        analyst_stop_event.set()

    @app.on_event("shutdown")
    def stop_console_runtime() -> None:
        try:
            from backend.v2.api.tui import tui_session

            tui_session.stop()
        except Exception:
            pass

    @app.exception_handler(StarletteHTTPException)
    async def v2_http_exception_handler(request: Request, exc: StarletteHTTPException):  # type: ignore[valid-type]
        status_code = int(getattr(exc, "status_code", 500))
        if status_code in {404, 405} and str(request.url.path).startswith("/v2/") and JSONResponse is not None:
            route_methods = v2_route_methods(request.app)
            details = route_not_found_details(request.url.path, request.method, route_methods.keys(), route_methods=route_methods)
            if status_code == 405:
                return JSONResponse(
                    status_code=405,
                    content=error_payload(
                        "api method not allowed",
                        405,
                        code="api_method_not_allowed",
                        details=details,
                    ),
                )
            return JSONResponse(
                status_code=404,
                content=error_payload(
                    "api endpoint not found",
                    404,
                    code="api_endpoint_not_found",
                    details=details,
                ),
            )
        if JSONResponse is not None:
            detail = getattr(exc, "detail", "request failed")
            if isinstance(detail, dict):
                return JSONResponse(status_code=int(exc.status_code), content={"detail": detail})
            return JSONResponse(status_code=int(exc.status_code), content={"detail": str(detail)})
        raise exc

    if auth.router is not None:
        app.include_router(auth.router)
    if chat.router is not None:
        app.include_router(chat.router)
    if speech.router is not None:
        app.include_router(speech.router)
    if code.router is not None:
        app.include_router(code.router)
    if research.router is not None:
        app.include_router(research.router)
    if create.router is not None:
        app.include_router(create.router)
    if models.router is not None:
        app.include_router(models.router)
    if analyst.router is not None:
        app.include_router(analyst.router)
    if run.router is not None:
        app.include_router(run.router)
    if console.router is not None:
        app.include_router(console.router)
    if cost_control.router is not None:
        app.include_router(cost_control.router)
    if irc.router is not None:
        app.include_router(irc.router)
    if startup.router is not None:
        app.include_router(startup.router)
    if observe.router is not None:
        app.include_router(observe.router)
    if onboarding.router is not None:
        app.include_router(onboarding.router)
    if operate.router is not None:
        app.include_router(operate.router)
    if tui.router is not None:
        app.include_router(tui.router)
    if tmux_ws.router is not None:
        app.include_router(tmux_ws.router)
    if BRANDING_DIR.exists() and StaticFiles is not None:
        app.mount("/branding", StaticFiles(directory=str(BRANDING_DIR)), name="branding")
    if StaticFiles is not None:
        app.mount("/images", StaticFiles(directory=str(generated_images_dir())), name="generated-images")
    if FRONTEND_DIST.exists() and StaticFiles is not None:
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="react")
    return app


app = create_app() if FastAPI is not None else None
