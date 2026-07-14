import json
import runpy
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V2OpenApiGenerationTests(unittest.TestCase):
    def generator(self):
        return runpy.run_path(str(ROOT / "scripts" / "generate-v2-openapi.py"))

    def test_generated_openapi_and_client_include_core_routes(self):
        openapi_path = ROOT / "frontend" / "src" / "api" / "generated" / "openapi.json"
        client_path = ROOT / "frontend" / "src" / "api" / "generated" / "v2Client.ts"

        self.assertTrue(openapi_path.exists())
        self.assertTrue(client_path.exists())
        openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
        from backend.v2.app import app

        self.assertEqual(openapi, json.loads(json.dumps(app.openapi(), sort_keys=True)))
        paths = openapi.get("paths") or {}
        self.assertIn("/v2/me/capabilities", paths)
        self.assertIn("/v2/run", paths)
        self.assertIn("/v2/run/branches", paths)
        self.assertIn("/v2/run/rag", paths)
        self.assertIn("/v2/run/rag/config", paths)
        self.assertIn("/v2/run/rag/index", paths)
        self.assertIn("/v2/run/rag/search", paths)
        self.assertIn("/v2/run/replays", paths)
        self.assertIn("/v2/run/replay/snapshot", paths)
        self.assertIn("/v2/run/replay", paths)
        self.assertIn("/v2/run/workspace-bundles", paths)
        self.assertIn("/v2/run/workspace-bundles/export", paths)
        self.assertIn("/v2/run/workspace-bundles/preview", paths)
        self.assertIn("/v2/run/workspace-bundles/import", paths)
        self.assertIn("/v2/run/context-window", paths)
        self.assertIn("/v2/run/chat", paths)
        self.assertIn("/v2/run/prompt-templates", paths)
        self.assertIn("/v2/run/prompt-templates/preview", paths)
        self.assertIn("/v2/run/prompt-templates/{template_id}/rollback", paths)
        self.assertIn("/v2/run/prompt-templates/{template_id}/versions", paths)
        self.assertIn("/v2/run/eval-gates", paths)
        self.assertIn("/v2/run/eval-gates/preview", paths)
        self.assertIn("/v2/research", paths)
        self.assertIn("/v2/research/engines", paths)
        self.assertIn("/v2/research/search", paths)
        self.assertIn("/v2/run/profiles", paths)
        self.assertIn("/v2/run/profiles/{profile_id}/activate", paths)
        self.assertIn("/v2/run/profiles/{profile_id}/rollback", paths)
        self.assertIn("/v2/run/profiles/{profile_id}/versions", paths)
        self.assertIn("/v2/run/records", paths)
        self.assertIn("/v2/run/session-snapshots", paths)
        self.assertIn("/v2/console/overview", paths)
        self.assertIn("/v2/console/commands", paths)
        self.assertIn("/v2/console/commands/dispatch", paths)
        self.assertIn("/v2/console/code-sessions/defaults", paths)
        self.assertIn("/v2/console/code-sessions/start", paths)
        self.assertIn("/v2/console/code-sessions/permissions", paths)
        self.assertIn("/v2/console/code-sessions/capture", paths)
        self.assertIn("/v2/console/code-sessions/send", paths)
        self.assertIn("/v2/console/code-sessions/stop", paths)
        self.assertIn("/v2/console/tmux", paths)
        self.assertIn("/v2/console/tmux/start", paths)
        self.assertIn("/v2/console/tmux/capture", paths)
        self.assertIn("/v2/console/tmux/send", paths)
        self.assertIn("/v2/console/tmux/key", paths)
        self.assertIn("/v2/console/tmux/rename", paths)
        self.assertIn("/v2/console/tmux/stop", paths)
        self.assertIn("/v2/console/tui/status", paths)
        self.assertIn("/v2/irc", paths)
        self.assertIn("/v2/irc/config", paths)
        self.assertIn("/v2/irc/start", paths)
        self.assertIn("/v2/irc/stop", paths)
        self.assertIn("/v2/irc/restart", paths)
        self.assertIn("/v2/startup", paths)
        self.assertIn("/v2/startup/config", paths)
        self.assertIn("/v2/startup/services/{service_id}/{action}", paths)
        self.assertIn("/v2/observe", paths)
        self.assertIn("/v2/observe/traces", paths)
        self.assertIn("/v2/observe/audit", paths)
        self.assertIn("/v2/observe/evals", paths)
        self.assertIn("/v2/observe/telemetry", paths)
        self.assertIn("/v2/observe/reporting-export", paths)
        self.assertIn("/v2/observe/decisions/explain", paths)
        self.assertIn("/v2/operate", paths)
        self.assertIn("/v2/operate/ci-triage/preview", paths)
        self.assertIn("/v2/operate/ci-triage/launch", paths)
        self.assertIn("/v2/operate/repository-context/preview", paths)
        self.assertIn("/v2/operate/repository-context/import", paths)
        self.assertIn("/v2/operate/release/report", paths)
        self.assertIn("/v2/operate/config-drift/baseline", paths)
        self.assertIn("/v2/operate/config-drift/acknowledge", paths)
        self.assertIn("/v2/operate/rollback/preview", paths)
        self.assertIn("/v2/operate/rollback/apply", paths)
        self.assertIn("/v2/operate/reviews/update", paths)
        self.assertIn("/v2/operate/reviews/promote", paths)
        self.assertIn("/v2/operate/evals/datasets", paths)
        self.assertIn("/v2/operate/evals/datasets/build", paths)
        self.assertIn("/v2/operate/evals/run", paths)
        self.assertIn("/v2/operate/automation/rules", paths)
        self.assertIn("/v2/operate/automation/test", paths)
        self.assertIn("/v2/operate/automation/run", paths)
        self.assertIn("/v2/operate/automation/schedules/run-due", paths)
        self.assertIn("/v2/operate/model-deprecations/preview", paths)
        self.assertIn("/v2/operate/model-deprecations/apply", paths)
        self.assertIn("/v2/operate/model-deprecations/rollback", paths)
        self.assertIn("/v2/cost-control", paths)
        self.assertIn("/v2/cost-control/thresholds", paths)
        self.assertIn("/v2/cost-control/override", paths)

        client = client_path.read_text(encoding="utf-8")
        generator = self.generator()
        self.assertEqual(client, generator["CLIENT_SOURCE"])
        self.assertIn("import { responseJsonOrThrow } from '../errors';", client)
        self.assertIn("return responseJsonOrThrow<T>(response);", client)
        self.assertNotIn("function readResponsePayload", client)
        self.assertNotIn("function errorMessageFromPayload", client)
        self.assertIn("getMeCapabilities", client)
        self.assertIn("getRunWorkspace", client)
        self.assertIn("getLocalRag", client)
        self.assertIn("saveLocalRagConfig", client)
        self.assertIn("indexLocalRag", client)
        self.assertIn("searchLocalRag", client)
        self.assertIn("listReplays", client)
        self.assertIn("snapshotReplay", client)
        self.assertIn("runReplay", client)
        self.assertIn("listWorkspaceBundles", client)
        self.assertIn("exportWorkspaceBundle", client)
        self.assertIn("previewWorkspaceBundleImport", client)
        self.assertIn("importWorkspaceBundle", client)
        self.assertIn("inspectContextWindow", client)
        self.assertIn("runChat", client)
        self.assertIn("getIrcBridge", client)
        self.assertIn("updateIrcBridgeConfig", client)
        self.assertIn("getStartup", client)
        self.assertIn("runStartupServiceAction", client)
        self.assertIn("saveConversationBranch", client)
        self.assertIn("savePromptTemplate", client)
        self.assertIn("previewPromptTemplate", client)
        self.assertIn("listPromptTemplateVersions", client)
        self.assertIn("rollbackPromptTemplate", client)
        self.assertIn("previewEvalGate", client)
        self.assertIn("listEvalGateRecords", client)
        self.assertIn("saveRunProfile", client)
        self.assertIn("activateRunProfile", client)
        self.assertIn("rollbackRunProfile", client)
        self.assertIn("listRunProfileVersions", client)
        self.assertIn("saveRunRecord", client)
        self.assertIn("saveSessionSnapshot", client)
        self.assertIn("getConsoleOverview", client)
        self.assertIn("getConsoleCommands", client)
        self.assertIn("dispatchConsoleCommand", client)
        self.assertIn("startCodeSession", client)
        self.assertIn("previewCodeSessionPermissions", client)
        self.assertIn("captureCodeSession", client)
        self.assertIn("sendCodeSessionInput", client)
        self.assertIn("stopCodeSession", client)
        self.assertIn("getTmuxWorkspace", client)
        self.assertIn("startTmuxSession", client)
        self.assertIn("captureTmuxSession", client)
        self.assertIn("sendTmuxText", client)
        self.assertIn("sendTmuxKey", client)
        self.assertIn("renameTmuxSession", client)
        self.assertIn("stopTmuxSession", client)
        self.assertIn("acquireConsoleTuiControl", client)
        self.assertIn("getObserve", client)
        self.assertIn("getObserveTraces", client)
        self.assertIn("searchObserveAudit", client)
        self.assertIn("getObserveEvals", client)
        self.assertIn("getObserveTelemetry", client)
        self.assertIn("exportObserveReporting", client)
        self.assertIn("explainObserveDecision", client)
        self.assertIn("getOperate", client)
        self.assertIn("getCostControl", client)
        self.assertIn("updateCostControlThresholds", client)
        self.assertIn("overrideCostControl", client)
        self.assertIn("previewOperateCiTriage", client)
        self.assertIn("launchOperateCiTriage", client)
        self.assertIn("previewOperateRepositoryContext", client)
        self.assertIn("importOperateRepositoryContext", client)
        self.assertIn("writeOperateReleaseReport", client)
        self.assertIn("markOperateConfigDriftBaseline", client)
        self.assertIn("acknowledgeOperateConfigDrift", client)
        self.assertIn("previewOperateRollback", client)
        self.assertIn("applyOperateRollback", client)
        self.assertIn("updateOperateReview", client)
        self.assertIn("promoteOperateReview", client)
        self.assertIn("saveOperateEvalDataset", client)
        self.assertIn("buildOperateEvalDataset", client)
        self.assertIn("runOperateEval", client)
        self.assertIn("saveOperateAutomationRules", client)
        self.assertIn("testOperateAutomation", client)
        self.assertIn("runOperateAutomation", client)
        self.assertIn("runDueOperateAutomationSchedules", client)
        self.assertIn("previewOperateModelDeprecation", client)
        self.assertIn("applyOperateModelDeprecation", client)
        self.assertIn("rollbackOperateModelDeprecation", client)

    def test_check_artifacts_passes_without_rewriting_current_files(self):
        generator = self.generator()
        artifacts = {"openapi": '{"paths": {}}\n', "client": "// client\n"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            openapi_path = root / "openapi.json"
            client_path = root / "v2Client.ts"
            with redirect_stdout(StringIO()):
                generator["write_artifacts"](artifacts, openapi_path=openapi_path, client_path=client_path)
            before = {openapi_path: openapi_path.read_text(encoding="utf-8"), client_path: client_path.read_text(encoding="utf-8")}
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = generator["check_artifacts"](artifacts, openapi_path=openapi_path, client_path=client_path)

            self.assertEqual(status, 0)
            self.assertIn("current", stdout.getvalue())
            self.assertEqual(before[openapi_path], openapi_path.read_text(encoding="utf-8"))
            self.assertEqual(before[client_path], client_path.read_text(encoding="utf-8"))

    def test_check_artifacts_fails_stale_openapi_without_rewriting(self):
        generator = self.generator()
        artifacts = {"openapi": '{"paths": {"/v2/health": {}}}\n', "client": "// client\n"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            openapi_path = root / "openapi.json"
            client_path = root / "v2Client.ts"
            openapi_path.write_text('{"paths": {}}\n', encoding="utf-8")
            client_path.write_text(artifacts["client"], encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                status = generator["check_artifacts"](artifacts, openapi_path=openapi_path, client_path=client_path)

            self.assertEqual(status, 1)
            self.assertIn("OpenAPI document is stale", stderr.getvalue())
            self.assertIn("run python3 scripts/generate-v2-openapi.py", stderr.getvalue())
            self.assertEqual('{"paths": {}}\n', openapi_path.read_text(encoding="utf-8"))

    def test_check_artifacts_fails_stale_client_without_rewriting(self):
        generator = self.generator()
        artifacts = {"openapi": '{"paths": {}}\n', "client": "// current client\n"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            openapi_path = root / "openapi.json"
            client_path = root / "v2Client.ts"
            openapi_path.write_text(artifacts["openapi"], encoding="utf-8")
            client_path.write_text("// stale client\n", encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                status = generator["check_artifacts"](artifacts, openapi_path=openapi_path, client_path=client_path)

            self.assertEqual(status, 1)
            self.assertIn("TypeScript client is stale", stderr.getvalue())
            self.assertEqual("// stale client\n", client_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
