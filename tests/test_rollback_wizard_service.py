import json
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from src.console.services.rollback_wizard import RollbackWizardService


class RollbackWizardServiceTests(unittest.TestCase):
    def write_archive(self, root, target_file):
        root = Path(root)
        staging = root / "staging"
        payload = staging / "payload"
        payload.mkdir(parents=True)
        (payload / "model_registry").write_text('{"models":[{"id":"archived"}]}', encoding="utf-8")
        manifest = {
            "created_at": 999,
            "include_secrets": False,
            "items": [{"name": "model_registry", "path": str(target_file), "exists": True, "type": "file"}],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        archive = root / "runtime-state-backup.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(staging / "manifest.json", arcname="manifest.json")
            tar.add(payload, arcname="payload")
        return archive

    def service(self, root, audits=None, db=None):
        root = Path(root)
        audits = audits if audits is not None else []
        return RollbackWizardService(
            archive_dirs=lambda: [root],
            backup_output_dir=lambda: root / "rollback-backups",
            item_paths={},
            append_audit=lambda *args, **kwargs: audits.append((args, kwargs)),
            health_check=lambda: {"status": "ok"},
            v2_run_db=lambda: db or root / "missing.sqlite3",
            clock=lambda: 1000,
        )

    def test_discovers_runtime_archive_and_previews_impact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "models.json"
            target.write_text('{"models":[]}', encoding="utf-8")
            self.write_archive(root, target)
            service = self.service(root)
            targets = service.targets()
            target_id = targets["targets"][0]["id"]
            preview = service.preview({"target_id": target_id})

        self.assertEqual(targets["summary"]["runtime_archives"], 1)
        self.assertEqual(preview["summary"]["will_restore"], 1)
        self.assertTrue(preview["items"][0]["will_move_existing_aside"])

    def test_apply_creates_pre_backup_restores_selected_items_and_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audits = []
            target = root / "models.json"
            target.write_text('{"models":[]}', encoding="utf-8")
            self.write_archive(root, target)
            service = self.service(root, audits)
            target_id = service.targets()["targets"][0]["id"]
            result = service.apply({"target_id": target_id, "reason": "restore known good", "actor": {"id": "infra"}})
            restored_text = target.read_text(encoding="utf-8")
            pre_backup_exists = Path(result["pre_backup"]).exists()
            moved_aside = list(root.glob("models.json.pre-rollback-*"))

        self.assertIn("archived", restored_text)
        self.assertTrue(pre_backup_exists)
        self.assertTrue(moved_aside)
        self.assertEqual(result["health"], {"status": "ok"})
        self.assertEqual(audits[0][0][0], "rollback.apply")

    def test_apply_requires_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "models.json"
            target.write_text("{}", encoding="utf-8")
            self.write_archive(root, target)
            service = self.service(root)
            target_id = service.targets()["targets"][0]["id"]
            with self.assertRaisesRegex(ValueError, "reason is required"):
                service.apply({"target_id": target_id})

    def test_discovers_v2_version_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "run.sqlite3"
            conn = sqlite3.connect(str(db))
            try:
                conn.execute("CREATE TABLE run_profile_versions (profile_id TEXT, version INTEGER)")
                conn.execute("CREATE TABLE prompt_template_versions (template_id TEXT, version INTEGER)")
                conn.execute("INSERT INTO run_profile_versions VALUES ('p1', 1)")
                conn.commit()
            finally:
                conn.close()
            targets = self.service(root, db=db).targets()["targets"]

        self.assertTrue(any(row["type"] == "v2_run_profile_versions" for row in targets))


if __name__ == "__main__":
    unittest.main()
