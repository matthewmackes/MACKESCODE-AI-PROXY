#!/usr/bin/env python3
"""Headless browser smoke tests for the unified console."""
import argparse
import importlib.util
import os
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_studio():
    os.environ["MATTS_CONSOLE_DISABLE_AUTH"] = "1"
    os.environ["MATTS_MODEL_CONFIG_FILE"] = str(ROOT / "config" / "models.json")
    spec = importlib.util.spec_from_file_location("image_studio_browser_smoke", ROOT / "image-studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_for_smoke(studio, tmp):
    os.environ["MATTS_CONSOLE_DISABLE_AUTH"] = "1"
    os.environ["MATTS_SERVERLESS_CATALOG_CACHE_FILE"] = str(tmp / "serverless-catalog.json")
    os.environ["MATTS_DEDICATED_CONFIG_FILE"] = str(tmp / "dedicated-inference.json")
    os.environ["MATTS_DEDICATED_EVENTS_FILE"] = str(tmp / "dedicated-events.jsonl")
    os.environ["MATTS_TMUX_SESSION_REGISTRY_FILE"] = str(tmp / "tmux-sessions.json")
    os.environ["MATTS_VALUE_SET_COST_FILE"] = str(tmp / "usage.jsonl")
    os.environ["CLAUDE_DO_BUDGET_FILE"] = str(tmp / "budgets.json")

    proxy_sync = {
        "listening": True,
        "in_sync": True,
        "host": "127.0.0.1",
        "port": 18081,
        "url": "http://127.0.0.1:18081",
        "details": {
            "reason": "browser smoke stub",
            "capabilities": {
                "models": list(studio.ALL_MODELS),
                "model_config_state": {"loaded": True, "stale": False},
                "dedicated": {},
            },
            "expected_models": list(studio.ALL_MODELS),
        },
    }
    studio.start_proxy_if_needed = lambda force=False: None
    studio.proxy_sync_payload = lambda force=False: proxy_sync
    studio.proxy_in_sync = lambda: (True, proxy_sync["details"])
    studio.proxy_get = lambda path: (200, {"ok": True, "path": path})
    studio.port_open = lambda host, port: True
    studio.launcher_health = lambda: {"ok": True, "path": str(ROOT / "claude-DO.sh")}
    studio.tmux_sessions = lambda: []
    studio.tmux_session_items = lambda: []
    studio.agentboard_payload = lambda: {
        "sessions": [],
        "tasks": [],
        "evals": {},
        "leaderboard": [],
        "logs": [],
    }
    studio.sync_serverless_model_catalog = lambda force=False, validate_access=False: {
        "ok": True,
        "added": 0,
        "updated": 0,
        "removed": 0,
        "total": len(studio.load_model_registry(include_disabled=True)),
        "catalog": {"ok": True, "source": "browser-smoke", "fetched_at": 0, "error": ""},
        "access_validation": {"checked": 0, "disabled": 0},
    }
    studio.cost_summary_payload = lambda: {
        "month_to_date_total_usd": 0,
        "last_24h_total_usd": 0,
        "dedicated_month_to_date_usd": 0,
        "dedicated_last_24h_usd": 0,
        "dedicated_runtime": {"month_seconds": 0},
        "last_24h_source": "browser_smoke",
        "digitalocean_configured": False,
    }
    studio.digitalocean_health_snapshot = lambda: {"platform": {}, "account": {}, "prepay": {}, "errors": []}
    studio.dedicated_events = lambda limit=50: []
    studio.dedicated_status_payload = lambda poll=True: {
        "dedicated": {"state": "not_configured", "steps": []},
        "events": [],
        "models": studio.models_payload(refresh_catalog=False),
        "digitalocean": {},
    }
    studio.wallpaper_payload = lambda randomize=False: {
        "url": "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
        "caption": "Browser smoke wallpaper",
        "title": "Browser smoke wallpaper",
        "copyright": "",
    }


def start_server(studio):
    server = ThreadingHTTPServer(("127.0.0.1", 0), studio.StudioHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, "http://127.0.0.1:%d/" % server.server_address[1]


def run_browser_smoke(base_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_selector("#claude.active")
        page.get_by_role("button", name="Create").click()
        page.wait_for_selector("#create.active")
        page.wait_for_selector("#chat-log")
        page.get_by_label("Open Console").click()
        page.wait_for_selector("#console.active")
        page.wait_for_selector("#models-editor")
        page.get_by_role("button", name="Coding").click()
        page.wait_for_selector("#claude.active")
        header = page.locator("header").inner_text(timeout=5000)
        assert "Mackes Code" in header
        page.goto(base_url + "terminal?name=browser-smoke", wait_until="domcontentloaded")
        page.wait_for_selector("#terminal")
        assert "Mackes Code" in page.title()
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--required", action="store_true", help="fail instead of skipping when Playwright is unavailable")
    args = parser.parse_args()
    try:
        import playwright  # noqa: F401
    except Exception as exc:
        message = "Playwright is not installed; skipping browser smoke test."
        if args.required:
            raise SystemExit("%s Install with: python3 -m pip install playwright && python3 -m playwright install chromium" % message) from exc
        print(message)
        return 0

    with tempfile.TemporaryDirectory() as tmpdir:
        studio = load_studio()
        patch_for_smoke(studio, Path(tmpdir))
        server, url = start_server(studio)
        try:
            run_browser_smoke(url)
            print("Browser smoke passed: %s" % url)
        finally:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
