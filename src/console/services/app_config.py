"""JSON-backed console configuration with environment overrides."""
import copy
import json
import os
from pathlib import Path


DEFAULT_CONSOLE_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 18181},
    "auth": {"enabled": True},
    "logging": {"level": "INFO"},
    "models": {"auto_enable_max_usd": 0.45},
    "serverless": {"catalog_ttl_seconds": 3600},
    "proxy": {
        "host": "127.0.0.1",
        "port": 18081,
        "base_url": "https://inference.do-ai.run",
        "script": "do-anthropic-proxy.py",
    },
    "paths": {
        "template_dir": "templates",
        "studio_dir": ".cache/matts-value-set/studio",
        "default_model_registry_file": "config/default-models.json",
        "model_config_file": "config/models.json",
        "dedicated_config_file": "dedicated-inference.json",
        "serverless_catalog_cache_file": "serverless-model-catalog.json",
        "dedicated_events_file": "dedicated-events.jsonl",
        "tmux_session_registry_file": "tmux-sessions.json",
        "wallpaper_cache_dir": ".cache/matts-value-set/wallpapers",
        "auth_token_file": "console-auth-token",
        "cost_file": ".cache/matts-value-set/usage.jsonl",
        "budget_file": ".cache/matts-value-set/budgets.json",
        "proxy_log_file": "/tmp/matts-value-set-proxy.jsonl",
    },
    "rate_limits": {"enabled": False},
}


class ConfigError(ValueError):
    pass


def deep_merge(base, overrides):
    merged = copy.deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConsoleConfigService:
    """Load console configuration from defaults, JSON file, and environment."""

    def __init__(self, *, env=None, file_path=None, config_path=None):
        self.env = env if env is not None else os.environ
        self.file_path = Path(file_path or __file__).resolve()
        default_path = self.file_path.parent / "config" / "console.json"
        self.config_path = Path(config_path or self.env.get("MATTS_CONSOLE_CONFIG_FILE") or default_path)

    def load_file(self):
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError("invalid console config JSON: %s" % exc) from exc
        if not isinstance(data, dict):
            raise ConfigError("console config must be a JSON object")
        return data

    def env_overrides(self):
        overrides = {}
        mappings = {
            "MATTS_STUDIO_HOST": ("server", "host", str),
            "MATTS_STUDIO_PORT": ("server", "port", int),
            "MATTS_CONSOLE_LOG_LEVEL": ("logging", "level", str),
            "MATTS_MODEL_AUTO_ENABLE_MAX_USD": ("models", "auto_enable_max_usd", float),
            "MATTS_SERVERLESS_CATALOG_TTL_SECONDS": ("serverless", "catalog_ttl_seconds", int),
            "MATTS_VALUE_SET_PROXY_HOST": ("proxy", "host", str),
            "MATTS_VALUE_SET_PROXY_PORT": ("proxy", "port", int),
            "MATTS_VALUE_SET_BASE_URL": ("proxy", "base_url", str),
            "MATTS_VALUE_SET_PROXY_SCRIPT": ("proxy", "script", str),
        }
        for env_name, (section, key, cast) in mappings.items():
            if env_name in self.env and str(self.env.get(env_name, "")).strip() != "":
                try:
                    value = cast(self.env[env_name])
                except (TypeError, ValueError) as exc:
                    raise ConfigError("%s has invalid value %r" % (env_name, self.env[env_name])) from exc
                overrides.setdefault(section, {})[key] = value
        if self.env.get("MATTS_CONSOLE_DISABLE_AUTH") == "1":
            overrides.setdefault("auth", {})["enabled"] = False
        return overrides

    def load(self):
        config = deep_merge(DEFAULT_CONSOLE_CONFIG, self.load_file())
        config = deep_merge(config, self.env_overrides())
        self.validate(config)
        return config

    def validate(self, config):
        if not isinstance(config, dict):
            raise ConfigError("console config must be a JSON object")
        for section in ("server", "auth", "logging", "models", "serverless", "proxy", "paths", "rate_limits"):
            self.require_section(config, section)
        self.require_int(config, ("server", "port"), 1, 65535)
        self.require_int(config, ("proxy", "port"), 1, 65535)
        self.require_float(config, ("models", "auto_enable_max_usd"), 0)
        self.require_int(config, ("serverless", "catalog_ttl_seconds"), 1)
        self.require_string(config, ("server", "host"))
        self.require_string(config, ("proxy", "host"))
        self.require_string(config, ("proxy", "base_url"))
        self.require_string(config, ("proxy", "script"))
        self.require_string(config, ("logging", "level"))
        for key in DEFAULT_CONSOLE_CONFIG["paths"]:
            self.require_string(config, ("paths", key))
        if not isinstance(config["auth"].get("enabled"), bool):
            raise ConfigError("auth.enabled must be a boolean")
        if not isinstance(config["rate_limits"].get("enabled"), bool):
            raise ConfigError("rate_limits.enabled must be a boolean")
        return True

    def require_section(self, config, name):
        if not isinstance(config.get(name), dict):
            raise ConfigError("%s must be an object" % name)

    def value_at(self, config, path):
        current = config
        for part in path:
            if not isinstance(current, dict) or part not in current:
                raise ConfigError("%s is required" % ".".join(path))
            current = current[part]
        return current

    def require_int(self, config, path, minimum=None, maximum=None):
        value = self.value_at(config, path)
        if not isinstance(value, int):
            raise ConfigError("%s must be an integer" % ".".join(path))
        if minimum is not None and value < minimum:
            raise ConfigError("%s must be at least %s" % (".".join(path), minimum))
        if maximum is not None and value > maximum:
            raise ConfigError("%s must be at most %s" % (".".join(path), maximum))

    def require_float(self, config, path, minimum=None):
        value = self.value_at(config, path)
        if not isinstance(value, (int, float)):
            raise ConfigError("%s must be numeric" % ".".join(path))
        if minimum is not None and value < minimum:
            raise ConfigError("%s must be at least %s" % (".".join(path), minimum))

    def require_string(self, config, path):
        value = self.value_at(config, path)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError("%s must be a non-empty string" % ".".join(path))
