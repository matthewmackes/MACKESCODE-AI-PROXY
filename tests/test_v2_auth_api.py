import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.v2.api import auth as auth_api


class V2AuthApiTests(unittest.TestCase):
    def test_identity_uses_shared_runtime_console_token_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            studio_dir = root / "studio"
            studio_dir.mkdir()
            token_file = studio_dir / "console-auth-token"
            token_file.write_text("shared-token\n", encoding="utf-8")
            config_file = root / "console.json"
            config_file.write_text(
                json.dumps({
                    "auth": {"enabled": True},
                    "paths": {
                        "studio_dir": str(studio_dir),
                        "auth_token_file": "console-auth-token",
                    },
                }),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"MATTS_CONSOLE_CONFIG_FILE": str(config_file)}, clear=True):
                identity = auth_api.identity_from_values("/v2/me", query_token="shared-token")

        self.assertEqual(identity["id"], "console-owner")
        self.assertEqual(identity["roles"], ["owner"])
        self.assertEqual(identity["permissions"], ["*"])


if __name__ == "__main__":
    unittest.main()
