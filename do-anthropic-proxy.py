#!/usr/bin/env python3
"""Anthropic Messages API compatibility proxy for MDE LLM-PROXY models."""
import argparse
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from src.console.services.proxy_runtime import (
    apply_model_access_state as _apply_model_access_state,
    default_model_access_state_path as _default_model_access_state_path,
    env_truthy as _env_truthy,
    header_value as _proxy_header_value,
    inbound_authorized as _proxy_inbound_authorized,
    load_model_access_state as _load_model_access_state,
    proxy_bind_allowed as _proxy_bind_allowed,
)
from src.console.services.streaming_metrics import StreamingMetricsService


DEFAULT_DO_BASE_URL = "https://inference.do-ai.run"
DEFAULT_MODEL = "deepseek-3.2"
DEFAULT_COST_FILE = os.path.join(os.path.expanduser("~"), ".cache/matts-value-set/usage.jsonl")
DEFAULT_LOG_FILE = "/tmp/matts-value-set-proxy.jsonl"
DEFAULT_TRACE_FILE = os.path.join(os.path.expanduser("~"), ".cache/matts-value-set/studio/traces.jsonl")
DEFAULT_BUDGET_FILE = os.path.join(os.path.expanduser("~"), ".cache/matts-value-set/budgets.json")
DEFAULT_GATEWAY_POLICY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "gateway-policy.json")
# Only keys the proxy actually reads are declared here. Previously-advertised but
# never-consumed keys (failover.max_attempts/dedicated_preference/
# fallback_reason_codes, retries.enabled/max_retries/backoff_seconds, and the
# whole budget block) were removed so the /v1/claude-do/gateway-policy state no
# longer promises behavior the code does not implement. `retries.retry_statuses`
# is retained because it is read to decide which upstream statuses trigger
# serverless failover.
DEFAULT_GATEWAY_POLICY = {
    "schema_version": 1,
    "enabled": True,
    "failover": {
        "enabled": True,
        "serverless_fallback": True,
    },
    "circuit_breakers": {
        "enabled": False,
        "failure_window_seconds": 300,
        "failure_threshold": 5,
        "cooldown_seconds": 120,
        "tracked_statuses": [429, 500, 502, 503, 504],
    },
    "rate_limits": {
        "enabled": False,
        "global_per_minute": 0,
        "per_model_per_minute": {},
        "per_session_per_minute": {},
    },
    "cache": {
        "enabled": False,
        "ttl_seconds": 300,
        "routes": {"chat": False, "images": False, "model_list": True},
    },
    "retries": {
        "retry_statuses": [429, 500, 502, 503, 504],
    },
    "slo_routing": {
        "enabled": True,
        "default_goal": "balanced",
        "router_models": ["router:slo", "router:cheapest", "router:fastest", "router:quality", "router:context"],
        "enforce_explicit_constraints": False,
        "constraints": {
            "modality": "text",
            "min_context_window": 0,
            "max_estimated_cost_usd": 0,
            "max_input_cost_per_mtok": 0,
            "max_output_cost_per_mtok": 0,
            "max_latency_ms": 0,
            "require_tools": False
        },
        "quality_scores": {},
        "latency_targets_ms": {}
    },
}
def _model_config_path():
    return os.environ.get(
        "MATTS_MODEL_CONFIG_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "models.json"),
    )


def _default_model_config_path():
    return os.environ.get(
        "MATTS_DEFAULT_MODEL_CONFIG_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "default-models.json"),
    )


def _model_access_state_path():
    return os.environ.get("MATTS_MODEL_ACCESS_STATE_FILE", _default_model_access_state_path())


def _model_route_enabled(model):
    if not isinstance(model, dict) or not model.get("id") or model.get("enabled") is False:
        return False
    if model.get("serverless") and model.get("type", "text") == "text":
        return model.get("access_status") == "ok"
    return True


def _load_model_registry(path, fallback_models, fallback_aliases, fallback_costs, access_state_path=None):
    error = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            raw_version = data.get("schema_version", 1)
            try:
                schema_version = int(raw_version)
            except (TypeError, ValueError) as exc:
                raise ValueError("Model registry schema_version must be an integer.") from exc
            if schema_version != 1:
                raise ValueError("Model registry schema_version %s is not supported; expected 1." % schema_version)
            rows = data.get("models")
        else:
            rows = data
    except (OSError, ValueError) as exc:
        error = str(exc)
        rows = None
    if not isinstance(rows, list):
        rows = []

    records = [model for model in rows if isinstance(model, dict) and model.get("id")]
    records = _apply_model_access_state(records, _load_model_access_state(access_state_path))
    active = [model for model in records if _model_route_enabled(model)]
    if not active:
        fallback_records = [{"id": model_id, "type": "text", "enabled": True, "access_status": "fallback"} for model_id in fallback_models]
        return list(fallback_models), dict(fallback_aliases), dict(fallback_costs), False, records or fallback_records, error

    text = [str(model["id"]) for model in active if model.get("type", "text") == "text"]
    image = [str(model["id"]) for model in active if model.get("type") == "image"]
    aliases = {}
    costs = dict(fallback_costs)
    for model in active:
        model_id = str(model["id"])
        for alias in model.get("aliases") or []:
            alias = str(alias).strip()
            if alias:
                aliases[alias] = model_id
        pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
        if pricing:
            costs[model_id] = {key: float(value or 0) for key, value in pricing.items() if key in ("input", "output", "image")}
    return text + image, aliases, costs, True, records, ""


def _load_bootstrap_fallbacks(path=None):
    """Load the bootstrap fallback model/alias/pricing data.

    GOVERNANCE: `config/models.json` stays the active source of truth; this
    data is only used when that registry cannot provide any route-enabled
    model. `config/default-models.json` is the single sanctioned bootstrap
    fallback source. If it is unreadable too, degrade to a minimal
    model-id-only structure with no pricing (costs report `priced: false`)
    instead of keeping a divergent hardcoded price table.

    Returns (models, aliases, costs, warning).
    """
    path = path or _default_model_config_path()
    models, aliases, costs, loaded, _records, error = _load_model_registry(path, [DEFAULT_MODEL], {}, {})
    warning = ""
    if not loaded:
        warning = (
            "bootstrap fallback file %s could not be loaded (%s); "
            "degrading to minimal fallback model list %s with no pricing data"
            % (path, error or "no active models", json.dumps([DEFAULT_MODEL]))
        )
    return models, aliases, costs, warning


