#!/usr/bin/env python3
"""Headless browser smoke tests for the FastAPI/React v2 console."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
FRONTEND_LOCK = FRONTEND_DIR / "package-lock.json"
TS_BUILD_INFO = FRONTEND_DIR / "tsconfig.tsbuildinfo"
SIMPLE_ICONS_HOST = "cdn.simpleicons.org"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def frontend_install_command() -> list[str]:
    if FRONTEND_LOCK.exists():
        return ["npm", "ci", "--no-audit"]
    return ["npm", "install", "--no-audit"]


def ensure_frontend() -> tuple[bool, bool, bool]:
    had_node_modules = (FRONTEND_DIR / "node_modules").exists()
    had_dist = FRONTEND_DIST.exists()
    had_tsbuildinfo = TS_BUILD_INFO.exists()
    if not command_available("npm"):
        raise RuntimeError("npm is required to build the React frontend")
    if not had_node_modules:
        subprocess.run(frontend_install_command(), cwd=str(FRONTEND_DIR), check=True)
    if not FRONTEND_DIST.exists():
        subprocess.run(["npm", "run", "build"], cwd=str(FRONTEND_DIR), check=True)
    return had_node_modules, had_dist, had_tsbuildinfo


def cleanup_frontend(had_node_modules: bool, had_dist: bool, had_tsbuildinfo: bool) -> None:
    if not had_dist and FRONTEND_DIST.exists():
        shutil.rmtree(FRONTEND_DIST)
    if not had_node_modules and (FRONTEND_DIR / "node_modules").exists():
        shutil.rmtree(FRONTEND_DIR / "node_modules")
    if not had_tsbuildinfo and TS_BUILD_INFO.exists():
        TS_BUILD_INFO.unlink()


def wait_for_health(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(base_url + "v2/health", timeout=1.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError("v2 console did not become healthy: %s" % last_error)


def run_health_validate(base_url: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "health-validate.py"),
            "--v2-only",
            "--v2-url",
            base_url.rstrip("/"),
        ],
        cwd=str(ROOT),
        check=True,
    )


def assert_static_brand_assets(base_url: str) -> None:
    with urlopen(base_url.rstrip("/") + "/brand/mde-app-icon.png", timeout=5) as response:
        icon = response.read()
        assert response.status == 200, "MDE app icon did not return 200"
        assert response.headers.get("content-type", "").startswith("image/png"), "MDE app icon was not served as image/png"
        assert icon.startswith(b"\x89PNG\r\n\x1a\n"), "MDE app icon did not contain PNG bytes"
        assert len(icon) > 1000, "MDE app icon response was unexpectedly small"
    with urlopen(base_url.rstrip("/") + "/manifest.webmanifest", timeout=5) as response:
        manifest = json.loads(response.read().decode("utf-8"))
        assert response.status == 200, "web manifest did not return 200"
        assert manifest.get("name") == "MDE LLM-PROXY", "web manifest did not expose the canonical brand name"
        assert manifest.get("short_name") == "MDE", "web manifest did not expose the product short name"
        icons = manifest.get("icons") if isinstance(manifest.get("icons"), list) else []
        assert any(icon.get("src") == "/brand/mde-app-icon.png" for icon in icons if isinstance(icon, dict)), "web manifest did not reference the MDE app icon"


def start_server(port: int, run_db: Path) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    runtime_dir = run_db.parent
    access_state_file = runtime_dir / "model-access-state.json"
    if not access_state_file.exists():
        try:
            registry = json.loads((ROOT / "config" / "models.json").read_text(encoding="utf-8"))
            access_state_file.write_text(json.dumps({
                "schema_version": 1,
                "updated_at": time.time(),
                "models": {
                    str(model["id"]): {"access_status": "ok", "last_checked_at": time.time(), "source": "v2_browser_smoke"}
                    for model in registry.get("models", [])
                    if isinstance(model, dict)
                    and model.get("id")
                    and model.get("enabled") is not False
                    and model.get("serverless")
                    and model.get("type", "text") == "text"
                },
            }), encoding="utf-8")
        except Exception:
            pass
    env.update(
        {
            "MATTS_CONSOLE_AUTH_ENABLED": "0",
            "MATTS_V2_RUN_DB": str(run_db),
            "MATTS_V2_RAG_PROJECT_DIR": str(runtime_dir),
            "MATTS_V2_RAG_CONFIG_FILE": str(runtime_dir / "rag-config.json"),
            "MATTS_V2_RAG_INDEX_FILE": str(runtime_dir / "rag-index.json"),
            "MATTS_MODEL_CONFIG_FILE": str(ROOT / "config" / "models.json"),
            "MATTS_MODEL_ACCESS_STATE_FILE": str(access_state_file),
            "MATTS_MODEL_ACCESS_DRIFT_FILE": str(runtime_dir / "model-access-drift.json"),
            "MATTS_TRACE_FILE": str(runtime_dir / "traces.jsonl"),
            "MATTS_AUDIT_FILE": str(runtime_dir / "audit.jsonl"),
            "MATTS_REVIEW_QUEUE_FILE": str(runtime_dir / "reviews.jsonl"),
            "MATTS_REPLAY_FILE": str(runtime_dir / "replays.jsonl"),
            "MATTS_EVALS_DIR": str(runtime_dir / "evals"),
            "MATTS_EVAL_RUNS_DIR": str(runtime_dir / "eval-runs"),
            "MATTS_AUTOMATION_RULES_FILE": str(runtime_dir / "automation-rules.json"),
            "MATTS_AUTOMATION_EXECUTION_LOG_FILE": str(runtime_dir / "automation-executions.jsonl"),
            "MATTS_ROLLBACK_BACKUP_DIR": str(runtime_dir / "rollback-backups"),
            "MATTS_REPORTING_EXPORT_DIR": str(runtime_dir / "reporting"),
            "MATTS_RELEASE_CANDIDATE_REPORTS_DIR": str(runtime_dir / "release-candidates"),
            "MATTS_WORKSPACE_BUNDLES_DIR": str(runtime_dir / "workspace-bundles"),
            "MATTS_V2_RESEARCH_DB": str(runtime_dir / "research.sqlite3"),
            "MATTS_RESEARCH_LLM_ENABLED": "0",
            "MATTS_RESEARCH_IMAGE_TIMEOUT": "1",
            "MATTS_RESEARCH_MAP_TIMEOUT": "1",
            "MATTS_RESEARCH_WIKI_TIMEOUT": "1",
        }
    )
    return subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "matts-v2-console.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=5)
    except ProcessLookupError:
        pass


def assert_no_broken_model_artwork(page, label: str) -> None:
    page.wait_for_function("document.querySelectorAll('.modelLogo').length > 0", timeout=5000)
    logo_count = page.locator(".modelLogo").count()
    assert logo_count > 0, "%s did not render model identity marks" % label
    local_brand_count = page.locator('.modelLogo[data-artwork-state^="local-brand"]').count()
    assert local_brand_count > 0, "%s did not render any local model brand marks" % label
    # Brand SVG art arrives via a lazy same-origin chunk; wait for the upgrade from text marks.
    page.wait_for_function(
        "document.querySelectorAll('.modelLogo[data-artwork-state=\"local-brand-svg\"]').length > 0",
        timeout=5000,
    )
    bundled_svg_count = page.locator('.modelLogo[data-artwork-state="local-brand-svg"]').count()
    assert bundled_svg_count > 0, "%s did not render any bundled SVG model artwork" % label
    fallback_count = page.locator('.modelLogo[data-artwork-state$="initials"]').count()
    assert local_brand_count + fallback_count > 0, "%s did not render any intentional model artwork marks" % label
    deadline = time.time() + 5
    broken_sources = []
    while time.time() < deadline:
        broken_sources = page.locator(".modelLogo img").evaluate_all(
            """
            (imgs) => imgs
              .filter((img) => img.complete && img.naturalWidth === 0)
              .map((img) => img.currentSrc || img.getAttribute('src') || 'unknown')
            """
        )
        if not broken_sources:
            break
        page.wait_for_timeout(100)
    assert broken_sources == [], "%s rendered broken model artwork: %s" % (label, broken_sources)


def assert_loaded_image(locator, label: str) -> None:
    from playwright.sync_api import expect

    expect(locator).to_be_visible()
    loaded = locator.evaluate(
        """
        (img) => img.complete && img.naturalWidth > 0 && img.naturalHeight > 0
        """
    )
    assert loaded, "%s did not load image pixels" % label


def install_model_artwork_guard(page) -> dict[str, list[str]]:
    events: dict[str, list[str]] = {"requests": [], "failures": [], "console": []}

    def record_request(request) -> None:
        if SIMPLE_ICONS_HOST in request.url:
            events["requests"].append(request.url)

    def record_failed_request(request) -> None:
        if SIMPLE_ICONS_HOST in request.url:
            events["failures"].append(request.url)

    def record_console(message) -> None:
        text = message.text
        if message.type == "error" and (SIMPLE_ICONS_HOST in text or "ERR_BLOCKED_BY_RESPONSE" in text or "NotSameOrigin" in text):
            events["console"].append(text)

    def block_simple_icons(route) -> None:
        events["requests"].append(route.request.url)
        route.abort()

    page.on("request", record_request)
    page.on("requestfailed", record_failed_request)
    page.on("console", record_console)
    page.route("https://cdn.simpleicons.org/**", block_simple_icons)
    return events


def assert_no_model_artwork_guard_events(events: dict[str, list[str]], label: str) -> None:
    observed = {kind: sorted(set(values)) for kind, values in events.items() if values}
    assert observed == {}, "%s emitted blocked model artwork events: %s" % (label, observed)


def assert_no_document_horizontal_overflow(page, label: str) -> None:
    page.wait_for_function(
        """
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2
        """,
        timeout=5000,
    )
    dimensions = page.evaluate(
        """
        () => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth
        })
        """
    )
    assert dimensions["scrollWidth"] <= dimensions["clientWidth"] + 2, "%s overflowed horizontally: %s" % (label, dimensions)


def assert_create_atmosphere_contained(page, label: str) -> None:
    page.wait_for_function("document.querySelectorAll('.createAtmosphere span').length === 3", timeout=5000)
    boxes = page.locator(".createAtmosphere span").evaluate_all(
        """
        (nodes) => nodes.map((node) => {
          const rect = node.getBoundingClientRect();
          return {
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
            viewport: window.innerWidth
          };
        })
        """
    )
    escaped = [box for box in boxes if box["left"] < -2 or box["right"] > box["viewport"] + 2]
    assert escaped == [], "%s Create atmosphere escaped the viewport: %s" % (label, escaped)


def cost_control_smoke_payload(status: str = "ready") -> dict[str, object]:
    paused = status == "paused"
    return {
        "schema_version": 1,
        "checked_at": 1,
        "status": status,
        "costs": {
            "minute_total_usd": 0.01,
            "daily_total_usd": 2.5,
            "monthly_total_usd": 42.0,
            "categories": {
                "dedicated_instances": {"minute_usd": 0.0, "daily_usd": 1.0, "monthly_usd": 12.0},
                "llm_service": {"minute_usd": 0.01, "daily_usd": 1.5, "monthly_usd": 30.0},
            },
            "sources": {"minute": "local_estimate", "daily": "local_estimate", "monthly": "local_estimate"},
        },
        "threshold": {
            "monthly_threshold_usd": 100.0,
            "warning_at_usd": 80.0,
            "hard_at_usd": 105.0,
            "percent": 42.0,
            "warning": False,
            "hard": paused,
        },
        "pause": {"active": paused, "reason": "smoke_pause" if paused else "", "override": {"active": False}},
        "thresholds": {},
        "provider": {"monthly_source": "local_estimate", "fallback_estimates_active": True},
        "payment_review": {
            "items": [
                {"id": "provider_billing_api", "label": "Provider billing API", "status": "open", "detail": "Smoke provider billing check."},
                {"id": "payment_method", "label": "Payment method", "status": "complete", "detail": "Smoke payment method check."},
            ]
        },
    }


def run_mobile_whats_new_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        artwork_events = install_model_artwork_guard(page)
        page.goto(base_url, wait_until="networkidle")
        expect(page.get_by_role("heading", name="What's New")).to_be_visible()
        modal = page.locator(".whatsNewModal")
        expect(modal).to_be_visible()
        box = modal.bounding_box()
        viewport = page.viewport_size or {"height": 844}
        assert box is not None, "mobile Whats New modal did not produce a layout box"
        assert box["y"] >= 0 and box["height"] <= viewport["height"] - 20, "mobile Whats New modal does not fit the viewport"
        expect(page.get_by_role("button", name="Close What's New")).to_be_visible()
        digitalocean_shortcut = page.get_by_role("button", name=re.compile("DigitalOcean"))
        expect(digitalocean_shortcut).to_be_visible()
        digitalocean_shortcut.click()
        page.wait_for_function(
            """
            () => {
              const body = document.querySelector('.whatsNewSections');
              const link = [...document.querySelectorAll('.whatsNewModal a')]
                .find((node) => node.textContent && node.textContent.includes('Available Inference Models'));
              if (!body || !link) return false;
              const bodyBox = body.getBoundingClientRect();
              const linkBox = link.getBoundingClientRect();
              return linkBox.top >= bodyBox.top && linkBox.bottom <= bodyBox.bottom;
            }
            """,
            timeout=5000,
        )
        expect(page.get_by_role("link", name="Available Inference Models")).to_be_visible()
        expect(page.get_by_role("button", name="Close What's New")).to_be_visible()
        page.get_by_role("button", name="Close What's New").click()
        expect(page.locator(".whatsNewModal")).to_have_count(0)
        assert_no_model_artwork_guard_events(artwork_events, "mobile Whats New")
    finally:
        context.close()


def dismiss_whats_new_if_present(page, timeout: int = 5000) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import expect

    modal = page.locator(".whatsNewModal")
    try:
        modal.wait_for(state="visible", timeout=timeout)
    except PlaywrightTimeoutError:
        return
    page.get_by_role("button", name="Close What's New").click()
    expect(modal).to_have_count(0)


def open_shell_drawer(page):
    from playwright.sync_api import expect

    page.get_by_test_id("shell-menu-toggle").click()
    drawer = page.get_by_test_id("shell-navigation-drawer")
    expect(drawer).to_be_visible()
    expect(page.get_by_test_id("shell-menu-toggle")).to_have_attribute("aria-expanded", "true")
    return drawer


def navigate_shell(page, key: str) -> None:
    from playwright.sync_api import expect

    open_shell_drawer(page).get_by_test_id(f"shell-nav-{key}").click()
    expect(page.get_by_test_id("shell-navigation-drawer")).not_to_be_visible()


def open_advanced_workspace(page) -> None:
    """Advanced left the drawer nav; the Settings utility button is the entry point."""
    from playwright.sync_api import expect

    open_shell_drawer(page).get_by_test_id("shell-drawer-settings").click()
    expect(page.get_by_test_id("shell-navigation-drawer")).not_to_be_visible()
    expect(page.get_by_role("heading", name="Advanced")).to_be_visible()


def open_advanced_tab(page, tab: str) -> None:
    from playwright.sync_api import expect

    # Advanced tabs are workflow-grouped with humanized labels ("Models", "Run",
    # …); match the key case-insensitively so callers keep passing lowercase keys.
    name = re.compile(rf"^{re.escape(tab)}$", re.IGNORECASE)
    open_advanced_workspace(page)
    page.locator(".advancedTabs").get_by_role("button", name=name).click()
    expect(page.locator(".advancedTabs").get_by_role("button", name=name)).to_have_class(re.compile("active"))


def run_mobile_create_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(base_url + "#create", wait_until="domcontentloaded", timeout=60000)
        dismiss_whats_new_if_present(page)
        expect(page.get_by_role("heading", name="Create")).to_be_visible()
        expect(page.locator(".createAtmosphere")).to_be_visible()
        assert_no_document_horizontal_overflow(page, "mobile Create")
        assert_create_atmosphere_contained(page, "mobile Create")
    finally:
        context.close()


def run_mobile_advanced_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(base_url + "#advanced", wait_until="domcontentloaded", timeout=60000)
        dismiss_whats_new_if_present(page)
        expect(page.get_by_role("heading", name="Advanced")).to_be_visible()
        # Models is the Advanced landing (Overview folded in); the readiness pulse lives here.
        expect(page.get_by_role("heading", name="Models", exact=True)).to_be_visible()
        expect(page.get_by_test_id("advanced-readiness-pulse")).to_be_visible()
        for label in ("Models", "Console", "Run", "Observe", "Operate"):
            expect(page.locator(".advancedTabs").get_by_role("button", name=label, exact=True)).to_be_visible()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Models", exact=True)).to_have_class(re.compile("active"))
        # Console is now a lean System Operations dashboard; terminal/tmux live in Code (ADR-0002).
        page.locator(".advancedTabs").get_by_role("button", name="Console", exact=True).click()
        expect(page.locator(".consoleHeader")).to_be_visible(timeout=45000)
        expect(page.get_by_test_id("console-command-table")).to_be_visible()
        expect(page.get_by_test_id("console-operational-state")).to_be_visible()
        assert_no_document_horizontal_overflow(page, "mobile Advanced console")
        # The terminal/tmux workflow lives in Code, where it is covered here.
        navigate_shell(page, "code")
        expect(page.get_by_role("heading", name="Code")).to_be_visible()
        expect(page.get_by_test_id("code-tui-section")).to_be_visible()
        page.get_by_test_id("code-tui-toggle").click()
        expect(page.get_by_test_id("tui-terminal")).to_be_visible()
        assert_no_document_horizontal_overflow(page, "mobile Code TUI")
    finally:
        context.close()


def run_advanced_loading_skeleton_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    page = browser.new_page(viewport={"width": 1280, "height": 820})
    page.add_init_script(
        """
        window.sessionStorage.setItem('matts-v2-whats-new-dismissed', '1');
        window.sessionStorage.setItem('matts-v2-advanced-tab', 'console');
        window.sessionStorage.setItem('matts-v2-advanced-lazy-delay-ms', '900');
        """
    )
    try:
        page.goto(base_url + "#advanced", wait_until="domcontentloaded")
        skeleton = page.get_by_test_id("advanced-loading-skeleton")
        expect(skeleton).to_be_visible()
        expect(skeleton).to_contain_text("workspace loading")
        page.wait_for_function(
            """
            () => {
              const skeleton = document.querySelector('[data-testid="advanced-loading-skeleton"]');
              return skeleton && skeleton.scrollWidth <= skeleton.clientWidth + 2;
            }
            """,
            timeout=5000,
        )
        expect(page.get_by_test_id("console-operational-state")).to_be_visible(timeout=8000)
        expect(page.get_by_test_id("advanced-loading-skeleton")).to_have_count(0)
        assert_no_document_horizontal_overflow(page, "Advanced lazy-loading skeleton")
    finally:
        page.close()


def run_shell_error_boundary_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    page = browser.new_page(viewport={"width": 1280, "height": 820})
    page.add_init_script("window.sessionStorage.setItem('matts-v2-fatal-error-diagnostic', '1');")
    try:
        page.goto(base_url, wait_until="networkidle")
        expect(page.get_by_test_id("v2-fatal-error-boundary")).to_be_visible()
        expect(page.get_by_role("heading", name="V2 recovered from a render failure")).to_be_visible()
        expect(page.get_by_text("V2 shell diagnostic render failure")).to_be_visible()
        assert_no_document_horizontal_overflow(page, "fatal shell fallback")
        page.get_by_role("button", name="Reset Workspace").click()
        expect(page.get_by_test_id("v2-fatal-error-boundary")).to_have_count(0)
        dismiss_whats_new_if_present(page)
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        assert page.evaluate("window.sessionStorage.getItem('matts-v2-fatal-error-diagnostic')") is None
        assert_no_document_horizontal_overflow(page, "fatal shell recovery")
    finally:
        page.close()


def run_dark_mode_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    context = browser.new_context(viewport={"width": 1280, "height": 820}, color_scheme="light")
    page = context.new_page()
    try:
        page.goto(base_url + "#chat", wait_until="domcontentloaded", timeout=60000)
        dismiss_whats_new_if_present(page)
        toggle = page.get_by_test_id("shell-theme-toggle")
        expect(toggle).to_be_visible()
        page.wait_for_function("() => document.documentElement.dataset.theme === 'light'")
        toggle.click()
        page.wait_for_function("() => document.documentElement.dataset.theme === 'dark'")
        expect(toggle).to_have_attribute("aria-pressed", "true")
        page.wait_for_function(
            """
            () => {
              const rgb = getComputedStyle(document.body).backgroundColor.match(/\\d+/g);
              if (!rgb) return false;
              const [r, g, b] = rgb.map(Number);
              return r < 64 && g < 64 && b < 64;
            }
            """
        )
        open_advanced_tab(page, "models")
        expect(page.get_by_role("heading", name="Models")).to_be_visible()
        page.wait_for_function("() => document.documentElement.dataset.theme === 'dark'")
        assert_no_document_horizontal_overflow(page, "dark Models")
        page.reload(wait_until="domcontentloaded")
        dismiss_whats_new_if_present(page)
        page.wait_for_function("() => document.documentElement.dataset.theme === 'dark'")
        navigate_shell(page, "chat")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        page.get_by_role("button", name="Light", exact=True).click()
        page.wait_for_function("() => document.documentElement.dataset.theme === 'light'")
        expect(page.get_by_test_id("shell-theme-toggle")).to_have_attribute("aria-pressed", "false")
    finally:
        context.close()

    context = browser.new_context(viewport={"width": 1280, "height": 820}, color_scheme="dark")
    page = context.new_page()
    try:
        page.goto(base_url + "#chat", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function("() => document.documentElement.dataset.theme === 'dark'")
    finally:
        context.close()


CHAT_LAYOUT_TRANSCRIPT = [
    {"role": "user", "content": "Give me a two-line status summary of the proxy and the single next action."},
    {
        "role": "assistant",
        "content": (
            "The proxy is healthy on 127.0.0.1:18081 and every routable model answered the last smoke run. "
            "Next action: clear the two rate-limited Serverless endpoints before the release cut, then re-run the model audit."
        ),
        "model": "DeepSeek V3.2",
        "company": "DeepSeek",
        "delivery": "delivered",
    },
]

_CHAT_LAYOUT_MEASURE = """
() => {
  const rows = [...document.querySelectorAll('.icqTranscriptPane .messageRow.assistant')];
  return rows.map(row => {
    const card = row.querySelector('.messageModelCard');
    const body = row.querySelector('.messageBody');
    const cardBox = card.getBoundingClientRect();
    const bodyBox = body.getBoundingClientRect();
    const spills = [...card.querySelectorAll('.mdlCardFacts span')]
      .map(s => s.getBoundingClientRect().right - cardBox.right);
    return {
      cardRight: cardBox.right, bodyLeft: bodyBox.left,
      cardBottom: cardBox.bottom, bodyTop: bodyBox.top,
      chipSpill: Math.max(0, ...spills, 0),
    };
  });
}
"""


def _seed_chat_transcript(page, transcript, theme: str = "dark") -> None:
    page.add_init_script(
        "window.localStorage.setItem('matts-v2-theme', %s);"
        "window.sessionStorage.setItem('matts-v2-whats-new-dismissed', '1');"
        "window.sessionStorage.setItem('matts-v2-chat-transcript', %s);"
        % (json.dumps(theme), json.dumps(json.dumps(transcript)))
    )


def run_chat_model_card_layout_smoke(browser, base_url: str) -> None:
    """A per-message model card must never overflow onto the message body, and
    a fact chip (e.g. the long cost label) must never spill past the card edge.
    Regression guard for the 220px chat card that once overlapped the text and
    whose nowrap cost chip once bled onto adjacent content."""
    # Desktop: card sits in a left rail; its right edge must clear the body.
    context = browser.new_context(viewport={"width": 1280, "height": 860}, color_scheme="dark")
    page = context.new_page()
    _seed_chat_transcript(page, CHAT_LAYOUT_TRANSCRIPT)
    try:
        page.goto(base_url + "#chat", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".messageModelCard", timeout=15000)
        page.wait_for_timeout(400)
        rows = page.evaluate(_CHAT_LAYOUT_MEASURE)
        assert rows, "expected at least one assistant message row (desktop)"
        for i, r in enumerate(rows):
            assert r["cardRight"] <= r["bodyLeft"] + 1, (
                "desktop: model card (right=%s) overlaps message body (left=%s) in row %d"
                % (r["cardRight"], r["bodyLeft"], i)
            )
            assert r["chipSpill"] <= 1, (
                "desktop: a card fact chip spills %.1fpx past the card edge in row %d" % (r["chipSpill"], i)
            )
    finally:
        context.close()

    # Narrow: the card stacks above the body (single column); no chip spill.
    context = browser.new_context(viewport={"width": 560, "height": 860}, color_scheme="dark")
    page = context.new_page()
    _seed_chat_transcript(page, CHAT_LAYOUT_TRANSCRIPT)
    try:
        page.goto(base_url + "#chat", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".messageModelCard", timeout=15000)
        page.wait_for_timeout(400)
        rows = page.evaluate(_CHAT_LAYOUT_MEASURE)
        assert rows, "expected at least one assistant message row (narrow)"
        for i, r in enumerate(rows):
            assert r["cardBottom"] <= r["bodyTop"] + 2, (
                "narrow: model card should stack above the body (cardBottom=%s, bodyTop=%s) in row %d"
                % (r["cardBottom"], r["bodyTop"], i)
            )
            assert r["chipSpill"] <= 1, (
                "narrow: a card fact chip spills %.1fpx past the card edge in row %d" % (r["chipSpill"], i)
            )
    finally:
        context.close()


def run_boot_fallback_no_js_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 820})
    page = context.new_page()
    try:
        page.goto(base_url, wait_until="domcontentloaded")
        fallback = page.get_by_test_id("v2-boot-fallback")
        expect(fallback).to_be_visible()
        expect(page.get_by_role("heading", name="MDE LLM-PROXY is starting")).to_be_visible()
        assert_loaded_image(page.get_by_test_id("boot-brand-icon"), "boot fallback MDE app icon")
        expect(page.get_by_role("link", name="V2 Health")).to_have_attribute("href", "/v2/health")
        box = fallback.bounding_box()
        assert box, "boot fallback did not expose a visible bounding box"
        viewport = page.viewport_size or {"width": 390}
        assert box["x"] >= 0 and box["width"] <= viewport["width"] + 2, "boot fallback overflowed horizontally: %s in %s" % (box, viewport)
    finally:
        context.close()


def run_readiness_advisory_label_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    page = browser.new_page(viewport={"width": 1280, "height": 820})
    page.add_init_script(
        """
        Object.defineProperty(navigator, 'clipboard', {
          value: {
            writeText: async (text) => { window.__mattsSmokeClipboard = text; },
            readText: async () => window.__mattsSmokeClipboard || ''
          },
          configurable: true
        });
        """
    )
    try:
        page.route(
            "**/v2/operate/config-drift/acknowledge",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "summary": {"state": "acknowledged"},
                    "acknowledged": ["tmux_registry"],
                    "actor": {"id": "v2-browser-smoke"},
                }),
            ),
        )
        page.route(
            "**/v2/operate/config-drift/baseline",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "summary": {"state": "clean"},
                    "baseline_file": "/tmp/v2-browser-smoke-baseline.json",
                    "actor": {"id": "v2-browser-smoke"},
                }),
            ),
        )
        page.route(
            "**/v2/operate*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "generated_at": 1,
                    "release_candidate": {
                        "ready": True,
                        "summary": {"checks": 9, "blocking_failed": 0, "advisory_failed": 1, "passed": 8},
                        "operator_handoff": {"open_count": 0, "items": [], "summary": "No operator-owned release items are open."},
                        "checks": [
                            {
                                "id": "config_drift",
                                "title": "Config drift",
                                "status": "failed",
                                "severity": "advisory",
                                "blocking": False,
                                "evidence": {"active_drift_count": 1, "blocking_drift_count": 0, "advisory_drift_count": 1},
                            }
                        ],
                    },
                    "summary": {},
                    "eval_gates": {},
                    "reviews": {},
                    "rollback": {},
                    "config_drift": {
                        "summary": {"state": "drift", "baseline_present": True, "active_drift_count": 1, "highest_risk": "low"},
                        "items": [{"name": "console_config", "label": "Console config", "risk": "high", "path": "config/console.json"}],
                        "drift": [{
                            "name": "tmux_registry",
                            "label": "tmux session registry",
                            "risk": "low",
                            "status": "changed",
                            "path": "/tmp/tmux-sessions.json",
                            "acknowledged": False,
                            "rollback": {
                                "backup_item": "tmux_registry",
                                "restore_command": "python3 scripts/runtime-state.py restore <archive>",
                                "note": "Inspect the archive manifest before restoring.",
                            },
                            "current": {"sha256_short": "current-smoke-sha", "type": "file", "size": 3502, "json_valid": True, "rollback": {"note": "Inspect the archive manifest before restoring."}},
                            "baseline": {"sha256_short": "baseline-smoke-sha", "type": "file", "size": 3400, "json_valid": True, "rollback": {"note": "Inspect the archive manifest before restoring."}},
                        }],
                    },
                    "automation": {},
                    "quotas": {},
                    "synthetic_load": {},
                    "ci_triage": {},
                    "offline_mode": {},
                    "model_deprecations": {},
                    "cost_control": cost_control_smoke_payload(),
                }),
            ),
        )
        page.goto(base_url + "#advanced", wait_until="networkidle")
        dismiss_whats_new_if_present(page)
        pulse = page.get_by_test_id("advanced-readiness-pulse")
        expect(pulse).to_be_visible()
        expect(pulse).to_contain_text("Ready With Advisories")
        expect(pulse).to_contain_text("Config drift")
        expect(pulse).to_contain_text("1 low-risk drift item")
        expect(pulse).not_to_contain_text("Ready With Handoff")
        pulse.click()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Operate", exact=True)).to_have_class(re.compile("active"))
        expect(page.get_by_test_id("operate-config-drift-summary")).to_contain_text("1 active config drift item")
        expect(page.get_by_test_id("operate-config-drift-summary")).to_contain_text("Highest risk: low")
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("tmux session registry")
        # Forensic drift detail is now behind an expandable row (compact table + Descriptions).
        page.get_by_test_id("operate-rollback").locator(".ant-table-row-expand-icon").first.click()
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("Inspect the archive manifest")
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("current-smoke-sha")
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("baseline-smoke-sha")
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("file / 3502")
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("file / 3400")
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("JSON yes")
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("Restore available")
        expect(page.get_by_test_id("operate-rollback").get_by_role("button", name="Copy Evidence")).to_be_visible()
        page.get_by_test_id("operate-rollback").get_by_role("button", name="Copy Evidence").click()
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("Evidence copied")
        copied_drift_row = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert copied_drift_row.startswith("### 1. tmux session registry")
        assert "Current fingerprint: current-smoke-sha" in copied_drift_row
        assert "Baseline fingerprint: baseline-smoke-sha" in copied_drift_row
        assert "Backup item: tmux_registry" in copied_drift_row
        assert "Restore available: yes" in copied_drift_row
        assert "Inspect the archive manifest" in copied_drift_row
        assert "# Config Drift Evidence Brief" not in copied_drift_row
        expect(page.get_by_test_id("operate-rollback")).not_to_contain_text("Console config")
        expect(page.get_by_test_id("operate-config-drift-brief")).to_contain_text("Drift Brief Ready")
        page.get_by_test_id("operate-config-drift-brief").get_by_role("button", name="Copy Drift Brief").click()
        expect(page.get_by_test_id("operate-config-drift-brief")).to_contain_text("Drift brief copied")
        copied_drift = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# Config Drift Evidence Brief" in copied_drift
        assert "current-smoke-sha" in copied_drift
        assert "baseline-smoke-sha" in copied_drift
        assert "Inspect the archive manifest" in copied_drift
        with page.expect_download() as drift_download:
            page.get_by_test_id("operate-config-drift-brief").get_by_role("button", name="Download Drift Brief").click()
        assert drift_download.value.suggested_filename.startswith("mde-llm-proxy-config-drift-brief-")
        assert drift_download.value.suggested_filename.endswith(".md")
        expect(page.get_by_test_id("operate-config-drift-actions")).to_contain_text("config_drift_admin")
        expect(page.get_by_test_id("operate-config-drift-acknowledge")).to_be_enabled()
        expect(page.get_by_test_id("operate-config-drift-baseline")).to_be_enabled()
        page.get_by_test_id("operate-config-drift-acknowledge").click()
        expect(page.get_by_test_id("operate-config-drift-action-result")).to_contain_text("Config drift acknowledged")
        assert_no_document_horizontal_overflow(page, "readiness advisory label")
    finally:
        page.close()


def run_readiness_handoff_top_action_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    page = browser.new_page(viewport={"width": 1280, "height": 820})
    try:
        page.route(
            "**/v2/operate*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "generated_at": 1,
                    "release_candidate": {
                        "ready": True,
                        "summary": {"checks": 10, "blocking_failed": 0, "advisory_failed": 1, "passed": 9},
                        "operator_handoff": {
                            "open_count": 1,
                            "summary": "1 operator-owned release item remains before public release review.",
                            "items": [{
                                "item": "Dedicated Inference live capacity verification",
                                "owner": "Cloud operator",
                                "gate_type": "live-cloud",
                                "priority_rank": 1,
                                "urgency": "highest",
                                "blocking_rationale": "Cloud capacity determines whether the selected LLM route can be offered publicly in the target region.",
                                "next_action": "Check DigitalOcean model and GPU capacity in the target region.",
                                "evidence_required": "Region, GPU/plan identifier, selected model, observed availability, timestamp, and fallback.",
                                "closure_template": "Status cell: Closed <YYYY-MM-DD>: <outcome>. Evidence: Region, GPU/plan identifier, selected model, observed availability, timestamp, and fallback. Owner: Cloud operator. Gate: live-cloud.",
                            }],
                        },
                        "checks": [{
                            "id": "needs_operator",
                            "title": "Operator-needed items",
                            "status": "failed",
                            "severity": "advisory",
                            "blocking": False,
                            "evidence": {"open_items": 1},
                        }],
                    },
                    "summary": {},
                    "eval_gates": {},
                    "reviews": {},
                    "rollback": {},
                    "config_drift": {"summary": {"state": "clean", "active_drift_count": 0}, "items": [], "drift": []},
                    "automation": {},
                    "quotas": {},
                    "synthetic_load": {},
                    "ci_triage": {},
                    "offline_mode": {},
                    "model_deprecations": {},
                    "cost_control": cost_control_smoke_payload(),
                }),
            ),
        )
        page.goto(base_url + "#advanced", wait_until="networkidle")
        dismiss_whats_new_if_present(page)
        pulse = page.get_by_test_id("advanced-readiness-pulse")
        expect(pulse).to_be_visible()
        expect(pulse).to_contain_text("Ready With Handoff")
        expect(pulse).to_contain_text("Next #1")
        expect(pulse).to_contain_text("Dedicated Inference live capacity verification")
        expect(page.get_by_test_id("advanced-readiness-reason").first).to_contain_text("#1 Operator Action")
        expect(page.get_by_test_id("advanced-readiness-reason").first).to_contain_text("Cloud operator")
        expect(pulse).not_to_contain_text("Operator-needed items")
    finally:
        page.close()


def run_high_risk_config_drift_guard_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    page = browser.new_page(viewport={"width": 1280, "height": 820})
    confirmed_actions: list[dict[str, object]] = []
    try:
        def high_risk_ack(route) -> None:
            payload = json.loads(route.request.post_data or "{}")
            confirmed_actions.append({
                "confirmed": payload.get("confirm_high_risk") is True,
                "confirmed_items": payload.get("confirmed_high_risk_items"),
            })
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"summary": {"state": "acknowledged"}, "acknowledged": payload.get("items") or [], "actor": {"id": "v2-browser-smoke"}}),
            )

        page.route("**/v2/operate/config-drift/acknowledge", high_risk_ack)
        page.route(
            "**/v2/operate/config-drift/baseline",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"summary": {"state": "clean"}, "baseline_file": "/tmp/v2-browser-smoke-baseline.json"}),
            ),
        )
        page.route(
            "**/v2/operate*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "generated_at": 1,
                    "release_candidate": {
                        "ready": False,
                        "summary": {"checks": 9, "blocking_failed": 1, "advisory_failed": 0, "passed": 8},
                        "operator_handoff": {"open_count": 0, "items": [], "summary": "No operator-owned release items are open."},
                        "checks": [{
                            "id": "config_drift",
                            "title": "Config drift",
                            "status": "failed",
                            "severity": "blocking",
                            "blocking": True,
                            "evidence": {"active_drift_count": 1, "blocking_drift_count": 1, "advisory_drift_count": 0},
                        }],
                    },
                    "summary": {},
                    "eval_gates": {},
                    "reviews": {},
                    "rollback": {},
                    "config_drift": {
                        "summary": {"state": "drift", "baseline_present": True, "active_drift_count": 1, "highest_risk": "high"},
                        "items": [],
                        "drift": [{
                            "name": "console_config",
                            "label": "Console config",
                            "risk": "high",
                            "status": "changed",
                            "path": "config/console.json",
                            "acknowledged": False,
                            "rollback": {"note": "Compare the current config to the marked baseline."},
                            "current": {"sha256_short": "current-high-risk-sha", "type": "file", "size": 3830, "json_valid": True},
                            "baseline": {"sha256_short": "baseline-high-risk-sha", "type": "file", "size": 3832, "json_valid": True},
                        }],
                    },
                    "automation": {},
                    "quotas": {},
                    "synthetic_load": {},
                    "ci_triage": {},
                    "offline_mode": {},
                    "model_deprecations": {},
                    "cost_control": cost_control_smoke_payload("paused"),
                }),
            ),
        )
        page.goto(base_url + "#advanced", wait_until="networkidle")
        dismiss_whats_new_if_present(page)
        page.get_by_test_id("advanced-readiness-pulse").click()
        expect(page.get_by_test_id("operate-config-drift-summary")).to_contain_text("Highest risk: high")
        page.get_by_test_id("operate-rollback").locator(".ant-table-row-expand-icon").first.click()
        expect(page.get_by_test_id("operate-rollback")).to_contain_text("Manual compare")
        expect(page.get_by_test_id("operate-config-drift-high-risk-warning")).to_contain_text("console_config")
        expect(page.get_by_test_id("operate-config-drift-actions")).to_contain_text("high risk locked")
        expect(page.get_by_test_id("operate-config-drift-acknowledge")).to_be_disabled()
        expect(page.get_by_test_id("operate-config-drift-baseline")).to_be_disabled()
        page.get_by_test_id("operate-config-drift-high-risk-confirm").click()
        expect(page.get_by_test_id("operate-config-drift-actions")).to_contain_text("high risk confirmed")
        expect(page.get_by_test_id("operate-config-drift-acknowledge")).to_be_enabled()
        expect(page.get_by_test_id("operate-config-drift-baseline")).to_be_enabled()
        page.get_by_test_id("operate-config-drift-acknowledge").click()
        expect(page.get_by_test_id("operate-config-drift-action-result")).to_contain_text("Config drift acknowledged")
        assert confirmed_actions == [{"confirmed": True, "confirmed_items": ["console_config"]}]
        assert_no_document_horizontal_overflow(page, "high-risk config drift guard")
    finally:
        page.close()


def run_hash_token_research_auth_smoke(browser, base_url: str) -> None:
    from playwright.sync_api import expect

    page = browser.new_page(viewport={"width": 1280, "height": 860})
    research_urls: list[str] = []
    research_tokens: list[str] = []

    def handle_research_setup(route) -> None:
        if route.request.method != "GET":
            route.continue_()
            return
        research_urls.append(route.request.url)
        research_tokens.append(route.request.headers.get("x-matts-console-token", ""))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "engines": [{"id": "bing", "name": "Bing", "status": "needs_key", "kind": "web"}],
                "source_classes": [],
                "modes": ["Balanced"],
                "model_strategy": {"roles": [], "coordinator": {}, "constraints": []},
            }),
        )

    try:
        page.route("**/v2/research**", handle_research_setup)
        page.goto(base_url + "#research?token=hash-smoke-token", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        expect(page.get_by_text("Research setup unavailable")).to_have_count(0)
        assert "token=hash-smoke-token" not in page.url, "bootstrap token was not scrubbed from the browser URL: %s" % page.url
        assert research_urls, "hash-token Research setup route was not exercised"
        assert all("token=hash-smoke-token" not in url for url in research_urls), "hash token leaked into /v2/research URL: %s" % research_urls
        assert "hash-smoke-token" in research_tokens, "hash token was not forwarded in x-matts-console-token: %s" % research_tokens
        assert page.evaluate("window.localStorage.getItem('matts-v2-console-token')") == "hash-smoke-token"
        page.goto(base_url + "?stored-token-check=1#research", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        assert len(research_urls) >= 2, "stored-token Research setup route was not exercised"
        assert "token=hash-smoke-token" not in page.url, "stored-token navigation reintroduced token in URL: %s" % page.url
        assert "token=hash-smoke-token" not in research_urls[-1], "stored token leaked into /v2/research URL: %s" % research_urls[-1]
        assert research_tokens[-1] == "hash-smoke-token", "stored token was not reused in x-matts-console-token: %s" % research_tokens[-1]
        page.evaluate("window.sessionStorage.removeItem('matts-v2-console-token')")
        page.goto(base_url + "#research", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        assert research_tokens[-1] == "hash-smoke-token", "local storage did not restore x-matts-console-token after session storage cleared: %s" % research_tokens[-1]
    finally:
        page.close()


def run_browser_smoke(base_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    assert_static_brand_assets(base_url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        run_boot_fallback_no_js_smoke(browser, base_url)
        run_shell_error_boundary_smoke(browser, base_url)
        run_dark_mode_smoke(browser, base_url)
        run_chat_model_card_layout_smoke(browser, base_url)
        run_readiness_advisory_label_smoke(browser, base_url)
        run_readiness_handoff_top_action_smoke(browser, base_url)
        run_high_risk_config_drift_guard_smoke(browser, base_url)
        run_advanced_loading_skeleton_smoke(browser, base_url)
        run_hash_token_research_auth_smoke(browser, base_url)
        page = browser.new_page(viewport={"width": 1440, "height": 950})
        page.add_init_script(
            """
            if (window.crypto) {
              Object.defineProperty(window.crypto, 'randomUUID', { value: undefined, configurable: true });
            }
            Object.defineProperty(navigator, 'clipboard', {
              value: {
                writeText: async (text) => { window.__mattsSmokeClipboard = text; },
                readText: async () => window.__mattsSmokeClipboard || ''
              },
              configurable: true
            });
            window.__mattsPrintCalled = false;
            window.print = () => { window.__mattsPrintCalled = true; };
            """
        )
        artwork_events = install_model_artwork_guard(page)
        generated_chat_errors: list[str] = []

        def handle_chat_route(route) -> None:
            if route.request.method != "POST":
                route.continue_()
                return
            post_data = route.request.post_data or ""
            latest_prompt = post_data
            try:
                payload = json.loads(post_data)
                messages = payload.get("messages", [])
                if messages:
                    latest_prompt = str(messages[-1].get("content", ""))
            except (json.JSONDecodeError, AttributeError, TypeError):
                latest_prompt = post_data
            if "detail-string-smoke" in latest_prompt:
                route.fulfill(
                    status=400,
                    content_type="application/json",
                    body=json.dumps({"detail": "Hero client detail string reached the UI"}),
                )
                return
            if "plain-text-smoke" in latest_prompt:
                route.fulfill(
                    status=502,
                    content_type="text/plain",
                    body="Hero client plain text error reached the UI",
                )
                return
            if "route-diagnostic-smoke" in latest_prompt:
                route.fulfill(
                    status=404,
                    content_type="application/json",
                    body=json.dumps({
                        "message": "api endpoint not found",
                        "code": "api_endpoint_not_found",
                        "details": {
                            "path": "/v2/chat",
                            "method": "GET",
                            "allowed_methods": ["POST"],
                            "suggested_fix": "Use POST /v2/chat; this endpoint exists but not for GET.",
                        },
                    }),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": 200, "response": {"text": "V2 smoke transcript response"}}),
            )

        def handle_generated_run_chat_route(route) -> None:
            if route.request.method != "POST":
                route.continue_()
                return
            post_data = route.request.post_data or ""
            if "generated-client-error-smoke" not in post_data:
                route.continue_()
                return
            generated_chat_errors.append(route.request.url)
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"detail": {"message": "Generated client detail reached browser smoke"}}),
            )

        page.route("**/v2/chat", handle_chat_route)
        page.route("**/v2/run/chat", handle_generated_run_chat_route)
        page.route(
            "**/v2/create/images",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "status": 200,
                    "response": {
                        "images": [{
                            "id": "create-smoke-image",
                            "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
                            "prompt": "smoke image prompt",
                            "model": "sdxl-smoke",
                            "size": "1024x1024",
                            "cost_usd": 0.02,
                        }]
                    },
                }),
            ) if route.request.method == "POST" else route.continue_(),
        )
        page.route(
            "**/v2/code/sessions/start",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"name": "smoke-code", "status": "started", "model": "qwen-smoke"}),
            ) if route.request.method == "POST" else route.continue_(),
        )
        page.route(
            "**/v2/code/sessions/send",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "status": "ok"}),
            ) if route.request.method == "POST" else route.continue_(),
        )
        page.route(
            "**/v2/code/review",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"status": 200, "response": {"text": "reviewed screenshot"}}),
            ) if route.request.method == "POST" else route.continue_(),
        )
        page.route(
            "**/v2/console/tmux",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "generated_at": 1,
                    "sessions": [{
                        "name": "smoke-tmux",
                        "display_name": "Smoke TMux",
                        "live": True,
                        "attached": False,
                        "read_only": False,
                        "windows": 1,
                        "idle_seconds": 0,
                        "project_dir": "/tmp/smoke",
                        "process_status": "running",
                    }],
                    "allowed_keys": ["Enter", "Escape"],
                    "terminal": {
                        "path": "/#code",
                        "query_param": "session",
                        "websocket_path": "/ws/tmux",
                        "default_legacy_port": 18182,
                    },
                    "summary": {
                        "sessions_total": 1,
                        "sessions_live": 1,
                        "sessions_read_only": 0,
                        "sessions_attached": 0,
                        "estimated_cost_usd": 0,
                        "estimated_tokens": 0,
                    },
                    "errors": {},
                }),
            ) if route.request.method == "GET" else route.continue_(),
        )
        page.route(
            "**/v2/console/tmux/capture",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"output": "smoke tmux capture", "name": "smoke-tmux"}),
            ) if route.request.method == "POST" else route.continue_(),
        )
        page.goto(base_url, wait_until="networkidle")
        expect(page.get_by_test_id("shell-floating-menu")).to_be_visible()
        assert_loaded_image(page.get_by_test_id("shell-brand-icon").locator("img"), "shell MDE app icon")
        expect(page.get_by_test_id("shell-floating-menu")).to_contain_text("MDE")
        expect(page.get_by_test_id("shell-floating-menu")).to_contain_text("LLM-PROXY Console v2")
        expect(page.get_by_test_id("shell-version")).to_be_visible()
        expect(page.get_by_test_id("shell-version")).to_contain_text(re.compile(r"v\d+\.\d+"))
        expect(page.get_by_test_id("shell-floating-menu")).to_contain_text("Workspace")
        expect(page.get_by_test_id("shell-floating-menu")).to_contain_text("Chat")
        expect(page.get_by_test_id("shell-menu-toggle")).to_have_attribute("aria-expanded", "false")
        expect(page.get_by_test_id("shell-cost-control")).to_be_visible()
        expect(page.get_by_test_id("shell-cost-minute")).to_contain_text("$")
        expect(page.get_by_test_id("shell-cost-day")).to_contain_text("$")
        expect(page.get_by_test_id("shell-cost-month")).to_contain_text("$")
        expect(page.locator(".sideRail")).to_have_count(0)
        expect(page.locator(".heroNav")).to_have_count(0)

        expect(page.get_by_role("heading", name="What's New")).to_be_visible()
        expect(page.locator(".whatsNewSections")).to_be_visible()
        expect(page.locator(".whatsNewSectionHeader").filter(has_text="DigitalOcean LLM links").first).to_be_visible()
        expect(page.get_by_role("link", name="Available Inference Models")).to_be_visible()
        assert_no_broken_model_artwork(page, "startup Whats New")
        page.get_by_role("button", name="Close What's New").click()
        expect(page.locator(".whatsNewModal")).to_have_count(0)
        page.get_by_test_id("shell-cost-control").locator("summary").click()
        expect(page.locator(".shellCostPanel")).to_be_visible()
        expect(page.get_by_test_id("shell-cost-threshold")).to_be_visible()
        expect(page.get_by_test_id("shell-cost-save")).to_be_visible()
        expect(page.get_by_test_id("shell-cost-override")).to_be_visible()
        page.get_by_test_id("shell-cost-control").locator("summary").click()
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        drawer = open_shell_drawer(page)
        assert_loaded_image(drawer.get_by_test_id("drawer-brand-icon").locator("img"), "drawer MDE app icon")
        for key in ("chat", "code", "research", "create"):
            expect(drawer.get_by_test_id(f"shell-nav-{key}")).to_be_visible()
        expect(drawer.get_by_test_id("shell-nav-models")).to_have_count(0)
        expect(drawer.get_by_test_id("shell-nav-advanced")).to_have_count(0)
        expect(drawer.get_by_test_id("shell-nav-chat")).to_contain_text("Autonomous command center")
        assert page.evaluate("document.activeElement && document.activeElement.dataset && document.activeElement.dataset.testid") == "shell-nav-chat"
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("shell-navigation-drawer")).not_to_be_visible()
        expect(page.get_by_test_id("shell-menu-toggle")).to_be_focused()
        drawer = open_shell_drawer(page)
        drawer.get_by_test_id("shell-drawer-switcher").click()
        expect(page.get_by_test_id("shell-navigation-drawer")).not_to_be_visible()
        expect(page.locator(".quickSwitcher")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator(".quickSwitcher")).to_have_count(0)
        drawer = open_shell_drawer(page)
        drawer.get_by_test_id("shell-drawer-settings").click()
        expect(page.get_by_test_id("shell-navigation-drawer")).not_to_be_visible()
        expect(page.get_by_role("heading", name="Advanced")).to_be_visible()
        expect(page.get_by_role("heading", name="Models", exact=True)).to_be_visible()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Models", exact=True)).to_have_class(re.compile("active"))
        # Models is the Advanced landing (Overview folded in): its metrics strip and brand-card grid.
        model_metrics = page.locator(".modelMetrics")
        expect(model_metrics).to_be_visible()
        expect(model_metrics).to_contain_text("Total")
        expect(model_metrics).to_contain_text("Routable")
        expect(model_metrics).to_contain_text("Attention")
        expect(page.locator(".modelGrid .mdlCard").first).to_be_visible()
        expect(page.locator(".modelGrid .modelLogo").first).to_be_visible()
        readiness_pulse = page.get_by_test_id("advanced-readiness-pulse")
        expect(readiness_pulse).to_be_visible()
        expect(readiness_pulse).not_to_contain_text("Syncing Readiness", timeout=20000)
        expect(readiness_pulse).to_contain_text("block")
        expect(readiness_pulse).to_contain_text("adv")
        expect(readiness_pulse).to_contain_text("checks")
        # Readiness reasons depend on the ephemeral server's live drift/state,
        # which is empty on a clean checkout (e.g. CI). Assert reason rendering
        # only when reasons exist; run_readiness_advisory_label_smoke covers the
        # reasons list and "Config drift" content deterministically with mocks.
        readiness_reasons = page.get_by_test_id("advanced-readiness-reason")
        if readiness_reasons.count() > 0:
            expect(page.get_by_test_id("advanced-readiness-reasons")).to_be_visible()
            expect(readiness_reasons.first).to_be_visible()
            expect(readiness_reasons.first).not_to_contain_text("#1 Operator Action")
        readiness_pulse.click()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Operate", exact=True)).to_have_class(re.compile("active"))
        expect(page.get_by_test_id("operate-payment-review")).to_be_visible()
        expect(page.get_by_test_id("operate-payment-review")).to_contain_text("Payment Review and Cost Guard")
        expect(page.get_by_test_id("operate-cost-threshold")).to_be_visible()
        # payment_review.items come from the real /v2/operate cost_control payload
        # (unmocked in the desktop flow), so a clean checkout (CI) has none. The
        # panel + threshold are static; assert item rows only when present.
        payment_review_items = page.get_by_test_id("operate-payment-review-item")
        if payment_review_items.count() > 0:
            expect(payment_review_items.first).to_be_visible()
        expect(page.get_by_test_id("operate-release")).to_be_visible()
        handoff_brief = page.get_by_test_id("operate-release-handoff-brief")
        expect(handoff_brief).to_be_visible()
        if "Brief Ready" in handoff_brief.inner_text():
            expect(page.get_by_test_id("operate-release-action-plan")).to_be_visible()
            expect(page.get_by_test_id("operate-release-action-plan-item").first).to_contain_text("#1")
            page.get_by_test_id("operate-release-action-plan-item").first.get_by_role("button", name="Copy Packet").click()
            expect(page.get_by_test_id("operate-release-action-plan-item").first).to_contain_text("Packet copied")
            copied_packet = page.evaluate("window.__mattsSmokeClipboard || ''")
            assert copied_packet.startswith("### 1. Dedicated Inference live capacity verification")
            assert "Urgency: highest" in copied_packet
            assert "Why this matters:" in copied_packet
            assert "Closure template:" in copied_packet
            assert "# Operator Handoff Brief" not in copied_packet
            page.get_by_test_id("operate-release-handoff-item").first.get_by_role("button", name="Copy Closure").click()
            expect(page.get_by_test_id("operate-release-handoff-item").first).to_contain_text("Closure copied")
            copied_closure = page.evaluate("window.__mattsSmokeClipboard || ''")
            assert copied_closure.startswith("Status cell: Closed <YYYY-MM-DD>")
            assert "Gate: live-cloud" in copied_closure
            assert "# Operator Handoff Brief" not in copied_closure
            page.get_by_test_id("operate-release-handoff-brief").get_by_role("button", name="Copy Handoff").click()
            expect(page.get_by_test_id("operate-release-handoff-brief")).to_contain_text("Handoff copied")
            copied_handoff = page.evaluate("window.__mattsSmokeClipboard || ''")
            assert "# Operator Handoff Brief" in copied_handoff
            assert "## Ranked Action Plan" in copied_handoff
            assert "## Operator Item Packets" in copied_handoff
            assert "Dedicated Inference live capacity verification" in copied_handoff
            assert "GitHub repository administration" in copied_handoff
            assert "Urgency: highest" in copied_handoff
            assert "Why this matters:" in copied_handoff
            assert "Next action:" in copied_handoff
            assert "Evidence required:" in copied_handoff
            assert "Closure template:" in copied_handoff
            assert "Status cell: Closed <YYYY-MM-DD>" in copied_handoff
            assert "Gate: live-cloud" in copied_handoff
            with page.expect_download() as handoff_download:
                page.get_by_test_id("operate-release-handoff-brief").get_by_role("button", name="Download Handoff").click()
            assert handoff_download.value.suggested_filename.startswith("mde-llm-proxy-operator-handoff-")
            assert handoff_download.value.suggested_filename.endswith(".md")
        else:
            expect(handoff_brief).to_contain_text("No handoff")
        navigate_shell(page, "chat")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        page.keyboard.press("Control+K")
        expect(page.get_by_role("heading", name="Switch Workspace")).to_be_visible()
        page.get_by_role("button", name="Copy Current Workspace Link").click()
        expect(page.locator(".quickSwitcherHeader")).to_contain_text("Link copied")
        copied_workspace_link = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert copied_workspace_link.startswith(base_url)
        assert copied_workspace_link.endswith("#chat")
        page.keyboard.press("Escape")
        expect(page.locator(".quickSwitcher")).to_have_count(0)
        open_shell_drawer(page).get_by_test_id("shell-drawer-switcher").click()
        expect(page.get_by_test_id("shell-navigation-drawer")).not_to_be_visible()
        expect(page.locator(".quickSwitcher")).to_be_visible()
        page.locator(".quickSwitcherSearch input").fill("advanced")
        expect(page.locator(".quickSwitcherList").get_by_role("option", name=re.compile("Advanced"))).to_be_visible()
        page.locator(".quickSwitcherList").get_by_role("option", name=re.compile("Advanced")).click()
        expect(page.get_by_role("heading", name="Advanced")).to_be_visible()
        assert page.evaluate("window.location.hash") == "#advanced"
        page.keyboard.press("Control+K")
        page.get_by_role("button", name="Copy Current Workspace Link").click()
        expect(page.locator(".quickSwitcherHeader")).to_contain_text("Link copied")
        copied_workspace_link = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert copied_workspace_link.startswith(base_url)
        assert copied_workspace_link.endswith("#advanced")
        page.keyboard.press("Escape")
        navigate_shell(page, "chat")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()

        page.goto(base_url + "#models", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Advanced")).to_be_visible()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Models", exact=True)).to_have_class(re.compile("active"))
        expect(page.get_by_role("heading", name="Models")).to_be_visible()
        drawer = open_shell_drawer(page)
        expect(drawer.get_by_test_id("shell-nav-models")).to_have_count(0)
        expect(drawer.get_by_test_id("shell-nav-advanced")).to_have_count(0)
        for key in ("chat", "code", "research", "create"):
            expect(drawer.get_by_test_id(f"shell-nav-{key}")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("shell-navigation-drawer")).not_to_be_visible()
        assert_no_broken_model_artwork(page, "models hash route")
        page.goto(base_url + "#not-a-real-tab", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        navigate_shell(page, "research")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        assert page.evaluate("window.location.hash") == "#research"
        navigate_shell(page, "chat")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        assert page.evaluate("window.location.hash") == "#chat"
        expect(page.get_by_text("Autonomous System Manager")).to_be_visible()
        expect(page.locator(".icqContactPane")).to_be_visible()
        expect(page.locator(".icqChatWindow")).to_be_visible()
        contact_cards = page.locator('.icqContactPane [data-testid="chat-contact-card"]')
        expect(page.locator(".icqContactGroups")).to_contain_text("Pinned")
        drawer_toggle = page.get_by_test_id("chat-contacts-drawer-toggle")
        expect(drawer_toggle).to_be_visible()
        expect(drawer_toggle).to_have_attribute("aria-expanded", "false")
        expect(drawer_toggle).to_contain_text("All contacts")
        expect(contact_cards.first).to_be_visible()
        # V2-083: every model identity card carries a training-nation flag badge on its logo tile.
        expect(contact_cards.first.locator(".mdlFlagBadge")).to_be_visible()
        expect(page.locator('.icqContactPane .mdlCard.active')).to_be_visible()
        collapsed_count = contact_cards.count()
        first_contact_name = contact_cards.first.locator(".mdlCardName").inner_text().replace("✨", "").strip()
        page.locator(".icqContactSearch input").fill(first_contact_name)
        expect(drawer_toggle).to_have_attribute("aria-expanded", "true")
        expect(contact_cards.first).to_contain_text(first_contact_name)
        page.locator(".icqContactSearch input").fill("")
        expect(drawer_toggle).to_have_attribute("aria-expanded", "false")
        drawer_toggle.click()
        expect(drawer_toggle).to_have_attribute("aria-expanded", "true")
        assert contact_cards.count() >= collapsed_count
        if contact_cards.count() > 1:
            second_contact = contact_cards.nth(1)
            second_contact_name = second_contact.locator(".mdlCardName").inner_text().replace("✨", "").strip()
            second_contact.locator(".mdlCardBody").click()
            expect(page.locator(".icqChatTitle")).to_contain_text(second_contact_name)
            page.locator('.icqContactPane .mdlCard.active .mdlCardStar').click()
            expect(page.locator(".icqPinnedGroup")).to_contain_text(second_contact_name)
        drawer_toggle.click()
        expect(drawer_toggle).to_have_attribute("aria-expanded", "false")
        page.get_by_role("button", name="Dark", exact=True).click()
        expect(page.locator(".chatHero")).to_have_class(re.compile("chatThemeDark"))
        page.get_by_role("button", name="Light", exact=True).click()
        expect(page.locator(".chatHero")).to_have_class(re.compile("chatThemeLight"))
        assert_no_document_horizontal_overflow(page, "desktop ICQ Chat")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("button", name="Contacts", exact=True)).to_be_visible()
        assert_no_document_horizontal_overflow(page, "mobile ICQ Chat closed")
        page.get_by_role("button", name="Contacts", exact=True).click()
        page.wait_for_function("document.querySelector('.chatHero')?.classList.contains('contactPaneOpen')", timeout=5000)
        page.wait_for_function(
            """
            () => {
              const pane = document.querySelector('.icqContactPane');
              if (!pane) return false;
              const rect = pane.getBoundingClientRect();
              return rect.left >= -1 && rect.right <= window.innerWidth + 2;
            }
            """,
            timeout=5000,
        )
        drawer_box = page.locator(".icqContactPane").bounding_box()
        assert drawer_box and drawer_box["x"] >= -1 and drawer_box["width"] <= 390, "mobile contact drawer escaped viewport: %s" % drawer_box
        assert_no_document_horizontal_overflow(page, "mobile ICQ Chat drawer")
        page.locator(".icqCloseContacts").click()
        page.set_viewport_size({"width": 1440, "height": 950})
        expect(page.locator(".shellVoiceTools")).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("Voice On|Voice Off"))).to_be_visible()
        expect(page.get_by_label("Global voice preset")).to_be_visible()
        expect(page.get_by_label("Global speech language")).to_be_visible()
        expect(page.get_by_label("Global voice preset")).to_have_value("mission_control")
        expect(page.locator(".voiceConsole")).to_be_visible()
        expect(page.locator(".voiceConsole")).to_contain_text("Voice enabled")
        expect(page.locator(".voiceConsole")).to_contain_text("Samantha-style Assistant")
        expect(page.locator(".voiceConsole")).to_contain_text("Browser fallback")
        expect(page.locator(".voiceConsole")).to_contain_text("global preset")
        expect(page.locator(".voiceConsole")).not_to_contain_text("MATTS_SPEECH_ENGINE")
        expect(page.locator(".voiceConsole").get_by_role("button", name=re.compile("Listen|Stop Listen"))).to_be_visible()
        expect(page.locator(".voiceConsole").get_by_role("button", name="Download Speech", exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="Preview", exact=True)).to_be_enabled()
        page.wait_for_function(
            """
            () => {
              const panel = document.querySelector('.voiceConsole');
              const lead = document.querySelector('.voiceConsoleLead');
              const controls = document.querySelector('.voiceControls');
              const settings = document.querySelector('.voiceSettings');
              if (!panel || !lead || !controls || !settings) return false;
              const panelRect = panel.getBoundingClientRect();
              const leadRect = lead.getBoundingClientRect();
              const controlsRect = controls.getBoundingClientRect();
              const settingsRect = settings.getBoundingClientRect();
              const separated = controlsRect.top >= leadRect.bottom - 1 || controlsRect.left >= leadRect.right - 1;
              const settingsSeparated = settingsRect.top >= Math.max(leadRect.bottom, controlsRect.bottom) - 1;
              const contained = controlsRect.right <= panelRect.right + 2 && leadRect.right <= panelRect.right + 2 && settingsRect.right <= panelRect.right + 2;
              return separated && settingsSeparated && contained && panel.scrollWidth <= panel.clientWidth + 2;
            }
            """,
            timeout=5000,
        )
        page.get_by_role("button", name="Mute", exact=True).click()
        expect(page.locator(".voiceConsole")).to_contain_text("Voice muted")
        expect(page.get_by_role("button", name="Voice Off")).to_be_visible()
        page.get_by_role("button", name="Enable", exact=True).click()
        expect(page.locator(".voiceConsole")).to_contain_text("Voice enabled")
        expect(page.get_by_label("Global voice preset")).to_be_visible()
        expect(page.locator(".transcriptToolbar").get_by_role("button", name="Copy Brief")).to_be_disabled()
        expect(page.locator(".transcriptToolbar").get_by_role("button", name="Download Brief")).to_be_disabled()
        page.wait_for_function(
            """
            () => {
              const toolbar = document.querySelector('.transcriptToolbar');
              const summary = document.querySelector('.transcriptToolbar > div:first-child');
              const actions = document.querySelector('.transcriptActions');
              if (!toolbar || !summary || !actions) return false;
              const toolbarRect = toolbar.getBoundingClientRect();
              const summaryRect = summary.getBoundingClientRect();
              const actionsRect = actions.getBoundingClientRect();
              const separated = actionsRect.top >= summaryRect.bottom - 1 || actionsRect.left >= summaryRect.right - 1;
              const contained = actionsRect.right <= toolbarRect.right + 2 && summaryRect.right <= toolbarRect.right + 2;
              return separated && contained && toolbar.scrollWidth <= toolbar.clientWidth + 2;
            }
            """,
            timeout=5000,
        )
        expect(page.locator(".starterDeck")).to_have_count(0)
        page.locator(".voiceConsole").get_by_role("button", name="Mute", exact=True).click()
        page.locator(".chatHero .icqComposerInput").fill("Verify the V2 smoke transcript path.")
        expect(page.locator(".chatHero .icqComposerInput")).to_have_value("Verify the V2 smoke transcript path.")
        with page.expect_response(lambda response: response.url.endswith("/v2/chat") and response.status == 200):
            page.locator(".chatHero .icqComposerInput").press("Enter")
        expect(page.locator(".icqChatStats")).to_contain_text("2 messages")
        expect(page.locator(".transcriptToolbar").get_by_role("button", name="Copy", exact=True)).to_be_enabled()
        expect(page.locator(".transcriptToolbar").get_by_role("button", name="Download", exact=True)).to_be_enabled()
        expect(page.locator(".transcriptToolbar").get_by_role("button", name="Copy Brief")).to_be_enabled()
        expect(page.locator(".transcriptToolbar").get_by_role("button", name="Download Brief")).to_be_enabled()
        expect(page.locator(".transcriptToolbar").get_by_role("button", name="Clear", exact=True)).to_be_enabled()
        expect(page.locator(".messageRow.assistant")).to_contain_text("V2 smoke transcript response")
        stored_transcript = page.evaluate("window.sessionStorage.getItem('matts-v2-chat-transcript')")
        assert stored_transcript and "V2 smoke transcript response" in stored_transcript
        navigate_shell(page, "research")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        navigate_shell(page, "chat")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        expect(page.locator(".icqChatStats")).to_contain_text("2 messages")
        expect(page.locator(".messageRow.assistant")).to_contain_text("V2 smoke transcript response")
        page.locator(".transcriptToolbar").get_by_role("button", name="Copy", exact=True).click()
        expect(page.locator(".icqChatStats")).to_contain_text("Copied")
        page.locator(".transcriptToolbar").get_by_role("button", name="Copy Brief").click()
        expect(page.locator(".icqChatStats")).to_contain_text("Brief copied")
        copied_chat_brief = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# Chat Brief" in copied_chat_brief and "V2 smoke transcript response" in copied_chat_brief and "Active Model:" in copied_chat_brief
        with page.expect_download() as download_info:
            page.locator(".transcriptToolbar").get_by_role("button", name="Download", exact=True).click()
        assert download_info.value.suggested_filename.startswith("mde-llm-proxy-chat-transcript-")
        with page.expect_download() as chat_brief_download:
            page.locator(".transcriptToolbar").get_by_role("button", name="Download Brief").click()
        assert chat_brief_download.value.suggested_filename.startswith("mde-llm-proxy-chat-brief-")
        assert chat_brief_download.value.suggested_filename.endswith(".md")
        page.locator(".transcriptToolbar").get_by_role("button", name="Clear", exact=True).click()
        expect(page.locator(".icqChatStats")).to_contain_text("0 messages")
        expect(page.get_by_text("No conversation yet.")).to_be_visible()
        assert page.evaluate("window.sessionStorage.getItem('matts-v2-chat-transcript')") is None
        page.locator(".chatHero .icqComposerInput").fill("line one")
        page.locator(".chatHero .icqComposerInput").press("Shift+Enter")
        expect(page.locator(".chatHero .icqComposerInput")).to_have_value("line one\n")
        page.locator(".chatHero .icqComposerInput").fill("detail-string-smoke")
        with page.expect_response(lambda response: response.url.endswith("/v2/chat") and response.status == 400):
            page.get_by_role("button", name="Send", exact=True).click()
        expect(page.locator(".errorBanner")).to_have_text("Hero client detail string reached the UI")
        expect(page.get_by_text("v2 request failed: 400")).to_have_count(0)
        page.locator(".chatHero .icqComposerInput").fill("plain-text-smoke")
        with page.expect_response(lambda response: response.url.endswith("/v2/chat") and response.status == 502):
            page.get_by_role("button", name="Send", exact=True).click()
        expect(page.locator(".errorBanner")).to_have_text("Hero client plain text error reached the UI")
        expect(page.get_by_text("v2 request failed: 502")).to_have_count(0)
        page.locator(".chatHero .icqComposerInput").fill("route-diagnostic-smoke")
        with page.expect_response(lambda response: response.url.endswith("/v2/chat") and response.status == 404):
            page.get_by_role("button", name="Send", exact=True).click()
        expect(page.locator(".errorBanner")).to_have_text("api endpoint not found. Use POST /v2/chat; this endpoint exists but not for GET.")

        navigate_shell(page, "code")
        expect(page.get_by_role("heading", name="Code")).to_be_visible()
        # V2-082 Q10: the Code model picker is a custom listbox; favorites lead and the rest
        # stays behind a More-models expander. Close via the trigger (its keydown owns Escape).
        code_model_trigger = page.locator(".mdlSelectTrigger").first
        expect(code_model_trigger).to_be_visible()
        code_model_trigger.click()
        expect(page.locator(".mdlSelectPopover")).to_be_visible()
        expect(page.locator(".mdlSelectFilter")).to_be_visible()
        code_select_favorites = json.loads(page.evaluate("window.localStorage.getItem('matts-v2-model-favorites') || '[]'"))
        if code_select_favorites:
            select_more = page.locator(".mdlSelectMore")
            expect(select_more).to_be_visible()
            select_more.click()
            expect(select_more).to_have_count(0)
        code_model_trigger.click()
        expect(page.locator(".mdlSelectPopover")).to_have_count(0)
        expect(page.locator(".codeOutputConsole").get_by_role("button", name="Copy Brief")).to_be_disabled()
        expect(page.locator(".codeOutputConsole").get_by_role("button", name="Download Brief")).to_be_disabled()
        image_path = Path(tempfile.gettempdir()) / "v2-smoke-image.png"
        image_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        with page.expect_response(lambda response: "/v2/code/attachments" in response.url and response.status == 200):
            page.locator('input[type="file"]').set_input_files(str(image_path))
        expect(page.locator(".attachmentCard").get_by_text("v2-smoke-image.png")).to_be_visible()
        expect(page.locator(".attachmentCard img")).to_have_count(1)
        expect(page.locator(".attachmentCard")).to_contain_text("1 x 1")
        expect(page.locator(".attachmentCard").get_by_role("button", name="Remove")).to_be_visible()
        page.locator(".codeHero .xlInput").fill("code line one")
        page.locator(".codeHero .xlInput").press("Enter")
        expect(page.locator(".codeHero .xlInput")).to_have_value("code line one\n")
        page.locator(".codeHero .xlInput").fill("please review smoke screenshot")
        with page.expect_response(lambda response: "/v2/code/sessions/start" in response.url and response.status == 200):
            page.get_by_role("button", name="Start Session", exact=True).click()
        expect(page.locator(".codeOutputConsole")).to_contain_text("Session started")
        expect(page.locator(".codeOutputConsole")).to_contain_text("smoke-code")
        page.locator(".codeHero .xlInput").press("Control+Enter")
        expect(page.get_by_test_id("code-prompt-preview")).to_contain_text("Prompt Bundle Preview")
        expect(page.get_by_test_id("code-context-tray")).to_contain_text("v2-smoke-image.png")
        with page.expect_response(lambda response: "/v2/code/sessions/send" in response.url and response.status == 200):
            page.get_by_test_id("code-prompt-preview").get_by_role("button", name="Send Bundle").click()
        expect(page.locator(".codeOutputConsole")).to_contain_text("Sent to tmux")
        expect(page.get_by_test_id("code-worker-mirrors")).to_contain_text("Claude Code prompt bundle")
        page.locator(".codeHero .xlInput").fill("review smoke screenshot")
        with page.expect_response(lambda response: "/v2/code/review" in response.url and response.status == 200):
            page.get_by_role("button", name="Ask Model To Review Image", exact=True).click()
        expect(page.locator(".codeOutputConsole")).to_contain_text("Image review response")
        expect(page.locator(".codeOutputConsole")).to_contain_text("reviewed screenshot")
        expect(page.locator(".codeOutputConsole").get_by_text("Raw payload").first).to_be_visible()
        page.locator(".codeHero .xlInput").fill("follow up after screenshot review")
        stored_code = page.evaluate("window.sessionStorage.getItem('matts-v2-code-workspace')")
        assert stored_code and "reviewed screenshot" in stored_code and "v2-smoke-image.png" in stored_code
        navigate_shell(page, "research")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        navigate_shell(page, "code")
        expect(page.get_by_role("heading", name="Code")).to_be_visible()
        expect(page.locator(".codeHero .xlInput")).to_have_value("follow up after screenshot review")
        expect(page.locator(".attachmentCard").get_by_text("v2-smoke-image.png")).to_be_visible()
        expect(page.locator(".attachmentCard img")).to_have_count(1)
        expect(page.locator(".codeOutputConsole")).to_contain_text("Restored")
        expect(page.locator(".codeOutputConsole")).to_contain_text("Image review response")
        expect(page.locator(".codeOutputConsole")).to_contain_text("reviewed screenshot")
        page.locator(".codeOutputCard").first.get_by_role("button", name=re.compile("Copy Event")).click()
        expect(page.locator(".codeOutputCard").first).to_contain_text("Copied")
        copied_code_event = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# Code Event Packet" in copied_code_event
        assert "Title: Image review response" in copied_code_event and "Status:" in copied_code_event
        assert "Detail: reviewed screenshot" in copied_code_event and "## Raw Payload" in copied_code_event
        page.locator(".codeOutputConsole").get_by_role("button", name="Copy", exact=True).click()
        expect(page.locator(".codeOutputConsole")).to_contain_text("Copied")
        page.locator(".codeOutputConsole").get_by_role("button", name="Copy Brief").click()
        expect(page.locator(".codeOutputConsole")).to_contain_text("Brief copied")
        copied_code_brief = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# Code Brief" in copied_code_brief and "reviewed screenshot" in copied_code_brief and "v2-smoke-image.png" in copied_code_brief
        with page.expect_download() as code_brief_download:
            page.locator(".codeOutputConsole").get_by_role("button", name="Download Brief").click()
        assert code_brief_download.value.suggested_filename.startswith("mde-llm-proxy-code-brief-")
        assert code_brief_download.value.suggested_filename.endswith(".md")
        page.locator(".codeOutputConsole").get_by_role("button", name="Clear", exact=True).click()
        expect(page.locator(".codeOutputConsole")).to_contain_text("0 events")
        expect(page.get_by_text("Session output and image review responses will appear here.")).to_be_visible()
        page.wait_for_function("JSON.parse(window.sessionStorage.getItem('matts-v2-code-workspace') || '{}').actions?.length === 0")

        navigate_shell(page, "research")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        expect(page.locator(".researchBriefDock")).to_contain_text("No packet")
        expect(page.locator(".researchBriefDock").get_by_role("button", name="Copy Packet")).to_be_disabled()
        expect(page.locator(".researchBriefDock").get_by_role("button", name="Download Packet")).to_be_disabled()
        expect(page.locator(".researchBriefDock").get_by_role("button", name="Print / Save PDF")).to_be_disabled()
        expect(page.locator(".researchTabs").get_by_role("tab", name="Advanced Search")).to_have_attribute("aria-selected", "true")
        page.locator(".searchLine input").fill("DigitalOcean LLM models")
        research_mode_options = page.locator(".searchLine select option").all_text_contents()
        selected_research_mode = research_mode_options[-1] if research_mode_options else "Balanced"
        page.locator(".searchLine select").select_option(label=selected_research_mode)
        expect(page.locator(".engineControls")).to_contain_text("All engines selected")
        expect(page.locator(".engineControls").get_by_role("button", name="Select All")).to_be_enabled()
        expect(page.locator(".engineControls").get_by_role("button", name="Select All")).to_have_attribute("aria-pressed", "true")
        expect(page.locator(".engineControls").get_by_role("button", name="Required Sources")).to_have_attribute("aria-pressed", "false")
        page.locator(".engineControls").get_by_role("button", name="Clear").click()
        expect(page.get_by_role("button", name="Search", exact=True)).to_be_disabled()
        expect(page.get_by_text("Select at least one research engine")).to_be_visible()
        expect(page.locator(".engineControls").get_by_role("button", name="Select All")).to_have_attribute("aria-pressed", "false")
        expect(page.locator(".engineControls").get_by_role("button", name="Required Sources")).to_have_attribute("aria-pressed", "false")
        page.locator(".engineControls").get_by_role("button", name="Required Sources").click()
        expect(page.locator(".engineControls")).to_contain_text("5 required sources selected")
        expect(page.get_by_role("button", name="Search", exact=True)).to_be_enabled()
        expect(page.locator(".engineControls").get_by_role("button", name="Select All")).to_have_attribute("aria-pressed", "false")
        expect(page.locator(".engineControls").get_by_role("button", name="Required Sources")).to_have_attribute("aria-pressed", "true")
        required_source_ids = ["images", "examples", "mapping", "wikipedia", "technical-docs"]
        page.wait_for_function(
            """
            (ids) => {
              const raw = window.sessionStorage.getItem('matts-v2-research-workspace');
              if (!raw) return false;
              const workspace = JSON.parse(raw);
              const selected = workspace.selectedEngines || [];
              return workspace.engineSelectionMode === 'custom'
                && selected.length === ids.length
                && ids.every((id) => selected.includes(id));
            }
            """,
            arg=required_source_ids,
        )
        with page.expect_response(lambda response: "/v2/research/search" in response.url and response.status == 200):
            page.locator(".researchHero .searchLine input").press("Enter")
        expect(page.locator(".researchTabs").get_by_role("tab", name="Results")).to_have_attribute("aria-selected", "true")
        expect(page.locator(".researchCommandBoard")).to_be_visible()
        expect(page.locator(".researchMetrics")).to_contain_text("Evidence")
        expect(page.locator(".researchMetrics")).to_contain_text("Live")
        expect(page.locator(".researchMetrics")).to_contain_text("Sources")
        expect(page.locator(".researchMetrics")).to_contain_text("Degraded")
        source_coverage = page.get_by_test_id("research-source-coverage")
        expect(source_coverage).to_contain_text("images")
        expect(source_coverage).to_contain_text("examples")
        expect(source_coverage).to_contain_text("mapping services")
        expect(source_coverage).to_contain_text("Wikipedia")
        expect(source_coverage).to_contain_text("technical documentation")
        technical_docs_coverage = source_coverage.get_by_role("button", name=re.compile("technical documentation", re.I))
        technical_docs_coverage.click()
        expect(technical_docs_coverage).to_have_attribute("aria-pressed", "true")
        expect(page.locator(".researchFilters").get_by_role("button", name="Technical Documentation")).to_have_class(re.compile("active"))
        first_research_result = page.locator(".lexisResultRow").first
        expect(first_research_result).to_contain_text("Technical Documentation")
        first_research_title = first_research_result.locator("summary strong").inner_text()
        copy_source_button = first_research_result.get_by_role("button", name=re.compile("Copy Source"))
        copy_source_button.click()
        expect(copy_source_button).to_contain_text("Copied")
        copied_source_packet = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert first_research_title in copied_source_packet
        assert "Engine: Technical Documentation" in copied_source_packet and "Citation:" in copied_source_packet and "Snippet:" in copied_source_packet
        expect(page.locator(".researchFilters").get_by_role("button", name="All evidence")).to_be_visible()
        page.locator(".researchFilters").get_by_role("button", name="All evidence").click()
        expect(technical_docs_coverage).to_have_attribute("aria-pressed", "false")
        assert page.locator(".researchFilters button").count() >= 2
        page.locator(".researchFilters button").nth(1).click()
        expect(page.locator(".lexisResultRow").first).to_be_visible()
        page.locator(".researchFilters").get_by_role("button", name="All evidence").click()
        first_pin_button = page.locator(".lexisResultRow .pinButton").first
        with page.expect_response(lambda response: "/v2/research/dossiers/" in response.url and response.url.endswith("/pins") and response.status == 200):
            first_pin_button.click()
        expect(first_pin_button).to_have_attribute("aria-pressed", "true")
        expect(page.locator(".researchBriefDock")).to_contain_text("Packet Ready")
        expect(page.locator(".researchBriefDock").get_by_role("button", name="Copy Packet")).to_be_enabled()
        expect(page.locator(".researchBriefDock").get_by_role("button", name="Download Packet")).to_be_enabled()
        expect(page.locator(".researchBriefDock").get_by_role("button", name="Print / Save PDF")).to_be_enabled()
        page.locator(".researchBriefDock").get_by_role("button", name="Copy Packet").click()
        expect(page.locator(".researchBriefDock")).to_contain_text("Copied")
        copied_research_packet = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# " in copied_research_packet and "DigitalOcean LLM models" in copied_research_packet and "## Source Classes" in copied_research_packet and "## Full Report Sections" in copied_research_packet
        with page.expect_download() as research_download:
            page.locator(".researchBriefDock").get_by_role("button", name="Download Packet").click()
        assert research_download.value.suggested_filename.startswith("mde-llm-proxy-research-packet-")
        assert research_download.value.suggested_filename.endswith(".md")
        with page.expect_response(lambda response: "/v2/research/dossiers/" in response.url and response.url.endswith("/report") and response.status == 200):
            page.locator(".researchBriefDock").get_by_role("button", name="Print / Save PDF").click()
        page.wait_for_function("window.__mattsPrintCalled === true")
        expect(page.locator(".researchPrintFrame")).to_contain_text("DigitalOcean LLM models")

        page.locator(".researchTabs").get_by_role("tab", name="Synthesis Brief").click()
        expect(page.locator(".researchTabs").get_by_role("tab", name="Synthesis Brief")).to_have_attribute("aria-selected", "true")
        expect(page.get_by_test_id("research-claim-map")).to_be_visible()
        expect(page.get_by_test_id("research-claim-map")).to_contain_text("Claim Evidence Map")
        expect(page.get_by_test_id("research-claim-map")).to_contain_text("Some selected sources were degraded")
        page.locator(".researchAuditPanel summary").click()
        research_team_panel = page.locator("[data-testid='research-team-panel']").first
        expect(research_team_panel).to_contain_text("3 analysts + 1 coordinator")
        expect(research_team_panel).to_contain_text("Cost guard")
        expect(page.locator("[data-testid='research-model-outputs']")).to_be_visible()
        expect(page.locator("[data-testid='research-coordinated-answer']")).to_contain_text("Coordinated Answer")
        expect(page.locator("[data-testid='research-analyst-outputs']")).to_contain_text("low-cost")

        page.locator(".researchTabs").get_by_role("tab", name="Source Registry").click()
        expect(page.get_by_test_id("research-source-registry")).to_be_visible()
        expect(page.get_by_test_id("research-source-registry")).to_contain_text("Technical Documentation")
        expect(page.get_by_test_id("research-source-registry")).to_contain_text("Included")
        page.locator(".researchTabs").get_by_role("tab", name="Results").click()
        expect(page.locator(".lexisResultTable")).to_be_visible()
        expect(page.locator(".lexisResultTable")).to_contain_text("Bing setup required for DigitalOcean LLM models")
        expect(page.locator(".researchFilters").get_by_role("button", name="Technical Documentation")).to_be_visible()
        page.locator(".researchTabs").get_by_role("tab", name="Advanced Search").click()
        expect(page.locator(".engineStrip button").first).to_be_visible()
        first_engine_class = page.locator(".engineStrip button").first.get_attribute("class") or ""
        assert "active" not in first_engine_class.split()
        expect(page.locator(".engineStrip").get_by_role("button", name=re.compile("Image Sources"))).to_have_class(re.compile("active"))
        page.locator(".engineStrip button").first.click()
        first_engine_class = page.locator(".engineStrip button").first.get_attribute("class") or ""
        assert "active" in first_engine_class.split()
        page.locator(".researchTabs").get_by_role("tab", name="Results").click()
        stored_research = page.evaluate("window.sessionStorage.getItem('matts-v2-research-workspace')")
        assert stored_research and "DigitalOcean LLM models" in stored_research and "engineSelectionMode" in stored_research and "selectedEngines" in stored_research
        assert '"dossier"' in stored_research and '"schema_version":2' in stored_research and '"activeTab":"results"' in stored_research
        navigate_shell(page, "create")
        expect(page.get_by_role("heading", name="Create")).to_be_visible()
        navigate_shell(page, "research")
        expect(page.get_by_role("heading", name="Research")).to_be_visible()
        expect(page.locator(".researchTabs").get_by_role("tab", name="Results")).to_have_attribute("aria-selected", "true")
        expect(page.locator(".researchCommandBoard")).to_be_visible()
        expect(page.locator(".lexisResultRow").first).to_be_visible()
        expect(page.locator(".lexisResultTable")).to_contain_text("Bing setup required for DigitalOcean LLM models")
        page.locator(".researchTabs").get_by_role("tab", name="Advanced Search").click()
        expect(page.locator(".searchLine input")).to_have_value("DigitalOcean LLM models")
        expect(page.locator(".searchLine select")).to_have_value(selected_research_mode)
        first_engine_class = page.locator(".engineStrip button").first.get_attribute("class") or ""
        assert "active" in first_engine_class.split()
        expect(page.locator(".engineStrip").get_by_role("button", name=re.compile("Image Sources"))).to_have_class(re.compile("active"))

        navigate_shell(page, "create")
        expect(page.get_by_role("heading", name="Create")).to_be_visible()
        expect(page.locator("#v2-create-mood")).to_be_visible()
        expect(page.locator(".createAtmosphere span")).to_have_count(3)
        expect(page.locator(".createBriefDock")).to_contain_text("No brief")
        expect(page.locator(".createBriefDock").get_by_role("button", name="Copy Brief")).to_be_disabled()
        expect(page.locator(".createBriefDock").get_by_role("button", name="Download Brief")).to_be_disabled()
        expect(page.locator(".modeSwitch")).to_have_count(0)
        expect(page.locator(".createSourceControls")).to_have_count(0)
        page.locator(".createPrompt textarea").fill("smoke image prompt")
        with page.expect_response(lambda response: "/v2/create/images" in response.url and response.status == 200):
            page.get_by_role("button", name="Generate", exact=True).click()
        expect(page.locator(".createBriefDock")).to_contain_text("Brief Ready")
        expect(page.locator(".createBriefDock").get_by_role("button", name="Copy Brief")).to_be_enabled()
        expect(page.locator(".createHistory")).to_be_visible()
        expect(page.locator(".createHistoryCard")).to_have_count(1)
        expect(page.locator(".createHistoryCard").first).to_contain_text("Image")
        assert "Research" not in page.locator(".createHistoryCard").first.inner_text()
        expect(page.locator(".createHistoryCard").first.locator("img")).to_have_count(1)
        expect(page.locator(".createHistoryCard").first.get_by_role("button", name="Reuse")).to_be_visible()
        expect(page.locator(".createHistoryCard").first.get_by_role("button", name="Copy")).to_be_visible()
        page.locator(".createHistoryCard").first.get_by_role("button", name="Copy").click()
        expect(page.locator(".createHistory")).to_contain_text("Packet copied")
        copied_image_history = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# Create History Packet" in copied_image_history
        assert "Mode: Image" in copied_image_history and "smoke image prompt" in copied_image_history
        assert "## Image Snapshot" in copied_image_history and "sdxl-smoke" in copied_image_history and "embedded data URL" in copied_image_history
        page.locator(".createBriefDock").get_by_role("button", name="Copy Brief").click()
        expect(page.locator(".createBriefDock")).to_contain_text("Brief copied")
        copied_create_brief = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# Create Brief" in copied_create_brief and "smoke image prompt" in copied_create_brief and "Studio: Image creation" in copied_create_brief
        assert "Research Source Mode" not in copied_create_brief and "serverless inference news" not in copied_create_brief
        assert "## Images" in copied_create_brief and "sdxl-smoke" in copied_create_brief and "## Recent History" in copied_create_brief
        with page.expect_download() as create_brief_download:
            page.locator(".createBriefDock").get_by_role("button", name="Download Brief").click()
        assert create_brief_download.value.suggested_filename.startswith("mde-llm-proxy-create-brief-")
        assert create_brief_download.value.suggested_filename.endswith(".md")
        page.locator(".createHistoryCard").first.get_by_role("button", name="Reuse").click()
        expect(page.locator(".createPrompt textarea")).to_have_value("smoke image prompt")
        expect(page.locator(".createImageGrid img")).to_have_count(1)
        expect(page.locator(".imageGalleryResult")).to_contain_text("Image result")
        expect(page.locator(".imageGalleryResult")).to_contain_text("smoke image prompt")
        expect(page.locator(".imageGalleryResult")).to_contain_text("sdxl-smoke")
        expect(page.locator(".imageGalleryResult").get_by_role("link", name="Open")).to_be_visible()
        expect(page.locator(".imageGalleryResult").get_by_role("link", name="Download")).to_be_visible()
        expect(page.locator(".imageGalleryResult")).to_contain_text("Raw payload")
        stored_create = page.evaluate("window.sessionStorage.getItem('matts-v2-create-workspace')")
        assert stored_create and "smoke image prompt" in stored_create and "sdxl-smoke" in stored_create and "serverless inference news" not in stored_create
        open_advanced_tab(page, "models")
        expect(page.get_by_role("heading", name="Models")).to_be_visible()
        navigate_shell(page, "create")
        expect(page.get_by_role("heading", name="Create")).to_be_visible()
        expect(page.locator(".modeSwitch")).to_have_count(0)
        expect(page.locator(".createPrompt textarea")).to_have_value("smoke image prompt")
        expect(page.locator(".createHistory")).to_contain_text("Restored")
        expect(page.locator(".createHistoryCard")).to_have_count(1)
        expect(page.locator(".createHistoryCard").first).to_contain_text("Image")
        assert "Research" not in page.locator(".createHistoryCard").first.inner_text()
        expect(page.locator(".imageGalleryResult")).to_contain_text("smoke image prompt")
        expect(page.locator(".imageGalleryResult")).to_contain_text("sdxl-smoke")

        open_advanced_tab(page, "models")
        expect(page.get_by_role("heading", name="Models")).to_be_visible()
        expect(page.get_by_role("button", name="What's New", exact=True)).to_be_enabled()
        page.get_by_role("button", name="What's New", exact=True).click()
        expect(page.get_by_role("heading", name="What's New")).to_be_visible()
        expect(page.locator(".whatsNewSections")).to_be_visible()
        expect(page.locator(".whatsNewSectionHeader").filter(has_text="New models").first).to_be_visible()
        expect(page.locator(".whatsNewSectionHeader").filter(has_text="Need attention").first).to_be_visible()
        expect(page.locator(".whatsNewSectionHeader").filter(has_text="DigitalOcean LLM links").first).to_be_visible()
        expect(page.locator(".whatsNewModal .mdlCard").first).to_be_visible()
        expect(page.get_by_role("link", name="Available Inference Models")).to_be_visible()
        assert_no_broken_model_artwork(page, "models Whats New")
        page.get_by_role("button", name="Close What's New").click()
        expect(page.locator(".whatsNewModal")).to_have_count(0)
        expect(page.locator(".modelMetric")).to_have_count(4)
        showcase_cards = page.locator('[data-testid="model-showcase-card"]')
        expect(showcase_cards.first).to_be_visible()
        # V2-083: showcase cards carry the flag badge, and no bundled flag image may render broken.
        expect(showcase_cards.first.locator(".mdlFlagBadge")).to_be_visible()
        page.wait_for_function(
            "() => [...document.querySelectorAll('.mdlFlagBadge img')].every((img) => img.complete)",
            timeout=5000,
        )
        broken_flag_sources = page.locator(".mdlFlagBadge img").evaluate_all(
            """
            (imgs) => imgs
              .filter((img) => img.complete && img.naturalWidth === 0)
              .map((img) => img.currentSrc || img.getAttribute('src') || 'unknown')
            """
        )
        assert broken_flag_sources == [], "models grid rendered broken flag badges: %s" % broken_flag_sources
        expect(showcase_cards.first).to_contain_text("Health")
        expect(page.locator(".modelInspector")).to_be_visible()
        expect(page.locator(".modelInspector")).to_contain_text("Model Inspector")
        expect(page.locator(".modelInspector")).to_contain_text("Provider")
        expect(page.locator(".modelInspector")).to_contain_text("Training Nation")
        expect(page.locator(".modelInspectorPalette")).to_be_visible()
        page.locator(".modeSwitch").get_by_role("button", name="Routable").click()
        expect(showcase_cards.first).to_contain_text("Routable")
        page.locator(".modelControls .searchLine input").fill("Alibaba Qwen3 32b")
        expect(showcase_cards.first).to_contain_text("Qwen3")
        showcase_cards.first.get_by_role("button", name=re.compile("Compare")).click()
        expect(page.locator(".modelCompareTray")).to_be_visible()
        expect(page.locator(".modelCompareTray")).to_contain_text("Model Compare")
        expect(page.locator(".modelCompareTray")).to_contain_text("Context")
        expect(page.locator(".modelCompareTray")).to_contain_text("Output")
        page.locator(".modelControls .searchLine input").fill("DeepSeek")
        expect(showcase_cards.first).to_contain_text("DeepSeek")
        showcase_cards.first.get_by_role("button", name=re.compile("Compare")).click()
        expect(page.locator(".modelCompareTray")).to_contain_text("2 selected")
        expect(page.locator(".modelCompareTray")).to_contain_text("DeepSeek")
        expect(page.locator(".modelCompareTray")).to_contain_text("Cost")
        expect(page.locator(".modelCompareActions").get_by_role("button", name="Copy Brief")).to_be_visible()
        page.locator(".modelCompareActions").get_by_role("button", name="Copy Brief").click()
        expect(page.locator(".modelCompareActions")).to_contain_text("Copied")
        copied_model_brief = page.evaluate("window.__mattsSmokeClipboard || ''")
        assert "# Model Compare Brief" in copied_model_brief and "DeepSeek" in copied_model_brief and "Training Nation" in copied_model_brief
        with page.expect_download() as model_compare_download:
            page.locator(".modelCompareActions").get_by_role("button", name="Download Brief").click()
        assert model_compare_download.value.suggested_filename.startswith("mde-llm-proxy-model-compare-brief-")
        assert model_compare_download.value.suggested_filename.endswith(".md")
        page.locator(".modelSort select").select_option("company")
        showcase_cards.first.locator(".mdlCardBody").click()
        expect(page.locator(".modelInspector")).to_contain_text("DeepSeek")
        stored_models = page.evaluate("window.sessionStorage.getItem('matts-v2-models-showcase')")
        assert stored_models and "DeepSeek" in stored_models and "compareIds" in stored_models and "company" in stored_models
        navigate_shell(page, "chat")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        open_advanced_tab(page, "models")
        expect(page.get_by_role("heading", name="Models")).to_be_visible()
        expect(page.locator(".modelControls .searchLine input")).to_have_value("DeepSeek")
        expect(page.locator(".modeSwitch").get_by_role("button", name="Routable")).to_have_class(re.compile("active"))
        expect(page.locator(".modelSort select")).to_have_value("company")
        expect(page.locator(".modelCompareTray")).to_contain_text("2 selected")
        expect(page.locator(".modelCompareTray")).to_contain_text("DeepSeek")
        expect(page.locator(".modelInspector")).to_contain_text("DeepSeek")
        page.locator(".modelCompareTray").get_by_role("button", name="Clear Compare").click()
        expect(page.locator(".modelCompareTray")).to_have_count(0)
        page.locator('[data-testid="model-showcase-card"]').first.locator(".mdlCardBody").click()
        expect(page.locator(".modelInspector")).to_contain_text("DeepSeek")
        expect(page.locator(".modelInspector")).to_contain_text("Context")
        expect(page.locator(".modelInspector")).to_contain_text("Output")
        expect(page.locator(".modelInspector")).to_contain_text("Cost")
        expect(page.locator(".modelArtworkGallery")).to_be_visible()
        expect(page.locator(".modelArtworkGallery")).to_contain_text("Artwork Preview")
        expect(page.locator(".modelArtworkGallery")).to_contain_text("Artwork Sources")
        expect(page.locator(".modelArtworkGallery")).to_contain_text("Bundled SVG")
        expect(page.locator(".modelArtworkGallery")).to_contain_text("Simple Icons")
        # V2-082 Q10: with a favorite pinned and no search filter, the grid collapses to
        # favorites behind an "All models" expander. Guarded: the chat block only stars a
        # model when more than one contact exists.
        model_favorites = json.loads(page.evaluate("window.localStorage.getItem('matts-v2-model-favorites') || '[]'"))
        if model_favorites:
            page.locator(".modelControls .searchLine input").fill("")
            grid_more = page.get_by_test_id("models-grid-more")
            expect(grid_more).to_be_visible()
            expect(grid_more).to_contain_text("All models")
            collapsed_grid_count = showcase_cards.count()
            grid_more.click()
            expect(grid_more).to_have_count(0)
            expanded_grid_count = showcase_cards.count()
            assert expanded_grid_count > collapsed_grid_count, (
                "expanding the favorites-collapsed grid did not reveal more model cards: %s -> %s"
                % (collapsed_grid_count, expanded_grid_count)
            )
        page.locator(".modelControls .searchLine input").fill("zzzz-no-model-match")
        expect(page.get_by_text("No models match this filter")).to_be_visible()

        expect(page.get_by_role("heading", name="Advanced")).to_be_visible()
        for label in ("Models", "Console", "Run", "Observe", "Operate"):
            expect(page.locator(".advancedTabs").get_by_role("button", name=label, exact=True)).to_be_visible()
        expect(page.locator(".advancedTabs").get_by_role("button", name="tui", exact=True)).to_have_count(0)
        expect(page.locator(".advancedTabs").get_by_role("button", name="overview", exact=True)).to_have_count(0)
        page.locator(".advancedTabs").get_by_role("button", name="Observe", exact=True).click()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Observe", exact=True)).to_have_class(re.compile("active"))
        assert page.evaluate("window.sessionStorage.getItem('matts-v2-advanced-tab')") == "observe"
        navigate_shell(page, "chat")
        expect(page.get_by_role("heading", name="Chat")).to_be_visible()
        page.evaluate("window.location.hash = '#advanced'")
        expect(page.get_by_role("heading", name="Advanced")).to_be_visible()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Observe", exact=True)).to_have_class(re.compile("active"))
        page.keyboard.press("Control+K")
        expect(page.get_by_role("heading", name="Switch Workspace")).to_be_visible()
        expect(page.locator(".quickSwitcherFooter")).to_contain_text("Saved State")
        expect(page.locator(".quickSwitcherFooter")).to_contain_text("workspace")
        expect(page.locator(".quickSwitcherFooter").get_by_role("button", name="Copy State")).to_be_enabled()
        expect(page.locator(".quickSwitcherFooter").get_by_role("button", name="Download State")).to_be_enabled()
        expect(page.locator(".quickSwitcherFooter").get_by_role("button", name="Reset Saved State")).to_be_enabled()
        page.locator(".quickSwitcherFooter").get_by_role("button", name="Copy State").click()
        expect(page.locator(".quickSwitcherFooter")).to_contain_text("State copied")
        copied_state = json.loads(page.evaluate("window.__mattsSmokeClipboard || '{}'"))
        assert copied_state["schema"] == "matts-v2-saved-workspace-state/v1"
        assert copied_state["active_workspace"] == "advanced"
        assert copied_state["saved_state_count"] >= 3
        assert "chat" in copied_state["recent_workspace_keys"]
        assert copied_state["restore_state"]["matts-v2-advanced-tab"] == "observe"
        assert "matts-v2-create-workspace" in copied_state["restore_state"]
        assert "smoke image prompt" in copied_state["restore_state"]["matts-v2-create-workspace"]
        assert "serverless inference news" not in copied_state["restore_state"]["matts-v2-create-workspace"]
        assert "researchResult" not in copied_state["restore_state"]["matts-v2-create-workspace"]
        assert "imageResult" in copied_state["restore_state"]["matts-v2-create-workspace"]
        workspace_state_path = Path(tempfile.gettempdir()) / "v2-workspace-state-smoke.json"
        workspace_state_path.write_text(json.dumps(copied_state), encoding="utf-8")
        with page.expect_download() as workspace_state_download:
            page.locator(".quickSwitcherFooter").get_by_role("button", name="Download State").click()
        assert workspace_state_download.value.suggested_filename.startswith("mde-llm-proxy-workspace-state-")
        assert workspace_state_download.value.suggested_filename.endswith(".json")
        page.locator(".quickSwitcherFooter").get_by_role("button", name="Reset Saved State").click()
        expect(page.locator(".quickSwitcher")).to_have_count(0)
        expect(page.locator(".advancedTabs").get_by_role("button", name="Models", exact=True)).to_have_class(re.compile("active"))
        assert page.evaluate(
            """
            [
              'matts-v2-chat-transcript',
              'matts-v2-code-workspace',
              'matts-v2-research-workspace',
              'matts-v2-create-workspace',
              'matts-v2-models-showcase',
              'matts-v2-advanced-tab'
            ].every((key) => window.sessionStorage.getItem(key) === null)
            """
        )
        page.keyboard.press("Control+K")
        expect(page.locator(".quickSwitcherFooter")).to_contain_text("No saved workspace state")
        expect(page.locator(".quickSwitcherFooter").get_by_role("button", name="Copy State")).to_be_disabled()
        expect(page.locator(".quickSwitcherFooter").get_by_role("button", name="Download State")).to_be_disabled()
        expect(page.locator(".quickSwitcherFooter").get_by_role("button", name="Import State")).to_be_enabled()
        expect(page.locator(".quickSwitcherFooter").get_by_role("button", name="Reset Saved State")).to_be_disabled()
        invalid_state_path = Path(tempfile.gettempdir()) / "v2-workspace-state-invalid.json"
        invalid_state_path.write_text(json.dumps({"schema": "wrong", "restore_state": {"matts-v2-advanced-tab": "observe"}}), encoding="utf-8")
        page.locator('[data-testid="workspace-state-import"]').set_input_files(str(invalid_state_path))
        expect(page.locator(".quickSwitcherFooter")).to_contain_text("Import failed")
        assert page.evaluate("window.sessionStorage.getItem('matts-v2-advanced-tab')") is None
        page.locator('[data-testid="workspace-state-import"]').set_input_files(str(workspace_state_path))
        expect(page.locator(".quickSwitcher")).to_have_count(0)
        expect(page.get_by_role("heading", name="Advanced")).to_be_visible()
        expect(page.locator(".advancedTabs").get_by_role("button", name="Observe", exact=True)).to_have_class(re.compile("active"))
        assert page.evaluate("window.location.hash") == "#advanced"
        restored_create = page.evaluate("window.sessionStorage.getItem('matts-v2-create-workspace')")
        assert restored_create and "smoke image prompt" in restored_create and "researchResult" not in restored_create and "imageResult" in restored_create
        restored_recents = page.evaluate("window.sessionStorage.getItem('matts-v2-quick-switcher-recents')")
        assert restored_recents and "chat" in restored_recents
        navigate_shell(page, "create")
        expect(page.get_by_role("heading", name="Create")).to_be_visible()
        expect(page.locator(".createHistoryCard")).to_have_count(1)
        expect(page.locator(".imageGalleryResult")).to_contain_text("smoke image prompt")
        open_advanced_workspace(page)
        page.keyboard.press("Control+K")
        expect(page.locator(".quickSwitcherRecents")).to_be_visible()
        expect(page.locator(".quickSwitcherRecents")).to_contain_text("Chat")
        expect(page.locator(".quickSwitcherSearch input")).to_be_focused()
        page.keyboard.press("End")
        expect(page.locator("#quick-switcher-results button[aria-selected='true']")).to_contain_text("Advanced")
        page.keyboard.press("Home")
        expect(page.locator("#quick-switcher-results button[aria-selected='true']")).to_contain_text("Chat")
        page.keyboard.press("ArrowDown")
        expect(page.locator("#quick-switcher-results button[aria-selected='true']")).to_contain_text("Code")
        page.keyboard.press("ArrowUp")
        expect(page.locator("#quick-switcher-results button[aria-selected='true']")).to_contain_text("Chat")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        expect(page.locator(".quickSwitcher")).to_have_count(0)
        expect(page.get_by_role("heading", name="Code")).to_be_visible()
        page.keyboard.press("Control+K")
        expect(page.locator(".quickSwitcherRecents")).to_contain_text("Advanced")
        page.keyboard.press("Escape")
        expect(page.locator(".quickSwitcher")).to_have_count(0)

        open_advanced_workspace(page)
        page.locator(".advancedTabs").get_by_role("button", name="Console", exact=True).click()
        # Console is now a System Operations dashboard; the tmux/terminal workflow lives in Code.
        expect(page.locator(".consoleHeader")).to_be_visible(timeout=45000)
        expect(page.get_by_test_id("console-operational-state")).to_be_visible()
        page.locator(".advancedTabs").get_by_role("button", name="Run", exact=True).click()
        expect(page.get_by_role("heading", name="Run")).to_be_visible(timeout=45000)
        expect(page.get_by_test_id("chat-run-panel")).to_be_visible()
        page.get_by_test_id("chat-run-prompt").fill("generated-client-error-smoke")
        with page.expect_response(lambda response: "/v2/run/chat" in response.url and response.status == 500):
            page.get_by_test_id("chat-run-send").click()
        expect(page.get_by_text("Generated client detail reached browser smoke", exact=True)).to_be_visible()
        expect(page.get_by_text("v2 request failed: 500")).to_have_count(0)
        assert generated_chat_errors, "generated run chat error route was not exercised"
        page.get_by_role("tab", name="Prompt Templates").click()
        page.get_by_test_id("template-name").fill("Smoke Template")
        page.get_by_test_id("template-body").fill("Answer {{goal}}")
        page.get_by_test_id("template-variables").fill("goal")
        with page.expect_response(lambda response: "/v2/run/prompt-templates" in response.url and response.request.method == "POST" and response.status == 200):
            page.get_by_test_id("template-save").click()
        expect(page.get_by_text("Smoke Template")).to_be_visible()
        smoke_template_row = page.get_by_role("row", name=re.compile(r"Smoke Template")).first
        expect(smoke_template_row).to_be_visible()
        dialog_messages = []
        page.on("dialog", lambda dialog: (dialog_messages.append(dialog.message), dialog.dismiss()))
        with page.expect_response(lambda response: "/v2/run/prompt-templates/" in response.url and "/versions" in response.url and response.status == 200):
            smoke_template_row.get_by_test_id("template-rollback").click()
        expect(page.get_by_test_id("template-rollback-status")).to_contain_text("No previous template version is available.")
        assert dialog_messages == []
        smoke_template_row.get_by_test_id("template-edit").click()
        page.get_by_test_id("template-body").fill("Answer {{goal}} carefully")
        with page.expect_response(lambda response: "/v2/run/prompt-templates" in response.url and response.request.method == "POST" and response.status == 200):
            page.get_by_test_id("template-save").click()
        smoke_template_row = page.get_by_role("row", name=re.compile(r"Smoke Template")).first
        expect(smoke_template_row).to_be_visible()
        with page.expect_response(lambda response: "/v2/run/prompt-templates/" in response.url and "/rollback" in response.url and response.status == 200):
            smoke_template_row.get_by_test_id("template-rollback").click()
        expect(page.get_by_test_id("template-rollback-status")).to_contain_text("Prompt template rolled back to version")
        assert_no_model_artwork_guard_events(artwork_events, "desktop V2")
        page.close()
        browser.close()
        mobile_browser = p.chromium.launch()
        try:
            run_mobile_whats_new_smoke(mobile_browser, base_url)
            run_mobile_advanced_smoke(mobile_browser, base_url)
            run_mobile_create_smoke(mobile_browser, base_url)
        finally:
            mobile_browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--required", action="store_true", help="fail instead of skipping when dependencies are unavailable")
    args = parser.parse_args(argv)

    try:
        import playwright  # noqa: F401
    except Exception as exc:
        message = "Playwright is not installed; skipping v2 browser smoke test."
        if args.required:
            raise SystemExit("%s Install with: python3 -m pip install playwright && python3 -m playwright install chromium" % message) from exc
        print(message)
        return 0

    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except Exception as exc:
        message = "FastAPI/uvicorn are not installed; skipping v2 browser smoke test."
        if args.required:
            raise SystemExit("%s Install with: python3 -m pip install -r requirements-v2.txt" % message) from exc
        print(message)
        return 0

    try:
        frontend_state = ensure_frontend()
    except Exception as exc:
        if args.required:
            raise
        print("React frontend is not buildable; skipping v2 browser smoke test: %s" % exc)
        return 0

    with tempfile.TemporaryDirectory() as tmpdir:
        docs = Path(tmpdir) / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "guide.md").write_text("Gateway routing uses traces for proof.\n", encoding="utf-8")
        (Path(tmpdir) / "traces.jsonl").write_text(
            '{"trace_id":"trace-smoke-replay","timestamp":1000.0,"requested_model":"deepseek-3.2","status":"ok","message_summary":{"message_count":1,"last_user_preview":"Replay smoke prompt","last_user_chars":120}}' + "\n",
            encoding="utf-8",
        )
        (Path(tmpdir) / "audit.jsonl").write_text(
            json.dumps(
                {
                    "ts": 9999999999.0,
                    "action": "audit.view",
                    "outcome": "denied",
                    "permission": "audit_view",
                    "status": 403,
                    "actor": {"id": "viewer", "roles": ["viewer"], "source": "smoke"},
                    "request": {
                        "path": "/api/audit",
                        "policy_decision": {
                            "domain": "rbac",
                            "action": "audit.view",
                            "allowed": False,
                            "reason": "missing_permission",
                            "matched_policy": {"permission": "audit_view"},
                            "inputs": {"roles": ["viewer"]},
                        },
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (Path(tmpdir) / "reviews.jsonl").write_text(
            json.dumps(
                {
                    "id": "review-smoke",
                    "schema_version": 1,
                    "created_at": 9999999998.0,
                    "updated_at": 9999999998.0,
                    "status": "open",
                    "severity": "high",
                    "reason": "eval_gate_blocked",
                    "title": "Review smoke item",
                    "source": {"type": "eval_gate"},
                    "evidence": {"decision": "blocked"},
                    "actor": {"id": "smoke"},
                    "assignee": "",
                    "notes": "",
                    "automatic": True,
                    "promotions": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (Path(tmpdir) / "automation-rules.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "rules": [
                        {
                            "id": "run-profile-change-eval",
                            "name": "Run Profile Change Eval",
                            "enabled": True,
                            "trigger": {"event": "run_profile.changed", "source": "run", "min_severity": "high", "field_equals": {"model": "model-a"}},
                            "actions": [{"type": "run_eval", "dataset_id": "smoke", "models": ["deepseek-3.2"]}],
                        },
                        {
                            "id": "scheduled-smoke-eval",
                            "name": "Scheduled Smoke Eval",
                            "enabled": True,
                            "trigger": {
                                "event": "eval.scheduled",
                                "source": "schedule",
                                "schedule": {"interval_seconds": 3600, "event": "eval.scheduled", "source": "schedule"},
                            },
                            "actions": [{"type": "run_eval", "dataset_id": "smoke", "models": ["deepseek-3.2"]}],
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        rollback_dir = Path(tmpdir) / "rollback-backups"
        rollback_payload = rollback_dir / "staging" / "payload"
        rollback_payload.mkdir(parents=True, exist_ok=True)
        rollback_target = Path(tmpdir) / "models.json"
        rollback_target.write_text('{"models":[]}', encoding="utf-8")
        (rollback_payload / "model_registry").write_text('{"models":[{"id":"rollback-smoke"}]}', encoding="utf-8")
        (rollback_dir / "staging" / "manifest.json").write_text(
            json.dumps(
                {
                    "created_at": 1002.0,
                    "include_secrets": False,
                    "items": [{"name": "model_registry", "path": str(rollback_target), "exists": True, "type": "file"}],
                }
            ),
            encoding="utf-8",
        )
        with tarfile.open(rollback_dir / "runtime-state-smoke.tar.gz", "w:gz") as tar:
            tar.add(rollback_dir / "staging" / "manifest.json", arcname="manifest.json")
            tar.add(rollback_payload, arcname="payload")
        evals_dir = Path(tmpdir) / "evals"
        eval_runs_dir = Path(tmpdir) / "eval-runs"
        evals_dir.mkdir(parents=True, exist_ok=True)
        eval_runs_dir.mkdir(parents=True, exist_ok=True)
        (evals_dir / "smoke.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "smoke",
                    "name": "Smoke",
                    "description": "V2 Observe smoke dataset.",
                    "examples": [{"id": "ex-001", "input": "Reply ok", "expected": "ok"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (eval_runs_dir / "eval_smoke_run.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "eval_smoke_run",
                    "created_at": 1001.0,
                    "dataset": {"id": "smoke", "name": "Smoke", "description": "V2 Observe smoke dataset.", "source": "smoke"},
                    "models": ["deepseek-3.2"],
                    "example_count": 1,
                    "summary": [{"model": "deepseek-3.2", "requests": 1, "failures": 0, "total_cost_usd": 0.0, "avg_latency_ms": 10, "pass_rate": 1.0}],
                    "results": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        port = free_port()
        base_url = "http://127.0.0.1:%d/" % port
        process = start_server(port, Path(tmpdir) / "run-workspace.sqlite3")
        try:
            wait_for_health(base_url)
            run_health_validate(base_url)
            run_browser_smoke(base_url)
            print("V2 browser smoke passed: %s" % base_url)
        finally:
            stop_server(process)
            cleanup_frontend(*frontend_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
