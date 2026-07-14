import importlib.util
import json
import os
import tarfile
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeStateScriptTests(unittest.TestCase):
    def test_backup_and_restore_moves_existing_files_aside(self):
        script = load_script("runtime-state.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            app = home / ".cache/matts-value-set/studio"
            app.mkdir(parents=True)
            model_file = root / "models.json"
            gateway_file = root / "gateway.json"
            v2_db = root / "v2-run.sqlite3"
            usage_file = home / ".cache/matts-value-set/usage.jsonl"
            budget_file = home / ".cache/matts-value-set/budgets.json"
            for path, text in [
                (model_file, '{"models":[{"id":"a","enabled":true}]}'),
                (gateway_file, '{"enabled":true}'),
                (v2_db, "sqlite-bytes"),
                (app / "dedicated-inference.json", '{"state":"active"}'),
                (app / "tmux-sessions.json", '{"sessions":[]}'),
                (app / "automation-rules.json", '{"rules":[]}'),
                (app / "reviews.jsonl", '{"id":"review-a"}\\n'),
                (usage_file, '{"cost":1}\\n'),
                (budget_file, '{"daily_usd":5}'),
            ]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            archive = root / "backup.tar.gz"
            env = {
                "HOME": str(home),
                "MATTS_MODEL_CONFIG_FILE": str(model_file),
                "MATTS_GATEWAY_POLICY_FILE": str(gateway_file),
                "MATTS_STUDIO_DIR": str(app),
                "MATTS_V2_RUN_DB": str(v2_db),
                "MATTS_VALUE_SET_COST_FILE": str(usage_file),
                "MATTS_VALUE_SET_BUDGET_FILE": str(budget_file),
            }
            with patch.dict(os.environ, env, clear=True), redirect_stdout(StringIO()):
                self.assertEqual(script.main(["backup", "--output", str(archive)]), 0)
            with tarfile.open(archive, "r:gz") as tar:
                manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
            item_names = {item["name"] for item in manifest["items"] if item.get("exists")}

            model_file.write_text('{"models":[]}', encoding="utf-8")
            dry_run_out = StringIO()
            with patch.dict(os.environ, env, clear=True), redirect_stdout(dry_run_out):
                self.assertEqual(script.main(["restore", str(archive), "--dry-run"]), 0)
            dry_run = json.loads(dry_run_out.getvalue())
            self.assertEqual(model_file.read_text(encoding="utf-8"), '{"models":[]}')
            with patch.dict(os.environ, env, clear=True), redirect_stdout(StringIO()):
                self.assertEqual(script.main(["restore", str(archive)]), 0)

            self.assertIn("v2_run_db", item_names)
            self.assertIn("automation_rules", item_names)
            self.assertTrue(dry_run["dry_run"])
            self.assertTrue(any(item["name"] == "model_registry" and item["will_move_existing_aside"] for item in dry_run["would_restore"]))
            self.assertIn('"id":"a"', model_file.read_text(encoding="utf-8"))
            self.assertTrue(list(root.glob("models.json.pre-restore-*")))


class HealthValidateScriptTests(unittest.TestCase):
    class Response:
        def __init__(self, status, body):
            self.status = status
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body.encode("utf-8")

    def args(self, **overrides):
        defaults = {
            "legacy_console_url": "",
            "v2_url": "http://v2",
            "proxy_url": "http://proxy",
            "timeout": 1.0,
            "proxy_only": False,
            "v2_only": False,
            "no_v2": False,
            "allow_degraded_console": False,
        }
        defaults.update(overrides)
        return types.SimpleNamespace(**defaults)

    def fake_urlopen(self, bodies, calls):
        def open_url(url, timeout):
            calls.append((url, timeout))
            return self.Response(200, bodies[url])

        return open_url

    def healthy_bodies(self):
        return {
            "http://v2/v2/health": '{"status":"ok","version":"2.0.0"}',
            "http://v2/": '<!doctype html><div id="root"><section data-testid="v2-boot-fallback">Starting</section></div><script type="module" src="/assets/index.js"></script>',
            "http://proxy/v1/claude-do/capabilities": '{"provider":"test"}',
            "http://proxy/v1/models": '{"data":[]}',
        }

    def test_default_health_validation_includes_v2_api_and_react_shell(self):
        script = load_script("health-validate.py")
        calls = []
        with patch.object(script, "urlopen", self.fake_urlopen(self.healthy_bodies(), calls)):
            result = script.validate(self.args())

        self.assertTrue(result["ok"])
        self.assertIn("v2_health", result["checks"])
        self.assertIn("v2_frontend", result["checks"])
        self.assertIn(("http://v2/v2/health", 1.0), calls)
        self.assertIn(("http://v2/", 1.0), calls)

    def test_health_validation_fails_when_v2_frontend_shell_is_missing(self):
        script = load_script("health-validate.py")
        bodies = self.healthy_bodies()
        bodies["http://v2/"] = "<!doctype html><main>not the React app</main>"
        with patch.object(script, "urlopen", self.fake_urlopen(bodies, [])):
            result = script.validate(self.args())

        self.assertFalse(result["ok"])
        frontend = result["checks"]["v2_frontend"]
        self.assertFalse(frontend["ok"])
        self.assertIn('id="root"', frontend["missing_fragments"])
        self.assertIn("<script", frontend["missing_fragments"])

    def test_health_validation_fails_when_v2_boot_fallback_is_missing(self):
        script = load_script("health-validate.py")
        bodies = self.healthy_bodies()
        bodies["http://v2/"] = '<!doctype html><div id="root"></div><script type="module" src="/assets/index.js"></script>'
        with patch.object(script, "urlopen", self.fake_urlopen(bodies, [])):
            result = script.validate(self.args())

        self.assertFalse(result["ok"])
        frontend = result["checks"]["v2_frontend"]
        self.assertFalse(frontend["ok"])
        self.assertIn('data-testid="v2-boot-fallback"', frontend["missing_fragments"])

    def test_proxy_only_skips_v2_checks(self):
        script = load_script("health-validate.py")
        calls = []
        bodies = {
            "http://proxy/v1/claude-do/capabilities": '{"provider":"test"}',
            "http://proxy/v1/models": '{"data":[]}',
        }
        with patch.object(script, "urlopen", self.fake_urlopen(bodies, calls)):
            result = script.validate(self.args(proxy_only=True))

        self.assertTrue(result["ok"])
        self.assertNotIn("v2_health", result["checks"])
        self.assertEqual([url for url, _timeout in calls], list(bodies.keys()))

    def test_no_v2_skips_v2_but_keeps_legacy_console_and_proxy_checks(self):
        script = load_script("health-validate.py")
        calls = []
        bodies = {
            "http://proxy/v1/claude-do/capabilities": '{"provider":"test"}',
            "http://proxy/v1/models": '{"data":[]}',
        }
        with patch.object(script, "urlopen", self.fake_urlopen(bodies, calls)):
            result = script.validate(self.args(no_v2=True))

        self.assertTrue(result["ok"])
        self.assertNotIn("v2_health", result["checks"])
        self.assertNotIn("legacy_console_health", result["checks"])
        self.assertIn("proxy_models", result["checks"])

    def test_legacy_console_validation_is_explicit(self):
        script = load_script("health-validate.py")
        calls = []
        bodies = dict(self.healthy_bodies())
        bodies.update(
            {
                "http://legacy/health": '{"status":"ok"}',
                "http://legacy/ready": '{"status":"ok"}',
                "http://legacy/version": '{"version":"1"}',
            }
        )
        with patch.object(script, "urlopen", self.fake_urlopen(bodies, calls)):
            result = script.validate(self.args(legacy_console_url="http://legacy"))

        self.assertTrue(result["ok"])
        self.assertIn("legacy_console_health", result["checks"])
        self.assertIn(("http://legacy/health", 1.0), calls)


class FrontendProductionAuditScriptTests(unittest.TestCase):
    def test_clean_report_passes_with_dependency_count(self):
        script = load_script("check-v2-frontend-audit.py")
        report = {
            "vulnerabilities": {},
            "metadata": {
                "vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 0, "critical": 0, "total": 0},
                "dependencies": {"prod": 81, "dev": 79, "total": 160},
            },
        }
        ok, message = script.check_report(report)
        self.assertTrue(ok)
        self.assertIn("0 production vulnerabilities", message)
        self.assertIn("81 production dependencies", message)

    def test_vulnerable_report_fails_with_summary(self):
        script = load_script("check-v2-frontend-audit.py")
        report = {
            "vulnerabilities": {
                "example": {
                    "severity": "high",
                    "via": [{"title": "example package reads secrets"}],
                }
            },
            "metadata": {"vulnerabilities": {"total": 1}},
        }
        ok, message = script.check_report(report)
        self.assertFalse(ok)
        self.assertIn("1 production vulnerability", message)
        self.assertIn("example [high]", message)
        self.assertIn("reads secrets", message)

    def test_main_from_file_returns_failure_for_vulnerabilities(self):
        script = load_script("check-v2-frontend-audit.py")
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "audit.json"
            report.write_text(
                json.dumps({"vulnerabilities": {"bad": {"severity": "moderate"}}, "metadata": {"vulnerabilities": {"total": 1}}}),
                encoding="utf-8",
            )
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(script.main(["--from-file", str(report)]), 1)
            self.assertIn("bad [moderate]", stderr.getvalue())


class V2FrontendBundleCheckScriptTests(unittest.TestCase):
    def run_check(self, html, entry_text="", include_boot_fallback=True):
        script = load_script("check-v2-frontend-bundles.py")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            assets = dist / "assets"
            assets.mkdir(parents=True)
            (assets / "index-shell.js").write_text(entry_text, encoding="utf-8")
            if include_boot_fallback:
                html = '<div id="root"><section data-testid="v2-boot-fallback">Starting</section></div>' + html
            (dist / "index.html").write_text(html, encoding="utf-8")
            stdout = StringIO()
            stderr = StringIO()
            with (
                patch.object(script, "DIST", dist),
                patch.object(script, "INDEX", dist / "index.html"),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                status = script.main()
        return status, stdout.getvalue(), stderr.getvalue()

    def test_allows_shell_script_and_stylesheet_with_any_attribute_order(self):
        status, stdout, stderr = self.run_check(
            """
            <script crossorigin src="/assets/index-shell.js" type="Module"></script>
            <link href="/assets/index-shell.css" rel="preload stylesheet">
            """
        )

        self.assertEqual(status, 0, stderr)
        self.assertIn("V2 frontend bundle check passed", stdout)

    def test_rejects_missing_static_boot_fallback(self):
        status, _, stderr = self.run_check(
            '<div id="root"></div><script type="module" src="/assets/index-shell.js"></script>',
            include_boot_fallback=False,
        )

        self.assertEqual(status, 1)
        self.assertIn("index.html is missing the static v2 boot fallback", stderr)

    def test_rejects_first_load_advanced_stylesheet(self):
        status, _, stderr = self.run_check(
            """
            <script type="module" src="/assets/index-shell.js"></script>
            <link rel="stylesheet" href="/assets/TuiTerminal-abc123.css">
            """
        )

        self.assertEqual(status, 1)
        self.assertIn("index.html eagerly references TuiTerminal- asset", stderr)

    def test_rejects_first_load_advanced_stylesheet_with_tokenized_rel(self):
        status, _, stderr = self.run_check(
            """
            <script type="module" src="/assets/index-shell.js"></script>
            <link rel="preload StyleSheet" href="/assets/TuiTerminal-abc123.css">
            """
        )

        self.assertEqual(status, 1)
        self.assertIn("index.html eagerly references TuiTerminal- asset", stderr)

    def test_rejects_first_load_advanced_modulepreload(self):
        status, _, stderr = self.run_check(
            """
            <script type="module" src="/assets/index-shell.js"></script>
            <link href="/assets/RunPage-abc123.js" rel="ModulePreload preload">
            """
        )

        self.assertEqual(status, 1)
        self.assertIn("index.html eagerly references RunPage- asset", stderr)

    def test_rejects_static_import_of_lazy_chunk_from_entry(self):
        status, _, stderr = self.run_check(
            '<script type="module" src="/assets/index-shell.js"></script>',
            entry_text='import ConsolePage from "./ConsolePage-abc123.js";',
        )

        self.assertEqual(status, 1)
        self.assertIn("entry chunk statically imports ConsolePage-", stderr)


class V2BrowserSmokeFrontendInstallTests(unittest.TestCase):
    def test_v2_browser_smoke_runs_health_validate_against_ephemeral_server(self):
        script = load_script("v2-browser-smoke.py")
        run = Mock()
        with patch.object(script.subprocess, "run", run):
            script.run_health_validate("http://127.0.0.1:12345/")

        self.assertEqual(run.call_args.args[0][1:], [str(ROOT / "scripts" / "health-validate.py"), "--v2-only", "--v2-url", "http://127.0.0.1:12345"])
        self.assertEqual(run.call_args.kwargs["cwd"], str(ROOT))
        self.assertTrue(run.call_args.kwargs["check"])

    def test_ensure_frontend_uses_npm_ci_when_lockfile_exists(self):
        script = load_script("v2-browser-smoke.py")
        with tempfile.TemporaryDirectory() as tmp:
            frontend = Path(tmp) / "frontend"
            frontend.mkdir()
            lockfile = frontend / "package-lock.json"
            lockfile.write_text("{}", encoding="utf-8")
            run = Mock()
            with (
                patch.object(script, "FRONTEND_DIR", frontend),
                patch.object(script, "FRONTEND_DIST", frontend / "dist"),
                patch.object(script, "FRONTEND_LOCK", lockfile),
                patch.object(script, "TS_BUILD_INFO", frontend / "tsconfig.tsbuildinfo"),
                patch.object(script, "command_available", return_value=True),
                patch.object(script.subprocess, "run", run),
            ):
                self.assertEqual(script.ensure_frontend(), (False, False, False))

        self.assertEqual([call.args[0] for call in run.call_args_list], [["npm", "ci", "--no-audit"], ["npm", "run", "build"]])
        self.assertEqual([call.kwargs["cwd"] for call in run.call_args_list], [str(frontend), str(frontend)])

    def test_ensure_frontend_falls_back_to_npm_install_without_lockfile(self):
        script = load_script("v2-browser-smoke.py")
        with tempfile.TemporaryDirectory() as tmp:
            frontend = Path(tmp) / "frontend"
            frontend.mkdir()
            run = Mock()
            with (
                patch.object(script, "FRONTEND_DIR", frontend),
                patch.object(script, "FRONTEND_DIST", frontend / "dist"),
                patch.object(script, "FRONTEND_LOCK", frontend / "package-lock.json"),
                patch.object(script, "TS_BUILD_INFO", frontend / "tsconfig.tsbuildinfo"),
                patch.object(script, "command_available", return_value=True),
                patch.object(script.subprocess, "run", run),
            ):
                self.assertEqual(script.ensure_frontend(), (False, False, False))

        self.assertEqual([call.args[0] for call in run.call_args_list], [["npm", "install", "--no-audit"], ["npm", "run", "build"]])


class ReleaseCheckScriptTests(unittest.TestCase):
    def test_release_gate_prefers_lockfile_reproducible_frontend_install(self):
        script = (ROOT / "scripts" / "release-check.sh").read_text(encoding="utf-8")

        self.assertIn("[[ -f frontend/package-lock.json ]]", script)
        self.assertIn("npm ci --prefix frontend --no-audit", script)
        self.assertIn("npm install --prefix frontend --no-audit", script)

    def test_release_gate_is_v2_browser_smoke_only(self):
        script = (ROOT / "scripts" / "release-check.sh").read_text(encoding="utf-8")

        self.assertIn("python3 scripts/v2-browser-smoke.py --required", script)
        self.assertIn("python3 scripts/v2-browser-smoke.py", script)
        self.assertNotIn("scripts/browser-smoke.py", script)

    def test_release_gate_isolates_runtime_state(self):
        script = (ROOT / "scripts" / "release-check.sh").read_text(encoding="utf-8")

        self.assertIn("MATTS_RELEASE_CHECK_RUNTIME_DIR", script)
        self.assertIn("export MATTS_STUDIO_DIR=\"$RELEASE_RUNTIME_ROOT/studio\"", script)
        self.assertIn("export MATTS_TRACE_FILE=\"$MATTS_STUDIO_DIR/traces.jsonl\"", script)
        self.assertIn("export MATTS_TMUX_SESSION_REGISTRY_FILE=\"$MATTS_STUDIO_DIR/tmux-sessions.json\"", script)
        self.assertIn("export MATTS_MODEL_ACCESS_STATE_FILE=\"$MATTS_STUDIO_DIR/model-access-state.json\"", script)
        self.assertIn("release_check_seed", script)
        self.assertIn("export MATTS_VALUE_SET_BUDGET_FILE=\"$RELEASE_RUNTIME_ROOT/budgets.json\"", script)
        self.assertIn("export MATTS_OPERATIONAL_DB=\"$MATTS_STUDIO_DIR/operational.sqlite3\"", script)
        self.assertIn("export MATTS_V2_RUN_DB=\"$MATTS_OPERATIONAL_DB\"", script)
        self.assertIn("export MATTS_V2_RESEARCH_DB=\"$MATTS_OPERATIONAL_DB\"", script)
        self.assertIn("python3 scripts/check-v2-brand-art.py", script)

    def test_release_gate_coverage_floor_is_configurable(self):
        script = (ROOT / "scripts" / "release-check.sh").read_text(encoding="utf-8")

        self.assertIn('python3 scripts/coverage-report.py --fail-under "${MATTS_COVERAGE_FLOOR:-50}"', script)

    def test_release_gate_cleans_release_runtime_proxy_processes(self):
        script = (ROOT / "scripts" / "release-check.sh").read_text(encoding="utf-8")

        self.assertIn("release_check_proxy_pids()", script)
        self.assertIn("cleanup_release_proxy_processes()", script)
        self.assertIn("trap release_check_cleanup EXIT", script)
        self.assertIn("cleanup_release_proxy_processes", script)
        self.assertIn("--cost-file ${RELEASE_RUNTIME_ROOT}/", script)
        self.assertIn("--budget-file ${RELEASE_RUNTIME_ROOT}/", script)
        self.assertIn("--log-file ${RELEASE_RUNTIME_ROOT}/", script)
        self.assertIn("--trace-file ${RELEASE_RUNTIME_ROOT}/", script)
        self.assertNotIn("trap 'rm -f \"$tmp_js\"' EXIT", script)

    def test_release_gate_checks_generated_v2_openapi_drift(self):
        script = (ROOT / "scripts" / "release-check.sh").read_text(encoding="utf-8")

        self.assertIn("V2 OpenAPI generated artifact drift", script)
        self.assertIn("python3 scripts/generate-v2-openapi.py --check", script)

    def test_release_gate_required_mode_fails_when_frontend_tooling_is_missing(self):
        script = (ROOT / "scripts" / "release-check.sh").read_text(encoding="utf-8")

        self.assertIn("React frontend build requires npm when MATTS_BROWSER_SMOKE_REQUIRED=1", script)
        self.assertIn("React frontend build skipped: npm is not installed", script)


if __name__ == "__main__":
    unittest.main()