def _model_config_fingerprint(path):
    try:
        stat = os.stat(path)
        return {
            "path": str(path),
            "exists": True,
            "mtime": stat.st_mtime,
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    except OSError as exc:
        return {
            "path": str(path),
            "exists": False,
            "mtime": 0,
            "mtime_ns": 0,
            "size": 0,
            "error": str(exc),
        }


def _same_model_config_fingerprint(left, right):
    return (
        bool(left)
        and bool(right)
        and left.get("exists") == right.get("exists")
        and left.get("mtime_ns") == right.get("mtime_ns")
        and left.get("size") == right.get("size")
    )


def _refresh_model_registry(server, force=False):
    if not getattr(server, "model_config_file", ""):
        return
    fingerprint = _model_config_fingerprint(server.model_config_file)
    access_fingerprint = _model_config_fingerprint(getattr(server, "model_access_state_file", ""))
    server.model_config_last_check_at = time.time()
    previous = getattr(server, "model_config_fingerprint", None)
    previous_access = getattr(server, "model_access_state_fingerprint", None)
    if not force and _same_model_config_fingerprint(fingerprint, previous) and _same_model_config_fingerprint(access_fingerprint, previous_access):
        return
    models, aliases, costs, loaded, records, error = _load_model_registry(
        server.model_config_file,
        server.fallback_models,
        server.fallback_model_aliases,
        server.fallback_costs,
        getattr(server, "model_access_state_file", ""),
    )
    server.models = models
    server.model_aliases = aliases
    server.costs = costs
    server.model_registry_records = records
    server.model_config_loaded = loaded
    server.model_config_fingerprint = fingerprint
    server.model_access_state_fingerprint = access_fingerprint
    server.model_config_last_loaded_at = time.time()
    server.model_config_last_error = "" if loaded else (error or fingerprint.get("error") or "No active route-enabled models loaded from registry.")
    if server.default_model not in server.models and server.models:
        text_models = [model for model in server.models if "image" not in model.lower() and "stable-diffusion" not in model.lower()]
        server.default_model = text_models[0] if text_models else server.models[0]


def _model_config_state(server):
    fingerprint = getattr(server, "model_config_fingerprint", None) or _model_config_fingerprint(getattr(server, "model_config_file", ""))
    current = _model_config_fingerprint(getattr(server, "model_config_file", ""))
    access_fingerprint = getattr(server, "model_access_state_fingerprint", None) or _model_config_fingerprint(getattr(server, "model_access_state_file", ""))
    access_current = _model_config_fingerprint(getattr(server, "model_access_state_file", ""))
    config_stale = not _same_model_config_fingerprint(fingerprint, current)
    access_stale = not _same_model_config_fingerprint(access_fingerprint, access_current)
    return {
        "file": getattr(server, "model_config_file", ""),
        "access_state_file": getattr(server, "model_access_state_file", ""),
        "loaded": bool(getattr(server, "model_config_loaded", False)),
        "loaded_at": getattr(server, "model_config_last_loaded_at", 0),
        "last_check_at": getattr(server, "model_config_last_check_at", 0),
        "last_error": getattr(server, "model_config_last_error", ""),
        "fingerprint": fingerprint,
        "current_fingerprint": current,
        "access_state_fingerprint": access_fingerprint,
        "current_access_state_fingerprint": access_current,
        "stale": config_stale or access_stale,
    }


def _registry_record_for_model(server, model):
    for record in getattr(server, "model_registry_records", []) or []:
        if isinstance(record, dict) and record.get("id") == model:
            return record
    return {}


def _unavailable_model_policy(server, model):
    record = _registry_record_for_model(server, model)
    dedicated = record.get("dedicated") if isinstance(record.get("dedicated"), dict) else {}
    access = record.get("access_status") or "not_checked"
    if record.get("serverless") and access in {"forbidden", "unauthorized"}:
        return {"decision": "access_forbidden_rejection", "model": model, "reason": "access_forbidden", "access_status": access}
    if dedicated.get("managed"):
        return {"decision": "build_server_prompt", "model": model, "reason": "dedicated_not_online", "state": dedicated.get("state") or record.get("state") or "not_configured"}
    return {"decision": "model_unavailable_rejection", "model": model, "reason": "model_not_configured", "access_status": access}


def _dedicated_config_path():
    return os.environ.get(
        "MATTS_DEDICATED_CONFIG_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "dedicated-inference.json"),
    )


def _load_dedicated_config():
    try:
        with open(_dedicated_config_path(), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def _dedicated_endpoint(cfg):
    endpoint = cfg.get("public_endpoint_fqdn") if cfg.get("enable_public_endpoint", True) else cfg.get("private_endpoint_fqdn")
    endpoint = str(endpoint or cfg.get("public_endpoint_fqdn") or cfg.get("private_endpoint_fqdn") or "").strip().rstrip("/")
    return endpoint


def _dedicated_route(model):
    cfg = _load_dedicated_config()
    if not cfg or model != cfg.get("model_id") or cfg.get("state") != "active":
        return None
    endpoint = _dedicated_endpoint(cfg)
    token = str(cfg.get("access_token") or "").strip()
    if not endpoint or not token:
        return None
    return {
        "url": endpoint + "/v1/chat/completions",
        "token": token,
        "model": cfg.get("model_slug") or model,
        "endpoint": endpoint,
        "config": cfg,
    }


def _dedicated_lifecycle(model):
    cfg = _load_dedicated_config()
    if not cfg or model != cfg.get("model_id"):
        return None
    endpoint = _dedicated_endpoint(cfg)
    token_ready = bool(str(cfg.get("access_token") or "").strip())
    ready = cfg.get("state") == "active" and bool(endpoint) and token_ready
    next_step = "Route requests to the Dedicated endpoint."
    if cfg.get("state") != "active":
        next_step = "Wait for DigitalOcean to report active, then sync the proxy from the Console."
    elif not endpoint:
        next_step = "Refresh Dedicated Inference status so the endpoint address is assigned."
    elif not token_ready:
        next_step = "Create or refresh the Dedicated access token from the Console."
    return {
        "ready": ready,
        "state": cfg.get("state") or "not_configured",
        "server_id": cfg.get("inference_id") or "",
        "name": cfg.get("name") or model,
        "model_id": cfg.get("model_id") or model,
        "model_slug": cfg.get("model_slug") or model,
        "region": cfg.get("region") or "",
        "accelerator_slug": cfg.get("accelerator_slug") or "",
        "endpoint_ready": bool(endpoint),
        "endpoint_mode": "public" if cfg.get("enable_public_endpoint", True) else "private",
        "endpoint_host": endpoint,
        "access_token_ready": token_ready,
        "last_error": cfg.get("last_error") or "",
        "next_step": next_step,
    }


def _dedicated_not_ready_error(model, lifecycle):
    message = (
        "%s is not ready for Claude Code yet. DigitalOcean state is %s. "
        "Endpoint: %s. Access token: %s. %s"
    ) % (
        lifecycle.get("name") or model,
        lifecycle.get("state") or "unknown",
        "assigned" if lifecycle.get("endpoint_ready") else "not assigned",
        "configured" if lifecycle.get("access_token_ready") else "missing",
        lifecycle.get("next_step") or "Refresh Dedicated Inference status in the Console.",
    )
    if lifecycle.get("last_error"):
        message += " Last DigitalOcean error: " + str(lifecycle["last_error"])[:500]
    return {
        "type": "error",
        "error": {
            "type": "service_unavailable_error",
            "message": message,
            "dedicated_lifecycle": lifecycle,
        },
        "routing": {
            "requested": model,
            "used": None,
            "backend": "dedicated",
            "reason": "dedicated_not_ready",
            "policy_decision": {
                "decision": "dedicated_wait_not_ready",
                "model": model,
                "state": lifecycle.get("state"),
                "next_step": lifecycle.get("next_step"),
            },
        },
    }


def _dedicated_max_output_tokens(cfg):
    value = cfg.get("max_output_tokens") or os.environ.get("MATTS_DEDICATED_MAX_OUTPUT_TOKENS")
    if value not in (None, ""):
        try:
            return max(256, int(value))
        except (TypeError, ValueError):
            pass
    model_slug = str(cfg.get("model_slug") or "").lower()
    if "qwen3" in model_slug:
        return 8192
    return None


def _apply_dedicated_runtime_limits(payload, cfg):
    max_output = _dedicated_max_output_tokens(cfg)
    if max_output is None:
        return None
    current = payload.get("max_tokens")
    try:
        current_int = int(current)
    except (TypeError, ValueError):
        payload["max_tokens"] = max_output
        return {"from": current, "to": max_output, "reason": "dedicated max output default"}
    if current_int > max_output:
        payload["max_tokens"] = max_output
        return {"from": current_int, "to": max_output, "reason": "dedicated max output default"}
    return None


def _context_retry_tokens(error_text):
    text = str(error_text or "")
    match = re.search(
        r"maximum context length is\s+(\d+)\s+tokens.*?requested\s+(\d+)\s+output tokens.*?prompt contains at least\s+(\d+)\s+input tokens",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    context_window = int(match.group(1))
    requested_output = int(match.group(2))
    input_tokens = int(match.group(3))
    retry_tokens = context_window - input_tokens - 256
    if retry_tokens < 256 or retry_tokens >= requested_output:
        return None
    return retry_tokens


def _chat_url(base_url):
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1/chat/completions"):
        return base_url
    return base_url + "/v1/chat/completions"


def _images_url(base_url):
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1/images/generations"):
        return base_url
    if base_url.endswith("/v1/chat/completions"):
        base_url = base_url[: -len("/v1/chat/completions")]
    if base_url.endswith("/v1/messages"):
        base_url = base_url[: -len("/v1/messages")]
    return base_url + "/v1/images/generations"


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _safe_json_loads(value, default=None):
    if not value:
        return default if default is not None else {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default if default is not None else {}


def _strip_provider_markup(text):
    if not text:
        return ""
    text = re.sub(r"<\|im_(?:start|end)\|>", "", text)
    text = re.sub(r"</?tool_response>", "", text)
    text = re.sub(r"(?is)<think>.*?</think>", "", text)
    text = text.replace("<think>", "").replace("</think>", "")
    return text.strip()


def _text_tool_call_to_openai(call_text, allowed_tool_names=None):
    data = _safe_json_loads(call_text, default=None)
    if not isinstance(data, dict):
        return None

    function = data.get("function") if isinstance(data.get("function"), dict) else {}
    name = data.get("name") or function.get("name")
    arguments = data.get("arguments")
    if arguments is None:
        arguments = data.get("input")
    if arguments is None:
        arguments = function.get("arguments")
    if not name:
        return None
    if allowed_tool_names is not None and name not in allowed_tool_names:
        return None
    if isinstance(arguments, str):
        argument_text = arguments
    else:
        argument_text = _json_text(arguments or {})
    return {
        "id": data.get("id") or "toolu_" + uuid.uuid4().hex,
        "type": "function",
        "function": {
            "name": name,
            "arguments": argument_text,
        },
    }


def _extract_text_tool_calls(text, allowed_tool_names=None):
    if not isinstance(text, str) or "<tool_call>" not in text:
        return _strip_provider_markup(text or ""), []
    if allowed_tool_names is not None and not allowed_tool_names:
        cleaned = re.sub(r"(?is)<tool_call>\s*.*?\s*</tool_call>", "", text)
        cleaned = re.split(r"(?is)<\|im_start\|>\s*(?:tool|user|assistant)\b", cleaned, maxsplit=1)[0]
        return _strip_provider_markup(cleaned), []

    tool_calls = []
    saw_tool_call = False

    def replace(match):
        nonlocal saw_tool_call
        saw_tool_call = True
        tool_call = _text_tool_call_to_openai(match.group(1), allowed_tool_names=allowed_tool_names)
        if tool_call:
            tool_calls.append(tool_call)
        return ""

    cleaned = re.sub(r"(?is)<tool_call>\s*(.*?)\s*</tool_call>", replace, text)
    if saw_tool_call:
        cleaned = re.split(r"(?is)<\|im_start\|>\s*(?:tool|user|assistant)\b", cleaned, maxsplit=1)[0]
    cleaned = _strip_provider_markup(cleaned)
    return cleaned, tool_calls


def _strip_assistant_history_markup(text):
    if not isinstance(text, str):
        return ""
    text = re.sub(r"(?is)<tool_call>\s*.*?\s*</tool_call>", "", text)
    text = re.split(r"(?is)<\|im_start\|>\s*(?:tool|user|assistant)\b", text, maxsplit=1)[0]
    return _strip_provider_markup(text)


def _content_to_text(content, include_tool_markers=True):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            text = _content_block_to_text(item, include_tool_markers=include_tool_markers)
            if text:
                parts.append(text)
        return "\n\n".join(parts)
    return ""


def _tool_result_content_to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, dict):
                item_type = item.get("type", "unknown")
                parts.append("[unsupported tool result content: %s]" % item_type)
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if content is None:
        return ""
    return str(content)


def _content_block_to_text(item, include_tool_markers=True):
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return str(item)

    item_type = item.get("type")
    if item_type == "text":
        return str(item.get("text", ""))

    if item_type == "tool_use":
        if not include_tool_markers:
            return ""
        header = "[tool_use"
        if item.get("id"):
            header += " id=%s" % item["id"]
        if item.get("name"):
            header += " name=%s" % item["name"]
        header += "]"
        tool_input = _json_text(item.get("input", {}))
        return "%s\n%s\n[/tool_use]" % (header, tool_input)

    if item_type == "tool_result":
        if not include_tool_markers:
            return ""
        header = "[tool_result"
        if item.get("tool_use_id"):
            header += " tool_use_id=%s" % item["tool_use_id"]
        if item.get("is_error"):
            header += " is_error=true"
        header += "]"
        result = _tool_result_content_to_text(item.get("content"))
        return "%s\n%s\n[/tool_result]" % (header, result)

    if item_type in ("image", "document"):
        return "[unsupported content block: %s]" % item_type

    return _json_text(item)


def _anthropic_tools_to_openai(tools):
    out = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not name:
            continue
        parameters = tool.get("input_schema")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description", ""),
                "parameters": parameters,
            },
        })
    return out


def _anthropic_tool_choice_to_openai(tool_choice):
    if not isinstance(tool_choice, dict):
        return None
    choice_type = tool_choice.get("type")
    if choice_type == "auto":
        return "auto"
    if choice_type == "any":
        return "required"
    if choice_type == "none":
        return "none"
    if choice_type == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return None


def _append_openai_user_parts(messages, role, parts):
    text = "\n\n".join(part for part in parts if part)
    if text:
        messages.append({"role": role, "content": text})


def _anthropic_user_to_openai(messages, role, content):
    if not isinstance(content, list):
        messages.append({"role": role, "content": _content_to_text(content)})
        return

    text_parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_result":
            _append_openai_user_parts(messages, role, text_parts)
            text_parts = []
            tool_use_id = item.get("tool_use_id")
            result_text = _tool_result_content_to_text(item.get("content"))
            if tool_use_id:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_use_id,
                    "content": result_text,
                })
            else:
                text_parts.append(_content_block_to_text(item))
        else:
            text = _content_block_to_text(item, include_tool_markers=False)
            if text:
                text_parts.append(text)
    _append_openai_user_parts(messages, role, text_parts)


