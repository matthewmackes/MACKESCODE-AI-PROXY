#!/usr/bin/env python3
"""Run the MDE LLM-PROXY v2 FastAPI/React console."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from src.console.services.app_config import ConsoleConfigService
from src.console.services.runtime_config import RuntimeConfigService


PROJECT_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
FRONTEND_LOCK = FRONTEND_DIR / "package-lock.json"


def frontend_install_command() -> list[str]:
    if FRONTEND_LOCK.exists():
        return ["npm", "ci", "--no-audit"]
    return ["npm", "install", "--no-audit"]


def build_frontend() -> None:
    if not (FRONTEND_DIR / "node_modules").exists():
        subprocess.run(frontend_install_command(), cwd=str(FRONTEND_DIR), check=True)
    subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND_DIR), check=True)


def runtime_config() -> RuntimeConfigService:
    config = ConsoleConfigService(file_path=PROJECT_DIR / "image-studio.py").load()
    return RuntimeConfigService(file_path=PROJECT_DIR / "image-studio.py", config=config)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18182)
    parser.add_argument("--reload", action="store_true", help="Run uvicorn with reload enabled.")
    parser.add_argument("--build-frontend", action="store_true", help="Build React assets before starting FastAPI.")
    parser.add_argument("--cors-origin", action="append", default=[], help="Allowed browser origin for remote React sessions. May be repeated.")
    args = parser.parse_args()

    if args.cors_origin:
        os.environ["MATTS_V2_CORS_ORIGINS"] = ",".join(args.cors_origin)

    if args.build_frontend or not FRONTEND_DIST.exists():
        build_frontend()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required. Install v2 dependencies with: python3 -m pip install -r requirements-v2.txt", file=sys.stderr)
        return 1

    runtime = runtime_config()
    token = runtime.auth_token()
    print("React v2 console: http://%s:%d/?token=%s" % (args.host, args.port, token), flush=True)
    for address in runtime.local_addresses():
        print("Reachable React v2 URL: http://%s:%d/?token=%s" % (address, args.port, token), flush=True)

    uvicorn.run("backend.v2.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
