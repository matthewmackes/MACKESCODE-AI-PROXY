import json
import tempfile
import unittest
from pathlib import Path

from backend.v2.services.run_store import RunStore
from src.console.services.workspace_bundles import WorkspaceBundleService


class WorkspaceBundleServiceTests(unittest.TestCase):
    def service(self, root, audits=None, clock=None):
        root = Path(root)
        audits = audits if audits is not None else []
        store = RunStore(root / "run.sqlite3", clock=clock or (lambda: 1000.0))
        return WorkspaceBundleService(
            bundles_dir=lambda: root / "bundles",
            model_registry_file=lambda: root / "models.json",
            gateway_policy_file=lambda: root / "gateway.json",
            evals_dir=lambda: root / "evals",
            comparison_reports_dir=lambda: root / "comparison-reports",
            release_reports_dir=lambda: root / "release-reports",
            run_store=store,
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            clock=clock or (lambda: 1000.0),
            app_version="test",
        ), store, audits

    def seed_files(self, root):
        root = Path(root)
        (root / "models.json").write_text(json.dumps([{"id": "model-a", "api_key": "secret"}]), encoding="utf-8")
        (root / "gateway.json").write_text(json.dumps({"routes": {"chat": "model-a"}}), encoding="utf-8")
        (root / "evals").mkdir()
        (root / "evals" / "smoke.json").write_text(json.dumps({"schema_version": 1, "id": "smoke", "examples": [{"input": "hi"}]}), encoding="utf-8")
        (root / "comparison-reports").mkdir()
        (root / "comparison-reports" / "report-a.json").write_text(json.dumps({"id": "report-a", "prompt": "token=abc123456789"}), encoding="utf-8")
        (root / "release-reports").mkdir()
        (root / "release-reports" / "release-candidate-a.json").write_text(json.dumps({"label": "a", "ready": True}), encoding="utf-8")

    def test_export_creates_manifest_checksums_and_redacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.seed_files(tmp)
            service, store, audits = self.service(tmp)
            store.save_prompt_template({"id": "template-a", "name": "Template", "body": "Hello {{name}}", "owner_notes": "Bearer abcdefghijklmnop"})
            store.save_run_profile({"id": "profile-a", "name": "Profile", "template_id": "template-a", "model": "model-a"})
            result = service.export_bundle({"sections": ["model_registry", "comparison_reports", "prompt_templates", "run_profiles"]}, actor={"id": "owner"})
            bundle = result["bundle"]

        self.assertEqual(bundle["manifest"]["schema_version"], 1)
        self.assertIn("model_registry", bundle["manifest"]["checksums"])
        self.assertTrue(bundle["manifest"]["redaction"]["contains_sensitive"])
        self.assertEqual(bundle["sections"]["model_registry"]["models"][0]["api_key"], "[redacted]")
        self.assertNotIn("token=abc123456789", json.dumps(bundle))
        self.assertEqual(audits[0][0][0], "workspace_bundle.export")

    def test_preview_detects_conflict_missing_dependency_and_secret_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.seed_files(tmp)
            service, _, _ = self.service(tmp)
            bundle = {
                "manifest": {"schema_version": 1, "id": "bad", "sections": ["eval_datasets", "run_profiles"], "checksums": {}},
                "sections": {
                    "eval_datasets": [{"schema_version": 1, "id": "smoke", "examples": [{"input": "hi"}]}],
                    "run_profiles": [{"id": "profile-b", "name": "Profile", "template_id": "missing", "authorization": "Bearer abcdefghijklmnop"}],
                },
            }
            preview = service.preview_import(bundle)

        codes = {issue["code"] for issue in preview["issues"]}
        self.assertIn("conflict", codes)
        self.assertIn("dependency", codes)
        self.assertIn("secret_risk", codes)
        self.assertTrue(preview["blocking"])

    def test_import_dry_run_and_selective_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            service, store, audits = self.service(tmp)
            store.save_prompt_template({"id": "template-a", "name": "Template", "body": "Body"})
            bundle = {
                "manifest": {"schema_version": 1, "id": "good", "sections": ["eval_datasets", "prompt_templates", "run_profiles"], "checksums": {}},
                "sections": {
                    "eval_datasets": [{"schema_version": 1, "id": "new-dataset", "examples": [{"input": "hello"}]}],
                    "prompt_templates": [{"id": "template-b", "name": "Template B", "body": "Body B"}],
                    "run_profiles": [{"id": "profile-b", "name": "Profile B", "template_id": "template-b", "model": "model-a"}],
                },
            }
            bundle["manifest"]["checksums"] = {section: service.checksum(bundle["sections"][section]) for section in bundle["manifest"]["sections"]}
            dry = service.import_bundle({**bundle, "dry_run": True})
            applied = service.import_bundle({**bundle, "dry_run": False, "selected_sections": ["eval_datasets", "prompt_templates", "run_profiles"]}, actor={"id": "owner"})

            self.assertTrue(dry["dry_run"])
            self.assertFalse(applied["dry_run"])
            self.assertIn("eval_datasets", applied["applied"])
            self.assertTrue((Path(tmp) / "evals" / "new-dataset.json").exists())
            self.assertTrue(any(row["id"] == "template-b" for row in store.list_prompt_templates()))
            self.assertTrue(any(row["id"] == "profile-b" for row in store.list_run_profiles()))
            self.assertEqual(audits[0][0][0], "workspace_bundle.import")


if __name__ == "__main__":
    unittest.main()