def _anthropic_assistant_to_openai(messages, content):
    if not isinstance(content, list):
        messages.append({"role": "assistant", "content": _strip_assistant_history_markup(_content_to_text(content))})
        return

    text_parts = []
    tool_calls = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            tool_calls.append({
                "id": item.get("id") or "toolu_" + uuid.uuid4().hex,
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": _json_text(item.get("input", {})),
                },
            })
        else:
            text = _content_block_to_text(item, include_tool_markers=False)
            if isinstance(item, dict) and item.get("type") == "text":
                text = _strip_assistant_history_markup(text)
            if text:
                text_parts.append(text)

    message = {"role": "assistant", "content": "\n\n".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    messages.append(message)


def _load_json_env(value, default):
    if not value:
        return default
    try:
        loaded = json.loads(value)
        return loaded if isinstance(loaded, type(default)) else default
    except ValueError:
        return default


def _resolve_model(model, aliases):
    return aliases.get(model, model)


def _capability_enabled(capabilities, name, default=True):
    value = capabilities.get(name)
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes", "on")


def _clamp_tokens(value, capabilities):
    if value is None:
        return None
    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return value
    max_output = capabilities.get("max_output_tokens")
    if max_output is None:
        return tokens
    try:
        return min(tokens, int(max_output))
    except (TypeError, ValueError):
        return tokens


def _anthropic_to_openai(body, model=None, capabilities=None):
    model = model or body.get("model") or DEFAULT_MODEL
    capabilities = capabilities or {}
    messages = []
    adapter = capabilities.get("prompt_adapter")
    if adapter:
        messages.append({"role": "system", "content": str(adapter)})
    system = body.get("system")
    if isinstance(system, str) and system:
        messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text = _content_to_text(system)
        if text:
            messages.append({"role": "system", "content": text})

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        content = msg.get("content", "")
        if role == "assistant":
            _anthropic_assistant_to_openai(messages, content)
        else:
            _anthropic_user_to_openai(messages, role, content)

    out = {
        "model": model,
        "messages": messages,
    }
    max_tokens = _clamp_tokens(body.get("max_tokens"), capabilities)
    if max_tokens is not None:
        out["max_tokens"] = max_tokens
    if body.get("temperature") is not None:
        out["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        out["top_p"] = body["top_p"]
    if body.get("stop_sequences") is not None:
        out["stop"] = body["stop_sequences"]

    tools = _anthropic_tools_to_openai(body.get("tools")) if _capability_enabled(capabilities, "tools", True) else []
    if tools:
        out["tools"] = tools
        tool_choice = _anthropic_tool_choice_to_openai(body.get("tool_choice"))
        if tool_choice is not None:
            out["tool_choice"] = tool_choice
    return out


def _openai_tool_call_to_anthropic(tool_call):
    function = tool_call.get("function") or {}
    return {
        "type": "tool_use",
        "id": tool_call.get("id") or "toolu_" + uuid.uuid4().hex,
        "name": function.get("name", ""),
        "input": _safe_json_loads(function.get("arguments"), default={}),
    }


def _stop_reason_from_openai(finish_reason, has_tool_calls=False):
    if has_tool_calls or finish_reason == "tool_calls":
        return "tool_use"
    if finish_reason == "length":
        return "max_tokens"
    if finish_reason == "stop" or finish_reason is None:
        return "end_turn"
    return "end_turn"


def _anthropic_response(model, message, finish_reason=None, usage=None, allowed_tool_names=None):
    usage = usage or {}
    text, parsed_tool_calls = _extract_text_tool_calls(
        message.get("content") or "",
        allowed_tool_names=allowed_tool_names,
    )
    tool_calls = list(message.get("tool_calls") or []) + parsed_tool_calls
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            content.append(_openai_tool_call_to_anthropic(tool_call))
    if not content:
        content.append({"type": "text", "text": ""})

    return {
        "id": "msg_" + uuid.uuid4().hex,
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": _stop_reason_from_openai(finish_reason, has_tool_calls=bool(tool_calls)),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _cost_for_usage(model, usage, costs):
    usage = usage or {}
    rates = costs.get(model) or {}
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    input_cost = input_tokens * float(rates.get("input", 0.0)) / 1_000_000
    output_cost = output_tokens * float(rates.get("output", 0.0)) / 1_000_000
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost_usd": round(input_cost, 8),
        "output_cost_usd": round(output_cost, 8),
        "total_cost_usd": round(input_cost + output_cost, 8),
        "priced": bool(rates),
    }


def _streaming_metrics(started_at, usage=None, output_text="", cost=None, stream_requested=False, client_streaming=False, provider_streaming=False, chunk_count=0):
    return StreamingMetricsService(clock=time.time).finalize(
        started_at=started_at,
        usage=usage,
        output_text=output_text,
        cost=cost,
        stream_requested=stream_requested,
        client_streaming=client_streaming,
        provider_streaming=provider_streaming,
        chunk_count=chunk_count,
    )


def _cost_for_images(model, image_count, costs):
    rates = costs.get(model) or {}
    image_cost = int(image_count or 0) * float(rates.get("image", 0.0))
    return {
        "model": model,
        "images": int(image_count or 0),
        "input_tokens": 0,
        "output_tokens": 0,
        "input_cost_usd": 0.0,
        "output_cost_usd": 0.0,
        "total_cost_usd": round(image_cost, 8),
        "priced": "image" in rates,
    }


def _write_jsonl(path, record):
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def _summarize_messages(messages, limit=160):
    rows = messages if isinstance(messages, list) else []
    last_user = ""
    for msg in rows:
        if isinstance(msg, dict) and msg.get("role") == "user":
            last_user = _content_to_text(msg.get("content"), include_tool_markers=False)
    preview = " ".join(str(last_user or "").split())[:limit]
    return {
        "message_count": len(rows),
        "last_user_preview": preview,
        "last_user_chars": len(str(last_user or "")),
    }


def _trace_request(
    server,
    *,
    action,
    status,
    body=None,
    requested_model=None,
    routed_model=None,
    endpoint_mode=None,
    routing_reason="",
    upstream_url="",
    upstream_id="",
    usage=None,
    cost=None,
    started_at=None,
    error_category="",
    human_message="",
    extra=None,
):
    status = int(status)
    cost = cost if isinstance(cost, dict) else {}
    usage = usage if isinstance(usage, dict) else {}
    record = {
        "trace_id": "trace_" + uuid.uuid4().hex,
        "timestamp": time.time(),
        "action": action,
        "status": "success" if status < 400 else "error",
        "http_status": status,
        "requested_model": requested_model,
        "routed_model": routed_model,
        "provider": getattr(server, "provider", "DigitalOcean"),
        "endpoint_mode": endpoint_mode or "proxy",
        "routing_reason": routing_reason or "",
        "latency_ms": int((time.time() - started_at) * 1000) if started_at else 0,
        "message_summary": _summarize_messages((body or {}).get("messages") if isinstance(body, dict) else []),
        "usage": usage,
        "cost": cost,
        "cost_usd": cost.get("total_cost_usd"),
        "upstream_id": upstream_id or "",
        "upstream_url": upstream_url or "",
        "error_category": error_category or ("http_%s" % status if status >= 400 else ""),
        "human_message": human_message or "",
    }
    if isinstance(extra, dict):
        record.update(extra)
    _write_jsonl(getattr(server, "trace_file", ""), record)
    return record


def _attach_trace(payload, trace):
    if not isinstance(payload, dict) or not isinstance(trace, dict):
        return payload
    payload["trace_id"] = trace.get("trace_id")
    if isinstance(payload.get("error"), dict):
        payload["error"]["trace_id"] = trace.get("trace_id")
    if isinstance(payload.get("claude_do"), dict):
        payload["claude_do"]["trace_id"] = trace.get("trace_id")
    return payload


def _read_json_file(path, default):
    if not path:
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override if override is not None else base
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_gateway_policy(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Gateway policy must be a JSON object.")
        schema_version = int(data.get("schema_version", 1))
        if schema_version != 1:
            raise ValueError("Gateway policy schema_version %s is not supported; expected 1." % schema_version)
        return _deep_merge(DEFAULT_GATEWAY_POLICY, data), True, ""
    except (OSError, TypeError, ValueError) as exc:
        return dict(DEFAULT_GATEWAY_POLICY), False, str(exc)


def _refresh_gateway_policy(server):
    policy, loaded, error = _load_gateway_policy(getattr(server, "gateway_policy_file", ""))
    server.gateway_policy = policy
    server.gateway_policy_loaded = loaded
    server.gateway_policy_last_error = "" if loaded else error
    server.gateway_policy_last_loaded_at = time.time() if loaded else getattr(server, "gateway_policy_last_loaded_at", 0)


def _gateway_policy_state(server):
    if not hasattr(server, "gateway_policy"):
        _refresh_gateway_policy(server)
    return {
        "file": getattr(server, "gateway_policy_file", ""),
        "loaded": bool(getattr(server, "gateway_policy_loaded", False)),
        "loaded_at": getattr(server, "gateway_policy_last_loaded_at", 0),
        "last_error": getattr(server, "gateway_policy_last_error", ""),
        "policy": getattr(server, "gateway_policy", dict(DEFAULT_GATEWAY_POLICY)),
    }


def _request_session_id(body):
    if not isinstance(body, dict):
        return ""
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    for key in ("session_id", "conversation_id", "chat_id", "user_id"):
        value = metadata.get(key) or body.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _positive_int(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _request_timeout_seconds(body, default=600):
    if not isinstance(body, dict):
        return default
    timeout = _positive_int(body.get("request_timeout_seconds") or body.get("timeout_seconds"))
    if not timeout:
        return default
    return max(1, min(default, timeout))


def _positive_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, value)


def _request_text_chars(body):
    messages = body.get("messages") if isinstance(body, dict) and isinstance(body.get("messages"), list) else []
    return sum(len(_content_to_text(msg.get("content"), include_tool_markers=False)) for msg in messages if isinstance(msg, dict))


def _estimate_chat_tokens(body):
    input_tokens = max(1, int(_request_text_chars(body) / 4))
    max_tokens = _positive_int((body or {}).get("max_tokens")) or 512
    return input_tokens, max_tokens


def _model_supports_tools(record):
    if not isinstance(record, dict):
        return False
    if record.get("supports_tools") is not None:
        return bool(record.get("supports_tools"))
    capabilities = record.get("capabilities") if isinstance(record.get("capabilities"), dict) else {}
    if capabilities.get("tools") is not None:
        return bool(capabilities.get("tools"))
    if record.get("tool_support") is not None:
        return str(record.get("tool_support")).lower() not in {"", "false", "none", "no"}
    return False


def _gateway_model_stats(server, model):
    stats = getattr(server, "gateway_model_stats", None)
    if stats is None:
        stats = {}
        server.gateway_model_stats = stats
    row = stats.get(model) or {}
    requests = int(row.get("requests") or 0)
    errors = int(row.get("errors") or 0)
    total_latency = float(row.get("total_latency_ms") or 0)
    return {
        "requests": requests,
        "errors": errors,
        "avg_latency_ms": int(total_latency / requests) if requests else 0,
        "error_rate": round(errors / requests, 4) if requests else 0.0,
        "total_cost_usd": round(float(row.get("total_cost_usd") or 0), 8),
    }


def _gateway_record_model_result(server, model, status, latency_ms=0, cost=None):
    if not model:
        return None
    stats = getattr(server, "gateway_model_stats", None)
    if stats is None:
        stats = {}
        server.gateway_model_stats = stats
    row = stats.get(model) or {"requests": 0, "errors": 0, "total_latency_ms": 0.0, "total_cost_usd": 0.0}
    row["requests"] = int(row.get("requests") or 0) + 1
    row["errors"] = int(row.get("errors") or 0) + (1 if int(status) >= 400 else 0)
    row["total_latency_ms"] = float(row.get("total_latency_ms") or 0) + max(0, float(latency_ms or 0))
    if isinstance(cost, dict):
        row["total_cost_usd"] = float(row.get("total_cost_usd") or 0) + float(cost.get("total_cost_usd") or 0)
    row["last_status"] = int(status)
    row["last_updated"] = time.time()
    stats[model] = row
    return _gateway_model_stats(server, model)


def _gateway_slo_policy(server):
    policy = getattr(server, "gateway_policy", DEFAULT_GATEWAY_POLICY)
    if not policy.get("enabled", True):
        return None
    slo = policy.get("slo_routing") if isinstance(policy.get("slo_routing"), dict) else {}
    if not slo.get("enabled", True):
        return None
    return slo


def _gateway_slo_request(body):
    if not isinstance(body, dict):
        return {}
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    request = body.get("slo") if isinstance(body.get("slo"), dict) else metadata.get("slo")
    return request if isinstance(request, dict) else {}


def _gateway_slo_goal(slo_policy, requested_model, body):
    request = _gateway_slo_request(body)
    explicit_goal = str(request.get("goal") or "").strip().lower()
    if explicit_goal:
        return explicit_goal
    requested = str(requested_model or "").strip().lower()
    if requested == "router:cheapest":
        return "cheapest"
    if requested == "router:fastest":
        return "fastest"
    if requested in {"router:quality", "router:highest-quality"}:
        return "highest_quality"
    if requested == "router:context":
        return "context_fit"
    return str((slo_policy or {}).get("default_goal") or "balanced").strip().lower()


def _gateway_slo_constraints(slo_policy, body):
    base = slo_policy.get("constraints") if isinstance(slo_policy.get("constraints"), dict) else {}
    requested = _gateway_slo_request(body).get("constraints")
    requested = requested if isinstance(requested, dict) else {}
    return _deep_merge(base, requested)


def _gateway_is_router_model(slo_policy, requested_model, body):
    request = _gateway_slo_request(body)
    if request:
        return bool(request.get("route") or request.get("goal") or request.get("constraints"))
    routers = {str(item).lower() for item in (slo_policy.get("router_models") or [])}
    return str(requested_model or "").lower() in routers


def _gateway_candidate_models(server):
    records = getattr(server, "model_registry_records", []) or []
    by_id = {str(record.get("id")): record for record in records if isinstance(record, dict) and record.get("id")}
    out = []
    for model in getattr(server, "models", []) or []:
        model = str(model)
        record = by_id.get(model, {})
        if (record.get("type") or "text") != "text":
            continue
        out.append((model, record))
    return out


def _gateway_slo_candidate(server, model, record, body, constraints, goal, slo_policy):
    input_tokens, output_tokens = _estimate_chat_tokens(body)
    rates = getattr(server, "costs", {}).get(model) or {}
    input_rate = float(rates.get("input") or 0)
    output_rate = float(rates.get("output") or 0)
    estimated_cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    context_window = int(record.get("context_window") or 0)
    max_output_tokens = int(record.get("max_output_tokens") or 0)
    modality = str(record.get("type") or "text")
    tool_support = _model_supports_tools(record)
    stats = _gateway_model_stats(server, model)
    latency_targets = slo_policy.get("latency_targets_ms") if isinstance(slo_policy.get("latency_targets_ms"), dict) else {}
    avg_latency_ms = int(latency_targets.get(model) or stats["avg_latency_ms"] or 0)
    quality_scores = slo_policy.get("quality_scores") if isinstance(slo_policy.get("quality_scores"), dict) else {}
    quality_score = float(quality_scores.get(model) or record.get("quality_score") or 0)
    reasons = []
    if constraints.get("modality") and str(constraints.get("modality")) != modality:
        reasons.append("modality_mismatch")
    if _positive_int(constraints.get("min_context_window")) and context_window and context_window < _positive_int(constraints.get("min_context_window")):
        reasons.append("context_window_too_small")
    if _positive_int(constraints.get("min_context_window")) and not context_window:
        reasons.append("context_window_unknown")
    if _positive_float(constraints.get("max_estimated_cost_usd")) and estimated_cost > _positive_float(constraints.get("max_estimated_cost_usd")):
        reasons.append("estimated_cost_too_high")
    if _positive_float(constraints.get("max_input_cost_per_mtok")) and input_rate > _positive_float(constraints.get("max_input_cost_per_mtok")):
        reasons.append("input_price_too_high")
    if _positive_float(constraints.get("max_output_cost_per_mtok")) and output_rate > _positive_float(constraints.get("max_output_cost_per_mtok")):
        reasons.append("output_price_too_high")
    if _positive_int(constraints.get("max_latency_ms")) and avg_latency_ms and avg_latency_ms > _positive_int(constraints.get("max_latency_ms")):
        reasons.append("latency_too_high")
    if constraints.get("require_tools") and not tool_support:
        reasons.append("tools_not_supported")
    score = _gateway_slo_score(goal, estimated_cost, avg_latency_ms, context_window, quality_score, stats["error_rate"])
    return {
        "model": model,
        "accepted": not reasons,
        "reasons": reasons,
        "score": score,
        "estimated_cost_usd": round(estimated_cost, 8),
        "input_cost_per_mtok": input_rate,
        "output_cost_per_mtok": output_rate,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "modality": modality,
        "tool_support": tool_support,
        "avg_latency_ms": avg_latency_ms,
        "error_rate": stats["error_rate"],
        "quality_score": quality_score,
    }


def _gateway_slo_score(goal, estimated_cost, avg_latency_ms, context_window, quality_score, error_rate):
    goal = goal or "balanced"
    if goal == "cheapest":
        return round(estimated_cost, 10)
    if goal == "fastest":
        return avg_latency_ms or 999999999
    if goal in {"highest_quality", "quality"}:
        return round(-quality_score + error_rate, 6)
    if goal == "context_fit":
        return -(context_window or 0)
    latency_component = (avg_latency_ms or 5000) / 5000
    cost_component = estimated_cost * 1000
    quality_component = -quality_score
    return round(cost_component + latency_component + error_rate + quality_component, 6)


def _gateway_select_slo_model(server, requested_model, resolved_model, body):
    slo_policy = _gateway_slo_policy(server)
    if not slo_policy:
        return resolved_model, None, None
    router_requested = _gateway_is_router_model(slo_policy, requested_model, body)
    if not router_requested and not bool(slo_policy.get("enforce_explicit_constraints")):
        return resolved_model, None, None
    goal = _gateway_slo_goal(slo_policy, requested_model, body)
    constraints = _gateway_slo_constraints(slo_policy, body)
    candidates = []
    for model, record in _gateway_candidate_models(server):
        if not router_requested and model != resolved_model:
            continue
        candidates.append(_gateway_slo_candidate(server, model, record, body, constraints, goal, slo_policy))
    accepted = [candidate for candidate in candidates if candidate["accepted"]]
    rejected = [candidate for candidate in candidates if not candidate["accepted"]]
    if not accepted:
        proof = {
            "decision": "slo_route_rejected",
            "requested_model": requested_model,
            "resolved_model": resolved_model,
            "goal": goal,
            "constraints": constraints,
            "candidates": candidates,
            "rejections": rejected,
        }
        return resolved_model, proof, {
            "type": "slo_route_rejected",
            "message": "No model satisfies SLO routing constraints for %s." % (requested_model or resolved_model),
            "policy_decision": proof,
        }
    selected = sorted(accepted, key=lambda item: (item["score"], item["estimated_cost_usd"], item["model"]))[0]
    proof = {
        "decision": "slo_route_selected" if router_requested else "slo_constraints_satisfied",
        "requested_model": requested_model,
        "resolved_model": resolved_model,
        "selected_model": selected["model"],
        "goal": goal,
        "constraints": constraints,
        "selected": selected,
        "candidates": candidates,
        "rejections": rejected,
    }
    return selected["model"], proof, None


def _rate_limit_candidates(policy, model, session_id):
    rate_policy = policy.get("rate_limits") if isinstance(policy.get("rate_limits"), dict) else {}
    if not rate_policy.get("enabled"):
        return []
    checks = []
    global_limit = _positive_int(rate_policy.get("global_per_minute"))
    if global_limit:
        checks.append(("global", "global", global_limit))
    model_limits = rate_policy.get("per_model_per_minute") if isinstance(rate_policy.get("per_model_per_minute"), dict) else {}
    model_limit = _positive_int(model_limits.get(model) or model_limits.get("*"))
    if model_limit:
        checks.append(("model", model, model_limit))
    session_limits = rate_policy.get("per_session_per_minute") if isinstance(rate_policy.get("per_session_per_minute"), dict) else {}
    session_limit = _positive_int(session_limits.get(session_id) or session_limits.get("*")) if session_id else 0
    if session_limit:
        checks.append(("session", session_id, session_limit))
    return checks


def _gateway_rate_limit_error(server, body, model, route_type, now=None):
    policy = getattr(server, "gateway_policy", DEFAULT_GATEWAY_POLICY)
    if not policy.get("enabled", True):
        return None
    now = time.time() if now is None else float(now)
    window_seconds = 60
    session_id = _request_session_id(body)
    checks = _rate_limit_candidates(policy, model, session_id)
    if not checks:
        return None
    counters = getattr(server, "gateway_rate_counters", None)
    if counters is None:
        counters = {}
        server.gateway_rate_counters = counters
    pending = []
    for scope, key, limit in checks:
        counter_key = "%s:%s:%s" % (route_type, scope, key)
        rows = [ts for ts in counters.get(counter_key, []) if now - float(ts) < window_seconds]
        counters[counter_key] = rows
        if len(rows) >= limit:
            oldest = min(rows) if rows else now
            retry_after = max(1, int(window_seconds - (now - oldest)))
            return {
                "type": "rate_limit_exceeded",
                "message": "%s rate limit exceeded for %s: %d requests per minute" % (scope, key, limit),
                "scope": scope,
                "key": key,
                "route": route_type,
                "model": model,
                "session_id": session_id,
                "limit": limit,
                "window_seconds": window_seconds,
                "retry_after_seconds": retry_after,
                "policy": {
                    "enabled": True,
                    "source": getattr(server, "gateway_policy_file", ""),
                },
            }
        pending.append((counter_key, rows))
    for counter_key, rows in pending:
        rows.append(now)
        counters[counter_key] = rows
    return None


def _json_clone(value):
    return json.loads(json.dumps(value))


def _gateway_cache_policy(server, route_type):
    policy = getattr(server, "gateway_policy", DEFAULT_GATEWAY_POLICY)
    if not policy.get("enabled", True):
        return None
    cache_policy = policy.get("cache") if isinstance(policy.get("cache"), dict) else {}
    routes = cache_policy.get("routes") if isinstance(cache_policy.get("routes"), dict) else {}
    if not cache_policy.get("enabled") or not routes.get(route_type):
        return None
    ttl = _positive_int(cache_policy.get("ttl_seconds")) or 300
    return {"ttl_seconds": ttl, "source": getattr(server, "gateway_policy_file", "")}


def _gateway_cache_key(route_type, model, request_payload):
    return "%s:%s:%s" % (route_type, model, json.dumps(request_payload or {}, sort_keys=True, separators=(",", ":")))


def _gateway_cache_get(server, route_type, model, request_payload, now=None):
    policy = _gateway_cache_policy(server, route_type)
    if not policy:
        return None
    now = time.time() if now is None else float(now)
    cache = getattr(server, "gateway_cache", None)
    if cache is None:
        cache = {}
        server.gateway_cache = cache
    key = _gateway_cache_key(route_type, model, request_payload)
    item = cache.get(key)
    if not item:
        return None
    if float(item.get("expires_at") or 0) <= now:
        cache.pop(key, None)
        return None
    payload = _json_clone(item.get("payload"))
    meta = payload.setdefault("claude_do", {})
    meta["gateway_cache"] = {
        "hit": True,
        "route": route_type,
        "cached_at": item.get("cached_at"),
        "expires_at": item.get("expires_at"),
        "ttl_seconds": policy["ttl_seconds"],
    }
    return payload


def _gateway_cache_store(server, route_type, model, request_payload, response_payload, now=None):
    policy = _gateway_cache_policy(server, route_type)
    if not policy or response_payload is None:
        return False
    now = time.time() if now is None else float(now)
    cache = getattr(server, "gateway_cache", None)
    if cache is None:
        cache = {}
        server.gateway_cache = cache
    key = _gateway_cache_key(route_type, model, request_payload)
    payload = _json_clone(response_payload)
    if isinstance(payload, dict):
        payload.pop("trace_id", None)
        if isinstance(payload.get("error"), dict):
            payload["error"].pop("trace_id", None)
        if isinstance(payload.get("claude_do"), dict):
            payload["claude_do"].pop("trace_id", None)
            payload["claude_do"].pop("gateway_cache", None)
    cache[key] = {
        "cached_at": now,
        "expires_at": now + policy["ttl_seconds"],
        "payload": payload,
    }
    return True


def _gateway_circuit_policy(server):
    policy = getattr(server, "gateway_policy", DEFAULT_GATEWAY_POLICY)
    if not policy.get("enabled", True):
        return None
    circuit = policy.get("circuit_breakers") if isinstance(policy.get("circuit_breakers"), dict) else {}
    if not circuit.get("enabled"):
        return None
    return {
        "failure_window_seconds": _positive_int(circuit.get("failure_window_seconds")) or 300,
        "failure_threshold": _positive_int(circuit.get("failure_threshold")) or 5,
        "cooldown_seconds": _positive_int(circuit.get("cooldown_seconds")) or 120,
        "tracked_statuses": {int(status) for status in circuit.get("tracked_statuses") or []},
        "source": getattr(server, "gateway_policy_file", ""),
    }


def _gateway_circuit_key(route_type, model):
    return "%s:%s" % (route_type, model)


def _gateway_circuit_open_error(server, route_type, model, now=None):
    policy = _gateway_circuit_policy(server)
    if not policy:
        return None
    now = time.time() if now is None else float(now)
    circuits = getattr(server, "gateway_circuit_state", None)
    if circuits is None:
        circuits = {}
        server.gateway_circuit_state = circuits
    key = _gateway_circuit_key(route_type, model)
    state = circuits.get(key) or {}
    open_until = float(state.get("open_until") or 0)
    if open_until <= now:
        return None
    retry_after = max(1, int(open_until - now))
    return {
        "type": "circuit_open",
        "message": "Gateway circuit is open for %s on %s; retry in %d seconds" % (model, route_type, retry_after),
        "route": route_type,
        "model": model,
        "open_until": open_until,
        "retry_after_seconds": retry_after,
        "failures": len(state.get("failures") or []),
        "policy": {"source": policy["source"], "cooldown_seconds": policy["cooldown_seconds"]},
    }


def _gateway_record_circuit_result(server, route_type, model, status, now=None):
    policy = _gateway_circuit_policy(server)
    if not policy:
        return None
    now = time.time() if now is None else float(now)
    circuits = getattr(server, "gateway_circuit_state", None)
    if circuits is None:
        circuits = {}
        server.gateway_circuit_state = circuits
    key = _gateway_circuit_key(route_type, model)
    state = circuits.get(key) or {"failures": [], "open_until": 0}
    status = int(status)
    if status < 400:
        circuits[key] = {"failures": [], "open_until": 0, "last_status": status, "last_updated": now}
        return circuits[key]
    if status not in policy["tracked_statuses"]:
        return state
    failures = [float(ts) for ts in state.get("failures") or [] if now - float(ts) < policy["failure_window_seconds"]]
    failures.append(now)
    open_until = float(state.get("open_until") or 0)
    if len(failures) >= policy["failure_threshold"]:
        open_until = now + policy["cooldown_seconds"]
    state = {
        "failures": failures,
        "open_until": open_until,
        "last_status": status,
        "last_updated": now,
    }
    circuits[key] = state
    return state


def _gateway_retry_statuses(server):
    policy = getattr(server, "gateway_policy", DEFAULT_GATEWAY_POLICY)
    retry = policy.get("retries") if isinstance(policy.get("retries"), dict) else {}
    return {int(status) for status in retry.get("retry_statuses") or [429, 500, 502, 503, 504]}


def _gateway_should_failover(server, status):
    policy = getattr(server, "gateway_policy", DEFAULT_GATEWAY_POLICY)
    if not policy.get("enabled", True):
        return False
    failover = policy.get("failover") if isinstance(policy.get("failover"), dict) else {}
    if not failover.get("enabled") or not failover.get("serverless_fallback", True):
        return False
    return int(status) in _gateway_retry_statuses(server)


def _gateway_text_failover_model(server, current_model, attempted=None):
    attempted = {str(item) for item in (attempted or []) if item}
    current_model = str(current_model or "")
    attempted.add(current_model)
    for candidate in getattr(server, "models", []) or []:
        candidate = str(candidate)
        lower = candidate.lower()
        if candidate in attempted:
            continue
        if "image" in lower or "stable-diffusion" in lower:
            continue
        return candidate
    return None


def _usage_totals(cost_file):
    totals = {"all": 0.0, "today": 0.0, "month": 0.0}
    now = time.localtime()
    today = (now.tm_year, now.tm_yday)
    month = (now.tm_year, now.tm_mon)
    try:
        with open(cost_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                ts = time.localtime(float(row.get("ts", 0) or 0))
                cost = float((row.get("cost") or {}).get("total_cost_usd") or 0.0)
                totals["all"] += cost
                if (ts.tm_year, ts.tm_yday) == today:
                    totals["today"] += cost
                if (ts.tm_year, ts.tm_mon) == month:
                    totals["month"] += cost
    except OSError:
        pass
    return totals


class _UsageAggregator:
    """Incremental usage totals for the hot-path budget check.

    The naive budget check re-parsed the entire (unbounded) usage.jsonl on every
    request. This keeps per-day / per-month / all-time cost buckets in memory and,
    on each call, reads only the bytes appended since the last read (tracked by
    byte offset), so a busy proxy does O(new lines) work per request instead of
    O(whole file). Rotation/truncation is detected by inode change or the file
    shrinking below the last offset, which resets and re-seeds the buckets."""

    def __init__(self):
        self._lock = threading.Lock()
        self._offset = 0
        self._inode = None
        self._by_day = {}
        self._by_month = {}
        self._all = 0.0

    def _reset(self):
        self._offset = 0
        self._inode = None
        self._by_day = {}
        self._by_month = {}
        self._all = 0.0

    def _ingest(self, chunk):
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            cost = float((row.get("cost") or {}).get("total_cost_usd") or 0.0)
            if not cost:
                continue
            ts = time.localtime(float(row.get("ts", 0) or 0))
            day = (ts.tm_year, ts.tm_yday)
            month = (ts.tm_year, ts.tm_mon)
            self._by_day[day] = self._by_day.get(day, 0.0) + cost
            self._by_month[month] = self._by_month.get(month, 0.0) + cost
            self._all += cost

    def totals(self, cost_file):
        now = time.localtime()
        today = (now.tm_year, now.tm_yday)
        month = (now.tm_year, now.tm_mon)
        with self._lock:
            try:
                st = os.stat(cost_file)
            except OSError:
                return {"all": self._all, "today": self._by_day.get(today, 0.0), "month": self._by_month.get(month, 0.0)}
            if st.st_ino != self._inode or st.st_size < self._offset:
                self._reset()
                self._inode = st.st_ino
            if st.st_size > self._offset:
                try:
                    with open(cost_file, "rb") as f:
                        f.seek(self._offset)
                        data = f.read()
                except OSError:
                    data = b""
                last_nl = data.rfind(b"\n")
                if last_nl >= 0:
                    consumed = data[:last_nl + 1]
                    self._offset += len(consumed)
                    self._ingest(consumed.decode("utf-8", errors="replace"))
            return {"all": self._all, "today": self._by_day.get(today, 0.0), "month": self._by_month.get(month, 0.0)}


def _budget_error(cost_file, budget_file, aggregator=None):
    budgets = _read_json_file(budget_file, {})
    totals = aggregator.totals(cost_file) if aggregator is not None else _usage_totals(cost_file)
    for key, total_key in (("daily_usd", "today"), ("monthly_usd", "month"), ("total_usd", "all")):
        limit = budgets.get(key)
        if limit is None or str(limit) == "":
            continue
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            continue
        if limit > 0 and totals[total_key] >= limit:
            return {
                "type": "budget_exceeded",
                "message": "%s budget exceeded: %.6f >= %.6f USD" % (key, totals[total_key], limit),
                "totals": totals,
                "budgets": budgets,
            }
    return None


def _friendly_error(status, text):
    lower = (text or "").lower()
    if status == 402:
        msg = "provider payment or prepayment required; add DigitalOcean Serverless Inference prepaid balance or enable auto-reload"
    elif status == 403:
        msg = "provider authorization failed; check model access key scope, VPC restriction, team role, and account tier"
    elif status == 401:
        msg = "provider authentication failed; check token file and provider mode"
    elif status == 404 or "model" in lower and "not" in lower:
        msg = "model is not available from the active provider"
    elif status == 429:
        msg = "provider rate limit or quota exceeded"
    elif status >= 500:
        msg = "provider service error"
    elif "tool" in lower:
        msg = "provider rejected tool-call payload; try a Claude-compatible model or disable tools"
    elif "context" in lower or "token" in lower:
        msg = "provider rejected token budget or context length"
    else:
        msg = "provider request failed"
    return {"type": "api_error", "message": msg, "provider_status": status, "provider_body": text[:2000]}


def _write_anthropic_stream(wfile, anthropic):
    def event(name, payload):
        wfile.write(("event: %s\n" % name).encode("utf-8"))
        wfile.write(("data: %s\n\n" % json.dumps(payload)).encode("utf-8"))
        wfile.flush()

    msg = dict(anthropic)
    msg["content"] = []
    event("message_start", {"type": "message_start", "message": msg})

    for index, block in enumerate(anthropic["content"]):
        if block["type"] == "text":
            event("content_block_start", {
                "type": "content_block_start",
                "index": index,
                "content_block": {"type": "text", "text": ""},
            })
            if block.get("text"):
                event("content_block_delta", {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "text_delta", "text": block["text"]},
                })
        elif block["type"] == "tool_use":
            event("content_block_start", {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": block["id"],
                    "name": block["name"],
                    "input": {},
                },
            })
            event("content_block_delta", {
                "type": "content_block_delta",
                "index": index,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": _json_text(block.get("input", {})),
                },
            })
        event("content_block_stop", {"type": "content_block_stop", "index": index})

    event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": anthropic["stop_reason"], "stop_sequence": None},
        "usage": {"output_tokens": anthropic["usage"]["output_tokens"]},
    })
    metrics = ((anthropic.get("claude_do") or {}).get("streaming_metrics") if isinstance(anthropic.get("claude_do"), dict) else None)
    if isinstance(metrics, dict):
        event("metrics", {"type": "metrics", "streaming_metrics": metrics})
    event("message_stop", {"type": "message_stop"})


