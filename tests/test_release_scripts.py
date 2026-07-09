import importlib.util
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


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
            usage_file = home / ".cache/matts-value-set/usage.jsonl"
            budget_file = home / ".cache/matts-value-set/budgets.json"
            for path, text in [
                (model_file, '{"models":[{"id":"a","enabled":true}]}'),
                (gateway_file, '{"enabled":true}'),
                (app / "dedicated-inference.json", '{"state":"active"}'),
                (app / "tmux-sessions.json", '{"sessions":[]}'),
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
                "MATTS_VALUE_SET_COST_FILE": str(usage_file),
                "MATTS_VALUE_SET_BUDGET_FILE": str(budget_file),
            }
            with patch.dict(os.environ, env, clear=False), redirect_stdout(StringIO()):
                self.assertEqual(script.main(["backup", "--output", str(archive)]), 0)

            model_file.write_text('{"models":[]}', encoding="utf-8")
            with patch.dict(os.environ, env, clear=False), redirect_stdout(StringIO()):
                self.assertEqual(script.main(["restore", str(archive)]), 0)

            self.assertIn('"id":"a"', model_file.read_text(encoding="utf-8"))
            self.assertTrue(list(root.glob("models.json.pre-restore-*")))


if __name__ == "__main__":
    unittest.main()
