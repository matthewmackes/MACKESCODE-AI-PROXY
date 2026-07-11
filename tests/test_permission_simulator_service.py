import tempfile
import unittest
from pathlib import Path

from src.console.services.permission_simulator import PermissionSimulatorService


class PermissionSimulatorServiceTests(unittest.TestCase):
    def service(self, root):
        return PermissionSimulatorService(project_dir=lambda: Path(root))

    def test_broad_bash_and_bypass_mode_are_high_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            summary = service.simulate({
                "project_dir": tmp,
                "permission_mode": "bypassPermissions",
                "allowed_tools": "Bash(*) Edit Write Read",
                "disallowed_tools": "",
            })

        codes = [item["code"] for item in summary["warnings"]]
        self.assertEqual(summary["risk_level"], "critical")
        self.assertIn("permission_bypass", codes)
        self.assertIn("broad_bash", codes)
        self.assertIn("edits_without_denylist", codes)
        self.assertTrue(summary["override_allowed"])
        self.assertEqual(summary["suggested_preset"]["permission_mode"], "plan")

    def test_path_summary_flags_outside_home_and_root_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inside = root / "docs"
            inside.mkdir()
            service = self.service(root)
            summary = service.simulate({
                "project_dir": str(root),
                "permission_mode": "acceptEdits",
                "add_dirs": "%s\n%s\n/" % (inside, Path.home()),
                "allowed_tools": "Read Grep Glob",
                "disallowed_tools": "Bash(rm *)",
            })

        risks = [item["risk"] for item in summary["paths"]]
        codes = [item["code"] for item in summary["warnings"]]
        self.assertIn("normal", risks)
        self.assertIn("home_scope", risks)
        self.assertIn("root_scope", risks)
        self.assertIn("home_directory_scope", codes)
        self.assertIn("root_directory_scope", codes)

    def test_unknown_tools_are_reported_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            summary = service.simulate({
                "project_dir": tmp,
                "permission_mode": "manual",
                "allowed_tools": "Read MadeUpTool",
                "disallowed_tools": "OtherTool",
            })

        self.assertEqual(summary["risk_level"], "low")
        self.assertEqual(summary["categories"]["unknown"], ["MadeUpTool", "OtherTool"])


if __name__ == "__main__":
    unittest.main()
