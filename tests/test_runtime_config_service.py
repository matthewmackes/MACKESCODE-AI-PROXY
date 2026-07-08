import tempfile
import unittest
from pathlib import Path

from src.console.services.runtime_config import RuntimeConfigService


class RuntimeConfigServiceTests(unittest.TestCase):
    def service(self, tmp, env=None, token_urlsafe=None, check_output_func=None):
        return RuntimeConfigService(
            env=env if env is not None else {"HOME": tmp},
            file_path=Path(tmp) / "project" / "image-studio.py",
            embedded_access_key="embedded-key",
            token_urlsafe=token_urlsafe or (lambda size: "generated-token"),
            check_output_func=check_output_func or (lambda *args, **kwargs: "10.0.0.5 127.0.0.1 fe80::1\n"),
        )

    def test_paths_default_under_home_and_create_app_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp)
            app_dir = service.app_dir()
            self.assertEqual(service.home_dir(), Path(tmp))
            self.assertEqual(service.script_dir(), Path(tmp) / "project")
            self.assertEqual(app_dir.name, "studio")
            self.assertTrue((app_dir / "images").is_dir())
            self.assertEqual(service.token_file(), Path(tmp) / ".mcnf-do-model-access-token")
            self.assertEqual(service.log_file(), Path("/tmp/matts-value-set-proxy.jsonl"))

    def test_auth_token_prefers_env_then_file_then_generated_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"HOME": tmp, "MATTS_CONSOLE_AUTH_TOKEN": " env-token "}
            self.assertEqual(self.service(tmp, env=env).auth_token(), "env-token")

            token_path = Path(tmp) / "auth-token"
            token_path.write_text("file-token\n", encoding="utf-8")
            env = {"HOME": tmp, "MATTS_CONSOLE_AUTH_FILE": str(token_path)}
            self.assertEqual(self.service(tmp, env=env).auth_token(), "file-token")

            generated_path = Path(tmp) / "generated-token-file"
            env = {"HOME": tmp, "MATTS_CONSOLE_AUTH_FILE": str(generated_path)}
            self.assertEqual(self.service(tmp, env=env).auth_token(), "generated-token")
            self.assertEqual(generated_path.read_text(encoding="utf-8").strip(), "generated-token")

    def test_auth_enabled_and_access_key_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            disabled = self.service(tmp, env={"HOME": tmp, "MATTS_CONSOLE_DISABLE_AUTH": "1"})
            self.assertFalse(disabled.auth_enabled())

            config_disabled = RuntimeConfigService(env={"HOME": tmp}, file_path=Path(tmp) / "image-studio.py", config={"auth": {"enabled": False}})
            self.assertFalse(config_disabled.auth_enabled())

            token_file = Path(tmp) / "model-token"
            token_file.write_text("file-key\n", encoding="utf-8")
            file_key = self.service(tmp, env={"HOME": tmp, "MATTS_VALUE_SET_TOKEN_FILE": str(token_file)})
            self.assertEqual(file_key.access_key(), "file-key")

            override = self.service(tmp, env={
                "HOME": tmp,
                "MATTS_VALUE_SET_TOKEN_FILE": str(token_file),
                "MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE": "1",
                "MATTS_VALUE_SET_ACCESS_KEY": "override-key",
            })
            self.assertEqual(override.access_key(), "override-key")

            fallback = self.service(tmp, env={"HOME": tmp})
            self.assertEqual(fallback.access_key(), "embedded-key")

    def test_write_token_requires_key_and_sets_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token"
            service = self.service(tmp, env={"HOME": tmp, "MATTS_VALUE_SET_TOKEN_FILE": str(token_path), "MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE": "1", "MATTS_VALUE_SET_ACCESS_KEY": "key"})
            service.write_token()
            self.assertEqual(token_path.read_text(encoding="utf-8").strip(), "key")

            missing = RuntimeConfigService(env={"HOME": tmp, "MATTS_VALUE_SET_TOKEN_FILE": str(token_path)}, file_path=Path(tmp) / "image-studio.py", embedded_access_key="")
            token_path.unlink()
            with self.assertRaises(SystemExit):
                missing.write_token()

    def test_proxy_cost_budget_and_digitalocean_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "HOME": tmp,
                "MATTS_VALUE_SET_PROXY_HOST": "0.0.0.0",
                "MATTS_VALUE_SET_PROXY_PORT": "19999",
                "MATTS_VALUE_SET_COST_FILE": str(Path(tmp) / "costs.jsonl"),
                "MATTS_VALUE_SET_BUDGET_FILE": str(Path(tmp) / "budget.json"),
                "MATTS_VALUE_SET_LOG_FILE": str(Path(tmp) / "proxy.log"),
                "DIGITALOCEAN_TOKEN": "do-token",
                "DIGITALOCEAN_ACCOUNT_URN": "urn:do:account:1",
            }
            service = self.service(tmp, env=env)

        self.assertEqual(service.proxy_host(), "0.0.0.0")
        self.assertEqual(service.proxy_port(), 19999)
        self.assertEqual(service.proxy_url("/v1/models"), "http://0.0.0.0:19999/v1/models")
        self.assertEqual(service.cost_file(), Path(tmp) / "costs.jsonl")
        self.assertEqual(service.budget_file(), Path(tmp) / "budget.json")
        self.assertEqual(service.log_file(), Path(tmp) / "proxy.log")
        self.assertEqual(service.digitalocean_token(), "do-token")
        self.assertEqual(service.digitalocean_account_urn(), "urn:do:account:1")

    def test_proxy_defaults_can_come_from_console_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = RuntimeConfigService(
                env={"HOME": tmp},
                file_path=Path(tmp) / "image-studio.py",
                config={"proxy": {"host": "proxy.internal", "port": 19001}},
            )

            self.assertEqual(service.proxy_host(), "proxy.internal")
            self.assertEqual(service.proxy_port(), 19001)
            self.assertEqual(service.proxy_url("/v1/models"), "http://proxy.internal:19001/v1/models")

    def test_digitalocean_token_reads_known_files_and_local_addresses_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".mcnf-do-token").write_text("file-do-token\n", encoding="utf-8")
            service = self.service(tmp, check_output_func=lambda *args, **kwargs: "10.0.0.1 127.0.0.1 fe80::1 192.168.1.10\n")
            self.assertEqual(service.digitalocean_token(), "file-do-token")
            self.assertEqual(service.local_addresses(), ["10.0.0.1", "192.168.1.10"])

    def test_local_addresses_handles_hostname_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, check_output_func=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing")))

        self.assertEqual(service.local_addresses(), [])


if __name__ == "__main__":
    unittest.main()
