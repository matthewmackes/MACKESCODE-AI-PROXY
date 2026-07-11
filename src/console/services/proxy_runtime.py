"""Shared runtime helpers for the standalone Anthropic-compatible proxy."""
import hmac
import ipaddress
import json
import os


def env_truthy(name):
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def is_loopback_bind_host(host):
    value = str(host or "").strip().lower()
    if value == "localhost":
        return True
    if not value:
        return False
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def proxy_bind_allowed(host, inbound_auth_token, allow_unauthenticated_remote=False):
    if is_loopback_bind_host(host):
        return True, "loopback"
    if str(inbound_auth_token or "").strip():
        return True, "inbound_auth_token"
    if allow_unauthenticated_remote:
        return True, "explicit_unauthenticated_remote_override"
    return False, "non-loopback proxy binds require --inbound-auth-token or MATTS_PROXY_AUTH_TOKEN"


def header_value(headers, name):
    if not hasattr(headers, "get"):
        return ""
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    if value is None:
        value = headers.get("-".join(part.capitalize() for part in name.split("-")))
    return str(value or "")


def inbound_authorized(headers, expected):
    expected = str(expected or "").strip()
    if not expected:
        return True
    header_token = header_value(headers, "x-matts-proxy-token").strip()
    auth_header = header_value(headers, "authorization").strip()
    bearer_token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    return (
        bool(header_token) and hmac.compare_digest(header_token, expected)
    ) or (
        bool(bearer_token) and hmac.compare_digest(bearer_token, expected)
    )


def default_model_access_state_path():
    return os.path.join(os.path.expanduser("~"), ".cache", "matts-value-set", "studio", "model-access-state.json")


def load_model_access_state(path):
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    return models if isinstance(models, dict) else {}


def apply_model_access_state(records, state):
    if not state:
        return [dict(record) for record in records]
    merged = []
    for record in records:
        row = dict(record)
        model_id = str(row.get("id") or "")
        overlay = state.get(model_id) if model_id else None
        if isinstance(overlay, dict):
            if overlay.get("access_status"):
                row["access_status"] = str(overlay.get("access_status"))
            if overlay.get("last_error"):
                row["last_error"] = str(overlay.get("last_error"))
            if overlay.get("last_checked_at"):
                row["last_checked_at"] = overlay.get("last_checked_at")
            if overlay.get("http_status"):
                row["access_http_status"] = overlay.get("http_status")
        merged.append(row)
    return merged