def _stream_openai_to_anthropic(wfile, model, line_iter):
    """Translate an OpenAI streaming (SSE) chat completion into the Anthropic SSE
    event protocol incrementally, forwarding each delta as it arrives so the
    client sees tokens with real time-to-first-byte instead of one buffered burst.
    Returns accumulated {text, usage, finish_reason, has_tool_calls} for cost/trace."""
    def event(name, payload):
        wfile.write(("event: %s\n" % name).encode("utf-8"))
        wfile.write(("data: %s\n\n" % json.dumps(payload)).encode("utf-8"))
        wfile.flush()

    message = {
        "id": "msg_" + uuid.uuid4().hex[:24],
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    event("message_start", {"type": "message_start", "message": message})

    text_index = None
    tool_blocks = {}
    next_index = 0
    finish_reason = None
    usage = {}
    text_accum = []
    for raw in line_iter:
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except ValueError:
            continue
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        content = delta.get("content")
        if content:
            if text_index is None:
                text_index = next_index
                next_index += 1
                event("content_block_start", {"type": "content_block_start", "index": text_index, "content_block": {"type": "text", "text": ""}})
            text_accum.append(content)
            event("content_block_delta", {"type": "content_block_delta", "index": text_index, "delta": {"type": "text_delta", "text": content}})
        for tool_call in delta.get("tool_calls") or []:
            tc_index = tool_call.get("index", 0)
            fn = tool_call.get("function") or {}
            if tc_index not in tool_blocks:
                block_index = next_index
                next_index += 1
                tool_blocks[tc_index] = block_index
                event("content_block_start", {"type": "content_block_start", "index": block_index, "content_block": {
                    "type": "tool_use",
                    "id": tool_call.get("id") or ("toolu_" + uuid.uuid4().hex[:20]),
                    "name": fn.get("name") or "",
                    "input": {},
                }})
            args = fn.get("arguments")
            if args:
                event("content_block_delta", {"type": "content_block_delta", "index": tool_blocks[tc_index], "delta": {"type": "input_json_delta", "partial_json": args}})

    if text_index is not None:
        event("content_block_stop", {"type": "content_block_stop", "index": text_index})
    for block_index in tool_blocks.values():
        event("content_block_stop", {"type": "content_block_stop", "index": block_index})

    stop_reason = _stop_reason_from_openai(finish_reason, has_tool_calls=bool(tool_blocks))
    event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": int(usage.get("completion_tokens") or 0)},
    })
    event("message_stop", {"type": "message_stop"})
    return {"text": "".join(text_accum), "usage": usage, "finish_reason": finish_reason, "has_tool_calls": bool(tool_blocks)}


