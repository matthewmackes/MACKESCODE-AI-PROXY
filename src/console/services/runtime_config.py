"""Runtime paths, local tokens, proxy endpoint, and host discovery."""
import os
import secrets
import subprocess
from pathlib import Path


class RuntimeConfigService:
    """Owns environment-backed runtime paths and local token helpers."""

    def __init__(
        self,
        *,
        env=None,
        file_path=None,
        embedded_access_key="",
        config=None,
        token_urlsafe=None,
        check_output_func=None,
    ):
        self.env = env if env is not None else os.environ
        self.file_path = Path(file_path or __file__).resolve()
        self.embedded_access_key = embedded_access_key
        self.config = config or {}
        self.token_urlsafe = token_urlsafe or secrets.token_urlsafe
        self.check_output_func = check_output_func or subprocess.check_output

    def config_value(self, section, key, default=None):
        section_value = self.config.get(section) if isinstance(self.config, dict) else None
        if isinstance(section_value, dict) and key in section_value:
            return section_value[key]
        return default

    def home_dir(self):
        return Path(self.env.get("HOME") or "/root")

    def script_dir(self):
        return self.file_path.parent

    def app_dir(self):
        path = Path(self.env.get("MATTS_STUDIO_DIR", self.home_dir() / ".cache/matts-value-set/studio"))
        path.mkdir(parents=True, exist_ok=True)
        (path / "images").mkdir(exist_ok=True)
        return path

    def auth_token_file(self):
        return Path(self.env.get("MATTS_CONSOLE_AUTH_FILE", self.app_dir() / "console-auth-token"))

    def auth_token(self):
        env_token = self.env.get("MATTS_CONSOLE_AUTH_TOKEN")
        if env_token:
            return env_token.strip()
        path = self.auth_token_file()
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        token = self.token_urlsafe(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n", encoding="utf-8")
        path.chmod(0o600)
        return token

    def auth_enabled(self):
        if self.env.get("MATTS_CONSOLE_DISABLE_AUTH") == "1":
            return False
        return bool(self.config_value("auth", "enabled", True))

    def token_file(self):
        return Path(self.env.get("MATTS_VALUE_SET_TOKEN_FILE", self.home_dir() / ".mcnf-do-model-access-token"))

    def access_key(self):
        if self.env.get("MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE") == "1" and self.env.get("MATTS_VALUE_SET_ACCESS_KEY"):
            return self.env["MATTS_VALUE_SET_ACCESS_KEY"]
        try:
            existing = self.token_file().read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except OSError:
            pass
        return self.embedded_access_key

    def write_token(self):
        path = self.token_file()
        key = self.access_key()
        if not key:
            raise SystemExit("Set MATTS_VALUE_SET_ACCESS_KEY or write a model access key to %s" % path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key + "\n", encoding="utf-8")
        path.chmod(0o600)

    def proxy_host(self):
        return self.env.get("MATTS_VALUE_SET_PROXY_HOST", str(self.config_value("proxy", "host", "127.0.0.1")))

    def proxy_port(self):
        return int(self.env.get("MATTS_VALUE_SET_PROXY_PORT", self.config_value("proxy", "port", 18081)))

    def proxy_url(self, path):
        return "http://%s:%d%s" % (self.proxy_host(), self.proxy_port(), path)

    def cost_file(self):
        return Path(self.env.get("MATTS_VALUE_SET_COST_FILE", self.home_dir() / ".cache/matts-value-set/usage.jsonl"))

    def budget_file(self):
        return Path(self.env.get("MATTS_VALUE_SET_BUDGET_FILE", self.home_dir() / ".cache/matts-value-set/budgets.json"))

    def log_file(self):
        return Path(self.env.get("MATTS_VALUE_SET_LOG_FILE", "/tmp/matts-value-set-proxy.jsonl"))

    def digitalocean_token_file(self):
        return Path(self.env.get("DIGITALOCEAN_TOKEN_FILE", self.home_dir() / ".config/digitalocean/token"))

    def digitalocean_token_paths(self):
        paths = [self.digitalocean_token_file(), self.home_dir() / ".mcnf-do-token", self.script_dir() / ".mcnf-do-token"]
        root_token = Path("/root/.mcnf-do-token")
        if root_token not in paths:
            paths.append(root_token)
        return paths

    def digitalocean_token(self):
        token = self.env.get("DIGITALOCEAN_TOKEN", "").strip()
        if token:
            return token
        for path in self.digitalocean_token_paths():
            if path.exists():
                token = path.read_text(encoding="utf-8").strip()
                if token:
                    return token
        return ""

    def digitalocean_account_urn(self):
        return self.env.get("DIGITALOCEAN_ACCOUNT_URN", "").strip()

    def local_addresses(self):
        addresses = []
        try:
            output = self.check_output_func(["hostname", "-I"], text=True, timeout=2)
            for item in output.split():
                if item and ":" not in item and not item.startswith("127."):
                    addresses.append(item)
        except (OSError, subprocess.SubprocessError):
            pass
        return addresses
