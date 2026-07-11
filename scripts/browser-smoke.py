#!/usr/bin/env python3
"""Headless browser smoke tests for the unified console."""
import argparse
import importlib.util
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urljoin


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_studio():
    os.environ["MATTS_CONSOLE_DISABLE_AUTH"] = "1"
    os.environ["MATTS_MODEL_CONFIG_FILE"] = str(ROOT / "config" / "models.json")
    spec = importlib.util.spec_from_file_location("image_studio_browser_smoke", ROOT / "image-studio.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def smoke_quota_decision(path="", data=None, actor=None, actor_key=""):
    data = data if isinstance(data, dict) else {}
    return {
        "enabled": False,
        "managed": False,
        "allowed": True,
        "status": "allowed",
        "action": str(data.get("action") or ""),
        "route": str(path or data.get("path") or ""),
        "actor": actor or {},
        "actor_key": actor_key or "",
        "warnings": [],
        "blocks": [],
        "checks": [],
        "policy_decision": {
            "domain": "quota",
            "allowed": True,
            "reason": "browser_smoke_quota_disabled",
            "effects": {},
        },
    }


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
    studio.quota_planner_payload = lambda actor=None, actor_key="": {
        "enabled": False,
        "warn_fraction": 0.0,
        "actor": actor or {},
        "actor_key": actor_key or "",
        "quotas": [],
        "recent": [],
        "policy": {},
    }
    studio.quota_planner_preview = smoke_quota_decision
    studio.quota_planner_consume = smoke_quota_decision


def smoke_handler_class(studio, quiet=False):
    if not quiet:
        return studio.StudioHandler

    class QuietSmokeHandler(studio.StudioHandler):
        def log_message(self, fmt, *args):
            return None

    return QuietSmokeHandler


def start_server(studio, quiet=False):
    server = ThreadingHTTPServer(("127.0.0.1", 0), smoke_handler_class(studio, quiet=quiet))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, "http://127.0.0.1:%d/" % server.server_address[1]


def terminal_smoke_url(base_url):
    return urljoin(base_url, "terminal") + "?" + urlencode({"name": "browser-smoke", "autoconnect": "0"})


def run_browser_smoke(base_url):
    from playwright.sync_api import sync_playwright

    def assert_create_layout(page, width, height):
        page.set_viewport_size({"width": width, "height": height})
        page.get_by_role("button", name="Create", exact=True).click()
        page.wait_for_selector("#create.active")
        page.wait_for_selector("#create-greeting")
        page.wait_for_selector("#wallpaper-caption")
        page.wait_for_selector("#create-mood")
        page.wait_for_selector("#wallpaper-info")
        page.wait_for_selector(".create-search")

        def collect_metrics():
            return page.evaluate(
                """() => {
                    const view = document.querySelector('#create');
                    const search = document.querySelector('.create-search');
                    const greeting = document.querySelector('#create-greeting');
                    const caption = document.querySelector('.create-caption');
                    const mood = document.querySelector('#create-mood');
                    const info = document.querySelector('#wallpaper-info');
                    const rect = el => {
                        const r = el.getBoundingClientRect();
                        return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height};
                    };
                    const visible = el => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                    };
                    return {
                        viewportWidth: innerWidth,
                        viewportHeight: innerHeight,
                        scrollWidth: document.documentElement.scrollWidth,
                        search: rect(search),
                        greeting: rect(greeting),
                        caption: rect(caption),
                        visible: {
                            greeting: visible(greeting),
                            caption: visible(caption),
                            mood: visible(mood),
                            info: visible(info),
                        },
                        activePane: document.querySelector('.create-pane.active')?.id,
                        viewActive: view.classList.contains('active'),
                    };
                }"""
            )

        metrics = collect_metrics()
        assert metrics["viewActive"], "Create view is not active"
        assert metrics["activePane"] == "chat", "Chat mode should open the chat pane"
        assert metrics["visible"]["greeting"], "Create greeting is not visible"
        assert metrics["visible"]["caption"], "Wallpaper caption is not visible"
        assert metrics["visible"]["mood"], "Weather/mood pill is not visible"
        assert metrics["visible"]["info"], "Wallpaper info control is not visible"
        assert metrics["scrollWidth"] <= metrics["viewportWidth"] + 2, "Create layout has horizontal overflow"
        assert metrics["search"]["width"] <= metrics["viewportWidth"] - 20, "Create search exceeds viewport width"
        search_center = (metrics["search"]["left"] + metrics["search"]["right"]) / 2
        viewport_center = metrics["viewportWidth"] / 2
        assert abs(search_center - viewport_center) <= max(24, metrics["viewportWidth"] * 0.08), "Create search is not centered"
        assert metrics["greeting"]["bottom"] <= metrics["search"]["top"] + 4, "Greeting overlaps the search box"
        assert metrics["caption"]["bottom"] <= metrics["viewportHeight"] + 2, "Caption renders below viewport"
        page.get_by_role("button", name="Image", exact=True).click()
        page.wait_for_selector("#images.active")
        image_metrics = collect_metrics()
        assert image_metrics["activePane"] == "images", "Image mode should open the image pane"
        assert image_metrics["search"]["width"] <= image_metrics["viewportWidth"] - 20, "Image prompt exceeds viewport width"
        image_center = (image_metrics["search"]["left"] + image_metrics["search"]["right"]) / 2
        assert abs(image_center - image_metrics["viewportWidth"] / 2) <= max(24, image_metrics["viewportWidth"] * 0.08), "Image prompt is not centered"
        assert page.locator("#create-image-model").is_visible(), "Image model selector is not visible in Image mode"
        assert page.locator("#generate").is_visible(), "Image generation controls are not visible"
        page.get_by_role("button", name="Chat", exact=True).click()
        page.wait_for_selector("#chat.active")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_selector("#claude.active")
        assert_create_layout(page, 1280, 900)
        assert_create_layout(page, 390, 844)
        page.get_by_label("Open Console").click()
        page.wait_for_selector("#console.active")
        page.get_by_role("button", name="LLM Management").click()
        page.wait_for_selector("#models-editor")
        page.get_by_role("button", name="Coding").click()
        page.wait_for_selector("#claude.active")
        header = page.locator("header").inner_text(timeout=5000)
        assert "MDE LLM-PROXY Console" in header
        page.goto(terminal_smoke_url(base_url), wait_until="domcontentloaded")
        page.wait_for_selector("#terminal")
        assert "MDE LLM-PROXY Console" in page.title()
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--required", action="store_true", help="fail instead of skipping when Playwright is unavailable")
    parser.add_argument("--quiet", action="store_true", help="suppress expected access logs from the isolated smoke server")
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
        server, url = start_server(studio, quiet=args.quiet)
        try:
            run_browser_smoke(url)
            print("Browser smoke passed: %s" % url)
        finally:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