def _model_display_name(model_id):
    return model_id.replace("-", " ").replace("_", " ").title()


def _models_payload(models, aliases=None, records=None, routeable=None, availability_filter="available"):
    routeable = set(routeable or models)
    out = []
    if records is not None:
        for record in records:
            model_id = str(record.get("id") or "").strip()
            if not model_id:
                continue
            available = model_id in routeable
            if availability_filter == "available" and not available:
                continue
            if availability_filter == "unavailable" and available:
                continue
            out.append({
                "id": model_id,
                "type": "model",
                "display_name": str(record.get("display_name") or _model_display_name(model_id)),
                "available": available,
                "model_type": record.get("type") or "text",
                "provider": record.get("provider") or "DigitalOcean",
                "access_status": record.get("access_status") or ("ok" if available else "not_checked"),
                "enabled": record.get("enabled") is not False,
                "context_window": int(record.get("context_window") or 0),
                "max_output_tokens": int(record.get("max_output_tokens") or 0),
                "pricing": record.get("pricing") if isinstance(record.get("pricing"), dict) else {},
                "tool_support": _model_supports_tools(record),
            })
    else:
        out = [{
            "id": model_id,
            "type": "model",
            "display_name": _model_display_name(model_id),
            "available": True,
        } for model_id in models]
    seen = {item["id"] for item in out}
    if availability_filter != "unavailable":
        for alias, target in sorted((aliases or {}).items()):
            if target not in seen or alias in seen:
                continue
            out.append({
                "id": alias,
                "type": "model",
                "display_name": "%s -> %s" % (_model_display_name(alias), target),
                "available": True,
                "alias_of": target,
            })
            seen.add(alias)
    return {
        "data": out,
        "has_more": False,
        "first_id": out[0]["id"] if out else None,
        "last_id": out[-1]["id"] if out else None,
        "available_filter": availability_filter,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "do-anthropic-proxy/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def _json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self._responded = True
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _raw(self, status, data, content_type="application/json"):
        self._responded = True
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _fail_safe(self, exc):
        """Convert an unhandled request-handler exception into a logged 502 instead
        of letting the exception escape and drop the client connection with no
        response and no trace."""
        try:
            _write_jsonl(getattr(self.server, "log_file", None), {
                "ts": time.time(),
                "provider": getattr(self.server, "provider", ""),
                "status": 502,
                "error_category": "unhandled_exception",
                "detail": str(exc),
                "path": getattr(self, "path", ""),
            })
        except Exception:
            pass
        if getattr(self, "_responded", False):
            return
        try:
            self._json(502, {"type": "error", "error": {
                "type": "api_error",
                "message": "proxy failed to handle the request or upstream response",
                "detail": str(exc),
            }})
        except Exception:
            pass

    def _read_json(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _token(self):
        with open(self.server.token_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _header_value(self, name):
        return _proxy_header_value(getattr(self, "headers", {}), name)

    def _inbound_authorized(self):
        expected = str(getattr(self.server, "inbound_auth_token", "") or "").strip()
        return _proxy_inbound_authorized(getattr(self, "headers", {}), expected)

    def _require_inbound_auth(self):
        if self._inbound_authorized():
            return False
        self._json(401, {"type": "error", "error": {
            "type": "unauthorized",
            "message": "proxy inbound auth token required",
        }})
        return True

    def _refresh_models(self, force=False):
        _refresh_model_registry(self.server, force=force)

    def _refresh_gateway_policy(self):
        _refresh_gateway_policy(self.server)

    def _chat_stream(self, body, payload, upstream_url, upstream_token, model, payload_model, requested_model, route, token_clamp, started):
        stream_payload = dict(payload)
        stream_payload["stream"] = True
        stream_payload["stream_options"] = {"include_usage": True}
        try:
            resp = requests.post(
                upstream_url,
                headers={
                    "authorization": "Bearer " + upstream_token,
                    "content-type": "application/json",
                    "user-agent": "matts-claude-code-proxy/1.0",
                },
                json=stream_payload,
                stream=True,
                timeout=600,
            )
        except Exception as exc:
            _write_jsonl(self.server.log_file, {"ts": time.time(), "provider": self.server.provider, "model": payload.get("model"), "upstream_url": upstream_url, "status": 502, "latency_ms": int((time.time() - started) * 1000), "error": str(exc)})
            _gateway_record_circuit_result(self.server, "chat", payload_model, 502, now=time.time())
            payload_error = {"type": "error", "error": {"type": "api_error", "message": str(exc)}}
            trace = _trace_request(self.server, action="proxy.chat", status=502, body=body, requested_model=requested_model, routed_model=payload_model, endpoint_mode="dedicated" if route else "serverless", routing_reason="upstream_exception", upstream_url=upstream_url, started_at=started, error_category="network_error", human_message=str(exc))
            return self._json(502, _attach_trace(payload_error, trace))
        # Error status: headers not yet sent, so respond with a normal JSON error
        # (no streaming) exactly like the buffered path.
        if resp.status_code >= 400:
            error_text = resp.text
            _write_jsonl(self.server.log_file, {"ts": time.time(), "provider": self.server.provider, "model": payload.get("model"), "upstream_url": upstream_url, "status": resp.status_code, "latency_ms": int((time.time() - started) * 1000), "error": error_text[:1000]})
            _gateway_record_circuit_result(self.server, "chat", payload.get("model", model), resp.status_code, now=time.time())
            friendly = _friendly_error(resp.status_code, error_text)
            payload_error = {"type": "error", "error": friendly}
            trace = _trace_request(self.server, action="proxy.chat", status=resp.status_code, body=body, requested_model=requested_model, routed_model=payload_model, endpoint_mode="dedicated" if route else "serverless", routing_reason="upstream_error", upstream_url=upstream_url, started_at=started, error_category=friendly.get("type") or "api_error", human_message=friendly.get("message") or "")
            return self._json(resp.status_code, _attach_trace(payload_error, trace))
        # OK: commit to the stream and forward tokens incrementally.
        self._responded = True
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        result = _stream_openai_to_anthropic(self.wfile, payload.get("model", model), resp.iter_lines())
        usage = result.get("usage") or {}
        cost = _cost_for_usage(payload.get("model", model), usage, self.server.costs)
        _gateway_record_circuit_result(self.server, "chat", payload.get("model", model), 200, now=time.time())
        record = {"ts": time.time(), "provider": self.server.provider, "requested_model": requested_model, "upstream_model": payload.get("model"), "upstream_url": upstream_url, "status": 200, "latency_ms": int((time.time() - started) * 1000), "stream": True, "cost": cost}
        if token_clamp:
            record["token_clamp"] = token_clamp
        _write_jsonl(self.server.log_file, record)
        _write_jsonl(self.server.cost_file, record)
        _trace_request(self.server, action="proxy.chat", status=200, body=body, requested_model=requested_model, routed_model=payload.get("model"), endpoint_mode="dedicated" if route else "serverless", routing_reason=(token_clamp.get("reason") if isinstance(token_clamp, dict) else "stream"), upstream_url=upstream_url, usage=usage, cost=cost, started_at=started)
        return

    def do_GET(self):
        self._responded = False
        try:
            if self._require_inbound_auth():
                return
            return self._handle_get()
        except Exception as exc:
            self._fail_safe(exc)

    def _handle_get(self):
        self._refresh_models()
        self._refresh_gateway_policy()
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/v1/models":
            available = (parse_qs(parsed.query).get("available") or ["true"])[0].lower()
            availability_filter = "all" if available in {"all", "*"} else ("unavailable" if available in {"false", "0", "no"} else "available")
            return self._json(200, _models_payload(
                self.server.models,
                aliases=self.server.model_aliases,
                records=getattr(self.server, "model_registry_records", None),
                routeable=self.server.models,
                availability_filter=availability_filter,
            ))
        if path == "/v1/claude-do/costs":
            return self._json(200, {
                "provider": self.server.provider,
                "costs_per_mtok": self.server.costs,
                "usage_file": self.server.cost_file,
                "model_config_file": self.server.model_config_file,
                "model_config_loaded": self.server.model_config_loaded,
                "model_config_state": _model_config_state(self.server),
            })
        if path == "/v1/claude-do/capabilities":
            return self._json(200, {
                "provider": self.server.provider,
                "base_url": self.server.base_url,
                "capabilities": self.server.capabilities,
                "models": self.server.models,
                "model_config_file": self.server.model_config_file,
                "model_config_loaded": self.server.model_config_loaded,
                "model_config_state": _model_config_state(self.server),
                "dedicated": _dedicated_lifecycle(_load_dedicated_config().get("model_id")),
                "gateway_policy": _gateway_policy_state(self.server),
            })
        if path == "/v1/claude-do/gateway-policy":
            return self._json(200, _gateway_policy_state(self.server))
        if path == "/v1/claude-do/budget":
            return self._json(200, {
                "budget_file": self.server.budget_file,
                "budgets": _read_json_file(self.server.budget_file, {}),
                "usage": _usage_totals(self.server.cost_file),
            })
        self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "not found"}})

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        self._responded = False
        try:
            if self._require_inbound_auth():
                return
            return self._handle_post()
        except Exception as exc:
            self._fail_safe(exc)

    def _handle_post(self):
        self._refresh_models()
        self._refresh_gateway_policy()
        path = urlparse(self.path).path
        if path == "/v1/claude-do/reload":
            self._refresh_models(force=True)
            self._refresh_gateway_policy()
            return self._json(200, {
                "ok": True,
                "models": self.server.models,
                "model_config_loaded": self.server.model_config_loaded,
                "model_config_state": _model_config_state(self.server),
                "gateway_policy": _gateway_policy_state(self.server),
            })

        if path == "/v1/claude-do/estimate_cost":
            body = self._read_json()
            model = _resolve_model(body.get("model", self.server.default_model), self.server.model_aliases)
            usage = {
                "prompt_tokens": body.get("input_tokens", 0),
                "completion_tokens": body.get("output_tokens", 0),
            }
            return self._json(200, _cost_for_usage(model, usage, self.server.costs))

        if path == "/v1/messages/count_tokens":
            body = self._read_json()
            approx = len(json.dumps(body)) // 4 + 1
            return self._json(200, {"input_tokens": approx})

        if path == "/v1/images/generations":
            body = self._read_json()
            model = _resolve_model(body.get("model", "stable-diffusion-3.5-large"), self.server.model_aliases)
            requested_model = body.get("model", model)
            body["model"] = model
            started = time.time()
            if model not in self.server.models:
                policy_decision = _unavailable_model_policy(self.server, model)
                payload = {
                    "type": "error",
                    "error": {
                        "type": "not_found_error",
                        "message": "model is not configured for Matts Value Set",
                        "model": model,
                        "policy_decision": policy_decision,
                    },
                    "routing": {"requested": requested_model, "used": None, "backend": "proxy", "reason": policy_decision.get("reason") or "model_not_configured", "policy_decision": policy_decision},
                }
                trace = _trace_request(
                    self.server,
                    action="proxy.image",
                    status=404,
                    body=body,
                    requested_model=requested_model,
                    routed_model=model,
                    endpoint_mode="proxy",
                    routing_reason="model_not_configured",
                    started_at=started,
                    error_category="not_found_error",
                    human_message="model is not configured for Matts Value Set",
                    extra={"gateway_policy": policy_decision},
                )
                return self._json(404, _attach_trace(payload, trace))
            budget_error = _budget_error(self.server.cost_file, self.server.budget_file, getattr(self.server, "usage_aggregator", None))
            if budget_error:
                payload = {"type": "error", "error": budget_error}
                trace = _trace_request(
                    self.server,
                    action="proxy.image",
                    status=402,
                    body=body,
                    requested_model=requested_model,
                    routed_model=model,
                    endpoint_mode="budget",
                    routing_reason="budget_exceeded",
                    started_at=started,
                    error_category=budget_error.get("type") or "budget_exceeded",
                    human_message=budget_error.get("message") or "",
                    extra={"gateway_policy": {"decision": "budget_exceeded_rejection", "model": model, "reason": "budget_exceeded"}},
                )
                return self._json(402, _attach_trace(payload, trace))
            rate_limit_error = _gateway_rate_limit_error(self.server, body, model, "images", now=started)
            if rate_limit_error:
                payload = {"type": "error", "error": rate_limit_error}
                trace = _trace_request(
                    self.server,
                    action="proxy.image",
                    status=429,
                    body=body,
                    requested_model=requested_model,
                    routed_model=model,
                    endpoint_mode="gateway",
                    routing_reason="rate_limit_exceeded",
                    started_at=started,
                    error_category="rate_limit_exceeded",
                    human_message=rate_limit_error.get("message") or "",
                    extra={"gateway_policy": {"decision": "rate_limited", "scope": rate_limit_error.get("scope"), "key": rate_limit_error.get("key")}},
                )
                return self._json(429, _attach_trace(payload, trace))
            cached = _gateway_cache_get(self.server, "images", model, body, now=started)
            if cached is not None:
                trace = _trace_request(
                    self.server,
                    action="proxy.image",
                    status=200,
                    body=body,
                    requested_model=requested_model,
                    routed_model=model,
                    endpoint_mode="gateway-cache",
                    routing_reason="cache_hit",
                    started_at=started,
                    extra={"gateway_policy": {"decision": "cache_hit", "route": "images"}},
                )
                cached.setdefault("claude_do", {})["trace_id"] = trace.get("trace_id")
                return self._json(200, cached)
            circuit_error = _gateway_circuit_open_error(self.server, "images", model, now=started)
            if circuit_error:
                payload = {"type": "error", "error": circuit_error}
                trace = _trace_request(
                    self.server,
                    action="proxy.image",
                    status=503,
                    body=body,
                    requested_model=requested_model,
                    routed_model=model,
                    endpoint_mode="gateway",
                    routing_reason="circuit_open",
                    started_at=started,
                    error_category="circuit_open",
                    human_message=circuit_error.get("message") or "",
                    extra={"gateway_policy": {"decision": "circuit_open", "route": "images"}},
                )
                return self._json(503, _attach_trace(payload, trace))
            try:
                resp = requests.post(
                    self.server.images_url,
                    headers={
                        "authorization": "Bearer " + self._token(),
                        "content-type": "application/json",
                    },
                    json=body,
                    timeout=600,
                )
            except Exception as exc:
                _write_jsonl(self.server.log_file, {
                    "ts": time.time(),
                    "provider": self.server.provider,
                    "model": model,
                    "status": 502,
                    "latency_ms": int((time.time() - started) * 1000),
                    "error": str(exc),
                })
                _gateway_record_circuit_result(self.server, "images", model, 502, now=time.time())
                payload = {"type": "error", "error": {"type": "api_error", "message": str(exc)}}
                trace = _trace_request(
                    self.server,
                    action="proxy.image",
                    status=502,
                    body=body,
                    requested_model=requested_model,
                    routed_model=model,
                    endpoint_mode="serverless-image",
                    routing_reason="upstream_exception",
                    upstream_url=self.server.images_url,
                    started_at=started,
                    error_category="network_error",
                    human_message=str(exc),
                )
                return self._json(502, _attach_trace(payload, trace))
            if resp.status_code >= 400:
                _write_jsonl(self.server.log_file, {
                    "ts": time.time(),
                    "provider": self.server.provider,
                    "model": model,
                    "status": resp.status_code,
                    "latency_ms": int((time.time() - started) * 1000),
                    "error": resp.text[:1000],
                })
                _gateway_record_circuit_result(self.server, "images", model, resp.status_code, now=time.time())
                friendly = _friendly_error(resp.status_code, resp.text)
                payload = {"type": "error", "error": friendly}
                trace = _trace_request(
                    self.server,
                    action="proxy.image",
                    status=resp.status_code,
                    body=body,
                    requested_model=requested_model,
                    routed_model=model,
                    endpoint_mode="serverless-image",
                    routing_reason="upstream_error",
                    upstream_url=self.server.images_url,
                    started_at=started,
                    error_category=friendly.get("type") or "api_error",
                    human_message=friendly.get("message") or "",
                )
                return self._json(resp.status_code, _attach_trace(payload, trace))
            data = resp.json()
            image_count = body.get("n") or len(data.get("data") or []) or 1
            cost = _cost_for_images(model, image_count, self.server.costs)
            record = {
                "ts": time.time(),
                "provider": self.server.provider,
                "requested_model": body.get("model"),
                "upstream_model": model,
                "status": resp.status_code,
                "latency_ms": int((time.time() - started) * 1000),
                "stream": False,
                "cost": cost,
            }
            _write_jsonl(self.server.log_file, record)
            _write_jsonl(self.server.cost_file, record)
            _gateway_record_circuit_result(self.server, "images", model, resp.status_code, now=time.time())
            _gateway_cache_store(self.server, "images", model, body, data, now=time.time())
            trace = _trace_request(
                self.server,
                action="proxy.image",
                status=resp.status_code,
                body=body,
                requested_model=requested_model,
                routed_model=model,
                endpoint_mode="serverless-image",
                upstream_url=self.server.images_url,
                cost=cost,
                started_at=started,
            )
            data.setdefault("claude_do", {})["trace_id"] = trace.get("trace_id")
            return self._json(200, data)

        if path != "/v1/messages":
            return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "not found"}})

        body = self._read_json()
        request_started = time.time()
        budget_error = _budget_error(self.server.cost_file, self.server.budget_file, getattr(self.server, "usage_aggregator", None))
        requested_model = body.get("model", self.server.default_model)
        model = _resolve_model(requested_model, self.server.model_aliases)
        model, slo_proof, slo_error = _gateway_select_slo_model(self.server, requested_model, model, body)
        if slo_error:
            payload = {"type": "error", "error": slo_error, "routing": {"requested": requested_model, "used": None, "backend": "gateway", "reason": "slo_route_rejected", "policy_decision": slo_error.get("policy_decision")}}
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=409,
                body=body,
                requested_model=requested_model,
                routed_model=None,
                endpoint_mode="gateway",
                routing_reason="slo_route_rejected",
                started_at=request_started,
                error_category="slo_route_rejected",
                human_message=slo_error.get("message") or "",
                extra={"gateway_policy": slo_error.get("policy_decision")},
            )
            return self._json(409, _attach_trace(payload, trace))
        rate_limit_error = _gateway_rate_limit_error(self.server, body, model, "chat", now=request_started)
        if rate_limit_error:
            payload = {"type": "error", "error": rate_limit_error}
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=429,
                body=body,
                requested_model=requested_model,
                routed_model=model,
                endpoint_mode="gateway",
                routing_reason="rate_limit_exceeded",
                started_at=request_started,
                error_category="rate_limit_exceeded",
                human_message=rate_limit_error.get("message") or "",
                extra={"gateway_policy": {"decision": "rate_limited", "scope": rate_limit_error.get("scope"), "key": rate_limit_error.get("key"), "slo_routing": slo_proof} if slo_proof else {"decision": "rate_limited", "scope": rate_limit_error.get("scope"), "key": rate_limit_error.get("key")}},
            )
            return self._json(429, _attach_trace(payload, trace))
        if budget_error:
            payload = {"type": "error", "error": budget_error}
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=402,
                body=body,
                requested_model=requested_model,
                routed_model=model,
                endpoint_mode="budget",
                routing_reason="budget_exceeded",
                started_at=request_started,
                error_category=budget_error.get("type") or "budget_exceeded",
                human_message=budget_error.get("message") or "",
                extra={"gateway_policy": {"decision": "budget_exceeded_rejection", "model": model, "reason": "budget_exceeded", "slo_routing": slo_proof} if slo_proof else {"decision": "budget_exceeded_rejection", "model": model, "reason": "budget_exceeded"}},
            )
            return self._json(402, _attach_trace(payload, trace))
        if model not in self.server.models:
            policy_decision = _unavailable_model_policy(self.server, model)
            payload = {
                "type": "error",
                "error": {
                    "type": "not_found_error",
                    "message": "model is not configured for MDE LLM-PROXY",
                    "model": model,
                    "policy_decision": policy_decision,
                },
                "routing": {"requested": requested_model, "used": None, "backend": "proxy", "reason": policy_decision.get("reason") or "model_not_configured", "policy_decision": policy_decision},
            }
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=404,
                body=body,
                requested_model=requested_model,
                routed_model=model,
                endpoint_mode="proxy",
                routing_reason="model_not_configured",
                started_at=request_started,
                error_category="not_found_error",
                human_message="model is not configured for MDE LLM-PROXY",
                extra={"gateway_policy": {**policy_decision, "slo_routing": slo_proof} if slo_proof else policy_decision},
            )
            return self._json(404, _attach_trace(payload, trace))
        lifecycle = _dedicated_lifecycle(model)
        if lifecycle and not lifecycle.get("ready"):
            _write_jsonl(self.server.log_file, {
                "ts": time.time(),
                "provider": self.server.provider,
                "model": model,
                "status": 409,
                "latency_ms": 0,
                "error": lifecycle.get("next_step"),
                "dedicated_lifecycle": lifecycle,
            })
            payload = _dedicated_not_ready_error(model, lifecycle)
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=409,
                body=body,
                requested_model=requested_model,
                routed_model=model,
                endpoint_mode="dedicated",
                routing_reason="dedicated_not_ready",
                started_at=request_started,
                error_category="service_unavailable_error",
                human_message=payload.get("error", {}).get("message", ""),
                extra={"dedicated_lifecycle": lifecycle, "gateway_policy": {"decision": "dedicated_wait_not_ready", "model": model, "state": lifecycle.get("state"), "reason": "dedicated_not_ready", "slo_routing": slo_proof} if slo_proof else {"decision": "dedicated_wait_not_ready", "model": model, "state": lifecycle.get("state"), "reason": "dedicated_not_ready"}},
            )
            return self._json(409, _attach_trace(payload, trace))
        route = _dedicated_route(model)
        payload_model = route["model"] if route else model
        payload = _anthropic_to_openai(body, payload_model, self.server.capabilities)
        token_clamp = None
        if route and "qwen3" in str(route["config"].get("model_slug") or "").lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            token_clamp = _apply_dedicated_runtime_limits(payload, route["config"])
        upstream_url = route["url"] if route else self.server.chat_url
        upstream_token = route["token"] if route else self._token()
        upstream_timeout = _request_timeout_seconds(body)
        failover_decision = None
        started = time.time()
        if not body.get("stream"):
            cached = _gateway_cache_get(self.server, "chat", payload_model, payload, now=started)
            if cached is not None:
                trace = _trace_request(
                    self.server,
                    action="proxy.chat",
                    status=200,
                    body=body,
                    requested_model=requested_model,
                    routed_model=payload_model,
                    endpoint_mode="gateway-cache",
                    routing_reason="cache_hit",
                    started_at=started,
                    extra={"gateway_policy": {"decision": "cache_hit", "route": "chat", "slo_routing": slo_proof} if slo_proof else {"decision": "cache_hit", "route": "chat"}},
                )
                if slo_proof:
                    cached.setdefault("claude_do", {})["slo_routing"] = slo_proof
                _attach_trace(cached, trace)
                return self._json(200, cached)
        circuit_error = _gateway_circuit_open_error(self.server, "chat", payload_model, now=started)
        if circuit_error:
            payload_error = {"type": "error", "error": circuit_error}
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=503,
                body=body,
                requested_model=requested_model,
                routed_model=payload_model,
                endpoint_mode="gateway",
                routing_reason="circuit_open",
                started_at=started,
                error_category="circuit_open",
                human_message=circuit_error.get("message") or "",
                extra={"gateway_policy": {"decision": "circuit_open", "route": "chat", "slo_routing": slo_proof} if slo_proof else {"decision": "circuit_open", "route": "chat"}},
            )
            return self._json(503, _attach_trace(payload_error, trace))
        if body.get("stream"):
            # Real streaming: forward tokens as they arrive (true TTFB). Streamed
            # requests forgo context-retry/failover because those require the full
            # response and cannot be applied once bytes have been sent to the client.
            return self._chat_stream(body, payload, upstream_url, upstream_token, model, payload_model, requested_model, route, token_clamp, started)
        try:
            resp = requests.post(
                upstream_url,
                headers={
                    "authorization": "Bearer " + upstream_token,
                    "content-type": "application/json",
                    "user-agent": "matts-claude-code-proxy/1.0",
                },
                json=payload,
                timeout=upstream_timeout,
            )
        except Exception as exc:
            _write_jsonl(self.server.log_file, {
                "ts": time.time(),
                "provider": self.server.provider,
                "model": payload.get("model"),
                "upstream_url": upstream_url,
                "status": 502,
                "latency_ms": int((time.time() - started) * 1000),
                "error": str(exc),
            })
            _gateway_record_model_result(self.server, payload_model, 502, int((time.time() - started) * 1000))
            _gateway_record_circuit_result(self.server, "chat", payload_model, 502, now=time.time())
            payload = {"type": "error", "error": {"type": "api_error", "message": str(exc)}}
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=502,
                body=body,
                requested_model=requested_model,
                routed_model=payload_model,
                endpoint_mode="dedicated" if route else "serverless",
                routing_reason="upstream_exception",
                upstream_url=upstream_url,
                started_at=started,
                error_category="network_error",
                human_message=str(exc),
                extra={"gateway_policy": {"decision": "upstream_exception", "slo_routing": slo_proof}} if slo_proof else None,
            )
            return self._json(502, _attach_trace(payload, trace))

        if resp.status_code == 400 and route:
            retry_tokens = _context_retry_tokens(resp.text)
            try:
                current_tokens = int(payload.get("max_tokens") or 0)
            except (TypeError, ValueError):
                current_tokens = 0
            if retry_tokens and current_tokens and retry_tokens < current_tokens:
                _write_jsonl(self.server.log_file, {
                    "ts": time.time(),
                    "provider": self.server.provider,
                    "model": payload.get("model"),
                    "upstream_url": upstream_url,
                    "status": 400,
                    "latency_ms": int((time.time() - started) * 1000),
                    "error": resp.text[:1000],
                    "retrying_with_max_tokens": retry_tokens,
                })
                retry_payload = dict(payload)
                retry_payload["max_tokens"] = retry_tokens
                started = time.time()
                try:
                    resp = requests.post(
                        upstream_url,
                        headers={
                            "authorization": "Bearer " + upstream_token,
                            "content-type": "application/json",
                            "user-agent": "matts-claude-code-proxy/1.0",
                        },
                        json=retry_payload,
                        timeout=upstream_timeout,
                    )
                    payload = retry_payload
                    token_clamp = {"from": current_tokens, "to": retry_tokens, "reason": "context length retry"}
                except Exception as exc:
                    _write_jsonl(self.server.log_file, {
                        "ts": time.time(),
                        "provider": self.server.provider,
                        "model": retry_payload.get("model"),
                        "upstream_url": upstream_url,
                        "status": 502,
                        "latency_ms": int((time.time() - started) * 1000),
                        "error": str(exc),
                    })
                    _gateway_record_model_result(self.server, retry_payload.get("model"), 502, int((time.time() - started) * 1000))
                    _gateway_record_circuit_result(self.server, "chat", retry_payload.get("model"), 502, now=time.time())
                    payload = {"type": "error", "error": {"type": "api_error", "message": str(exc)}}
                    trace = _trace_request(
                        self.server,
                        action="proxy.chat",
                        status=502,
                        body=body,
                        requested_model=requested_model,
                        routed_model=retry_payload.get("model"),
                        endpoint_mode="dedicated" if route else "serverless",
                        routing_reason="context_retry_exception",
                        upstream_url=upstream_url,
                        started_at=started,
                        error_category="network_error",
                        human_message=str(exc),
                        extra={"gateway_policy": {"decision": "context_retry_exception", "slo_routing": slo_proof}} if slo_proof else None,
                    )
                    return self._json(502, _attach_trace(payload, trace))

        if resp.status_code >= 400 and not route and _gateway_should_failover(self.server, resp.status_code):
            fallback_model = _gateway_text_failover_model(self.server, payload.get("model"), attempted={payload.get("model")})
            if fallback_model:
                original_status = resp.status_code
                original_body = resp.text[:1000]
                _gateway_record_circuit_result(self.server, "chat", payload.get("model"), resp.status_code, now=time.time())
                _gateway_record_model_result(self.server, payload.get("model"), resp.status_code, int((time.time() - started) * 1000))
                _write_jsonl(self.server.log_file, {
                    "ts": time.time(),
                    "provider": self.server.provider,
                    "model": payload.get("model"),
                    "upstream_url": upstream_url,
                    "status": resp.status_code,
                    "latency_ms": int((time.time() - started) * 1000),
                    "error": original_body,
                    "failover_to": fallback_model,
                })
                failover_payload = dict(payload)
                failover_payload["model"] = fallback_model
                started = time.time()
                try:
                    resp = requests.post(
                        upstream_url,
                        headers={
                            "authorization": "Bearer " + upstream_token,
                            "content-type": "application/json",
                            "user-agent": "matts-claude-code-proxy/1.0",
                        },
                        json=failover_payload,
                        timeout=upstream_timeout,
                    )
                    payload = failover_payload
                    failover_decision = {
                        "from_model": model,
                        "from_upstream_model": requested_model,
                        "failed_model": _resolve_model(requested_model, self.server.model_aliases),
                        "to_model": fallback_model,
                        "reason": "provider_%s_failover" % original_status,
                        "original_status": original_status,
                        "original_error": original_body,
                    }
                    if slo_proof:
                        failover_decision["slo_routing"] = slo_proof
                except Exception as exc:
                    _gateway_record_model_result(self.server, fallback_model, 502, int((time.time() - started) * 1000))
                    _gateway_record_circuit_result(self.server, "chat", fallback_model, 502, now=time.time())
                    payload_error = {"type": "error", "error": {"type": "api_error", "message": str(exc)}}
                    trace = _trace_request(
                        self.server,
                        action="proxy.chat",
                        status=502,
                        body=body,
                        requested_model=requested_model,
                        routed_model=fallback_model,
                        endpoint_mode="serverless",
                        routing_reason="failover_exception",
                        upstream_url=upstream_url,
                        started_at=started,
                        error_category="network_error",
                        human_message=str(exc),
                        extra={"gateway_policy": {"decision": "failover_exception", "from": payload.get("model"), "to": fallback_model, "slo_routing": slo_proof} if slo_proof else {"decision": "failover_exception", "from": payload.get("model"), "to": fallback_model}},
                    )
                    return self._json(502, _attach_trace(payload_error, trace))

        if resp.status_code >= 400:
            _write_jsonl(self.server.log_file, {
                "ts": time.time(),
                    "provider": self.server.provider,
                    "model": payload.get("model"),
                    "upstream_url": upstream_url,
                    "status": resp.status_code,
                    "latency_ms": int((time.time() - started) * 1000),
                    "error": resp.text[:1000],
                })
            _gateway_record_circuit_result(self.server, "chat", payload.get("model", model), resp.status_code, now=time.time())
            _gateway_record_model_result(self.server, payload.get("model", model), resp.status_code, int((time.time() - started) * 1000))
            friendly = _friendly_error(resp.status_code, resp.text)
            payload = {"type": "error", "error": friendly}
            trace = _trace_request(
                self.server,
                action="proxy.chat",
                status=resp.status_code,
                body=body,
                requested_model=requested_model,
                routed_model=payload_model,
                endpoint_mode="dedicated" if route else "serverless",
                routing_reason="upstream_error",
                upstream_url=upstream_url,
                started_at=started,
                error_category=friendly.get("type") or "api_error",
                human_message=friendly.get("message") or "",
                extra={"gateway_policy": {"decision": "upstream_error", "slo_routing": slo_proof}} if slo_proof else None,
            )
            return self._json(resp.status_code, _attach_trace(payload, trace))

        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        anthropic = _anthropic_response(
            payload.get("model", model),
            message,
            finish_reason=choice.get("finish_reason"),
            usage=data.get("usage"),
            allowed_tool_names={
                tool.get("function", {}).get("name")
                for tool in payload.get("tools", [])
                if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
            },
        )
        cost = _cost_for_usage(payload.get("model", model), data.get("usage"), self.server.costs)
        output_text = "".join(str(part.get("text") or "") for part in anthropic.get("content", []) if isinstance(part, dict) and part.get("type") == "text")
        streaming_metrics = _streaming_metrics(
            started,
            usage=data.get("usage") or {},
            output_text=output_text,
            cost=cost,
            stream_requested=bool(body.get("stream")),
            client_streaming=bool(body.get("stream")),
            provider_streaming=False,
            chunk_count=sum(1 for part in anthropic.get("content", []) if isinstance(part, dict)),
        )
        anthropic["claude_do"] = {
            "provider": self.server.provider,
            "requested_model": requested_model,
            "upstream_model": payload.get("model"),
            "upstream_url": upstream_url,
            "cost": cost,
            "streaming_metrics": streaming_metrics,
        }
        if failover_decision:
            anthropic["claude_do"]["failover"] = failover_decision
        if slo_proof:
            anthropic["claude_do"]["slo_routing"] = slo_proof
        if token_clamp:
            anthropic["claude_do"]["token_clamp"] = token_clamp
        _gateway_record_circuit_result(self.server, "chat", payload.get("model", model), resp.status_code, now=time.time())
        _gateway_record_model_result(self.server, payload.get("model", model), resp.status_code, int((time.time() - started) * 1000), cost)
        if not body.get("stream"):
            _gateway_cache_store(self.server, "chat", payload.get("model", model), payload, anthropic, now=time.time())
        record = {
            "ts": time.time(),
            "provider": self.server.provider,
            "requested_model": requested_model,
            "upstream_model": payload.get("model"),
            "upstream_url": upstream_url,
            "status": resp.status_code,
            "latency_ms": int((time.time() - started) * 1000),
            "stream": bool(body.get("stream")),
            "streaming_metrics": streaming_metrics,
            "cost": cost,
        }
        if token_clamp:
            record["token_clamp"] = token_clamp
        if slo_proof:
            record["slo_routing"] = slo_proof
        _write_jsonl(self.server.log_file, record)
        _write_jsonl(self.server.cost_file, record)
        trace = _trace_request(
            self.server,
            action="proxy.chat",
            status=resp.status_code,
            body=body,
            requested_model=requested_model,
            routed_model=payload.get("model"),
            endpoint_mode="dedicated" if route else "serverless",
            routing_reason=failover_decision.get("reason") if isinstance(failover_decision, dict) else (token_clamp.get("reason") if isinstance(token_clamp, dict) else ""),
            upstream_url=upstream_url,
            upstream_id=data.get("id") or "",
            usage=data.get("usage") or {},
            cost=cost,
            started_at=started,
            extra={
                "streaming_metrics": streaming_metrics,
                **({"gateway_policy": {"decision": "failover", "details": failover_decision, "slo_routing": slo_proof} if failover_decision else slo_proof} if (failover_decision or slo_proof) else {}),
            },
        )
        _attach_trace(anthropic, trace)

        if body.get("stream"):
            self._responded = True
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.end_headers()
            _write_anthropic_stream(self.wfile, anthropic)
            return

        self._json(200, anthropic)


def _build_arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    # Match the shipped default used by claude-DO.sh, the console, and
    # config/console.json (18081); running the proxy bare previously bound 18080,
    # which the launcher/console would then fail to find.
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--provider", default=os.environ.get("CLAUDE_DO_PROVIDER", "private"))
    parser.add_argument("--default-model", default=os.environ.get("CLAUDE_DO_DEFAULT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--token-file", default=os.path.join(os.path.expanduser("~"), ".mcnf-do-token"))
    parser.add_argument("--base-url", default=DEFAULT_DO_BASE_URL)
    parser.add_argument("--model-aliases", default=os.environ.get("CLAUDE_DO_MODEL_ALIASES", ""))
    parser.add_argument("--models", default=os.environ.get("CLAUDE_DO_MODELS", ""))
    parser.add_argument("--model-config-file", default=os.environ.get("MATTS_MODEL_CONFIG_FILE", _model_config_path()))
    parser.add_argument("--model-access-state-file", default=os.environ.get("MATTS_MODEL_ACCESS_STATE_FILE", _model_access_state_path()))
    parser.add_argument("--capabilities", default=os.environ.get("CLAUDE_DO_CAPABILITIES", ""))
    parser.add_argument("--costs", default=os.environ.get("CLAUDE_DO_COSTS", ""))
    parser.add_argument("--cost-file", default=os.environ.get("CLAUDE_DO_COST_FILE", DEFAULT_COST_FILE))
    parser.add_argument("--budget-file", default=os.environ.get("CLAUDE_DO_BUDGET_FILE", DEFAULT_BUDGET_FILE))
    parser.add_argument("--log-file", default=os.environ.get("CLAUDE_DO_LOG_FILE", DEFAULT_LOG_FILE))
    parser.add_argument("--trace-file", default=os.environ.get("MATTS_TRACE_FILE", DEFAULT_TRACE_FILE))
    parser.add_argument("--gateway-policy-file", default=os.environ.get("MATTS_GATEWAY_POLICY_FILE", DEFAULT_GATEWAY_POLICY_FILE))
    parser.add_argument("--inbound-auth-token", default=os.environ.get("MATTS_PROXY_AUTH_TOKEN", ""))
    parser.add_argument(
        "--allow-unauthenticated-remote",
        action="store_true",
        default=_env_truthy("MATTS_PROXY_ALLOW_UNAUTHENTICATED_REMOTE"),
        help="allow non-loopback binds without proxy inbound authentication",
    )
    return parser


def main():
    args = _build_arg_parser().parse_args()

    fallback_models, fallback_aliases, fallback_costs, bootstrap_warning = _load_bootstrap_fallbacks()
    if bootstrap_warning:
        print("warning: %s" % bootstrap_warning, file=sys.stderr, flush=True)

    allowed, bind_reason = _proxy_bind_allowed(args.host, args.inbound_auth_token, args.allow_unauthenticated_remote)
    if not allowed:
        print("refusing to bind proxy on %s:%d: %s" % (args.host, args.port, bind_reason), file=sys.stderr, flush=True)
        return 2

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.provider = args.provider
    server.default_model = args.default_model
    server.inbound_auth_token = str(args.inbound_auth_token or "").strip()
    server.token_file = args.token_file
    server.capabilities = _load_json_env(args.capabilities, {})
    server.fallback_model_aliases = dict(fallback_aliases)
    server.fallback_model_aliases.update(_load_json_env(args.model_aliases, {}))
    server.fallback_models = _load_json_env(args.models, fallback_models)
    server.fallback_costs = dict(fallback_costs)
    server.fallback_costs.update(_load_json_env(args.costs, {}))
    server.model_aliases = dict(server.fallback_model_aliases)
    server.models = list(server.fallback_models)
    server.model_registry_records = [{"id": model_id, "type": "text", "enabled": True, "access_status": "fallback"} for model_id in server.models]
    server.costs = dict(server.fallback_costs)
    server.model_config_file = args.model_config_file
    server.model_access_state_file = args.model_access_state_file
    server.model_config_loaded = False
    server.model_config_fingerprint = None
    server.model_access_state_fingerprint = None
    server.model_config_last_check_at = 0
    server.model_config_last_loaded_at = 0
    server.model_config_last_error = ""
    server.cost_file = args.cost_file
    server.budget_file = args.budget_file
    server.usage_aggregator = _UsageAggregator()
    server.log_file = args.log_file
    server.trace_file = args.trace_file
    server.gateway_policy_file = args.gateway_policy_file
    server.gateway_policy = dict(DEFAULT_GATEWAY_POLICY)
    server.gateway_policy_loaded = False
    server.gateway_policy_last_error = ""
    server.gateway_policy_last_loaded_at = 0
    server.base_url = args.base_url.rstrip("/")
    server.chat_url = _chat_url(args.base_url)
    server.images_url = _images_url(args.base_url)
    _refresh_model_registry(server, force=True)
    _refresh_gateway_policy(server)
    print("listening on http://%s:%d -> %s" % (args.host, args.port, server.chat_url), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
