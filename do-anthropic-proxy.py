#!/usr/bin/env python3
"""Anthropic Messages API compatibility proxy for Matts Value Set models."""
import argparse
import json
import os
import re
import time
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests


DEFAULT_DO_BASE_URL = "https://inference.do-ai.run"
DEFAULT_MODEL = "deepseek-3.2"
DEFAULT_COST_FILE = os.path.join(os.path.expanduser("~"), ".cache/matts-value-set/usage.jsonl")
DEFAULT_LOG_FILE = "/tmp/matts-value-set-proxy.jsonl"
DEFAULT_BUDGET_FILE = os.path.join(os.path.expanduser("~"), ".cache/matts-value-set/budgets.json")
MATTS_VALUE_SET_MODELS = [
    "deepseek-3.2",
    "deepseek-v4-pro",
    "glm-5",
    "mistral-3-14B",
    "openai-gpt-5.3-codex",
    "stable-diffusion-3.5-large",
]
DEFAULT_ALIASES = {
    "deepseek": "deepseek-3.2",
    "deepseek-v4": "deepseek-v4-pro",
    "glm": "glm-5",
    "mistral": "mistral-3-14B",
    "codex": "openai-gpt-5.3-codex",
    "sd35": "stable-diffusion-3.5-large",
}
DEFAULT_COSTS_PER_MTOK = {
    "deepseek-3.2": {"input": 0.27, "output": 1.1},
    "deepseek-v4-pro": {"input": 0.27, "output": 1.1},
    "glm-5": {"input": 0.27, "output": 1.1},
    "mistral-3-14B": {"input": 0.27, "output": 1.1},
    "openai-gpt-5.3-codex": {"input": 1.75, "output": 14.0},
    "stable-diffusion-3.5-large": {"input": 0.0, "output": 0.0, "image": 0.08},
}


def _model_config_path():
    return os.environ.get(
        "MATTS_MODEL_CONFIG_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "models.json"),
    )


def _model_route_enabled(model):
    if not isinstance(model, dict) or not model.get("id") or model.get("enabled") is False:
        return False
    if model.get("serverless") and model.get("type", "text") == "text":
        return model.get("access_status") == "ok"
    return True


def _load_model_registry(path, fallback_models, fallback_aliases, fallback_costs):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("models") if isinstance(data, dict) else data
    except (OSError, ValueError):
        rows = None
    if not isinstance(rows, list):
        rows = []

    active = [model for model in rows if _model_route_enabled(model)]
    if not active:
        return list(fallback_models), dict(fallback_aliases), dict(fallback_costs), False

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
    return text + image, aliases, costs, True


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
    server.model_config_last_check_at = time.time()
    previous = getattr(server, "model_config_fingerprint", None)
    if not force and _same_model_config_fingerprint(fingerprint, previous):
        return
    models, aliases, costs, loaded = _load_model_registry(
        server.model_config_file,
        server.fallback_models,
        server.fallback_model_aliases,
        server.fallback_costs,
    )
    server.models = models
    server.model_aliases = aliases
    server.costs = costs
    server.model_config_loaded = loaded
    server.model_config_fingerprint = fingerprint
    server.model_config_last_loaded_at = time.time()
    server.model_config_last_error = "" if loaded else (fingerprint.get("error") or "No active route-enabled models loaded from registry.")
    if server.default_model not in server.models and server.models:
        text_models = [model for model in server.models if "image" not in model.lower() and "stable-diffusion" not in model.lower()]
        server.default_model = text_models[0] if text_models else server.models[0]


def _model_config_state(server):
    fingerprint = getattr(server, "model_config_fingerprint", None) or _model_config_fingerprint(getattr(server, "model_config_file", ""))
    current = _model_config_fingerprint(getattr(server, "model_config_file", ""))
    return {
        "file": getattr(server, "model_config_file", ""),
        "loaded": bool(getattr(server, "model_config_loaded", False)),
        "loaded_at": getattr(server, "model_config_last_loaded_at", 0),
        "last_check_at": getattr(server, "model_config_last_check_at", 0),
        "last_error": getattr(server, "model_config_last_error", ""),
        "fingerprint": fingerprint,
        "current_fingerprint": current,
        "stale": not _same_model_config_fingerprint(fingerprint, current),
    }


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


def _read_json_file(path, default):
    if not path:
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


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


def _budget_error(cost_file, budget_file):
    budgets = _read_json_file(budget_file, {})
    totals = _usage_totals(cost_file)
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
    event("message_stop", {"type": "message_stop"})


def _model_display_name(model_id):
    return model_id.replace("-", " ").replace("_", " ").title()


def _models_payload(models, aliases=None):
    out = [{
        "id": model_id,
        "type": "model",
        "display_name": _model_display_name(model_id),
    } for model_id in models]
    seen = {item["id"] for item in out}
    for alias, target in sorted((aliases or {}).items()):
        if target in seen and alias not in seen:
            out.append({
                "id": alias,
                "type": "model",
                "display_name": "%s -> %s" % (_model_display_name(alias), target),
            })
    return {
        "data": out,
        "has_more": False,
        "first_id": out[0]["id"],
        "last_id": out[-1]["id"],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "do-anthropic-proxy/0.1"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def _json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _raw(self, status, data, content_type="application/json"):
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _token(self):
        with open(self.server.token_file, "r", encoding="utf-8") as f:
            return f.read().strip()

    def _refresh_models(self, force=False):
        _refresh_model_registry(self.server, force=force)

    def do_GET(self):
        self._refresh_models()
        path = urlparse(self.path).path
        if path == "/v1/models":
            return self._json(200, _models_payload(self.server.models, aliases=self.server.model_aliases))
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
            })
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
        self._refresh_models()
        path = urlparse(self.path).path
        if path == "/v1/claude-do/reload":
            self._refresh_models(force=True)
            return self._json(200, {
                "ok": True,
                "models": self.server.models,
                "model_config_loaded": self.server.model_config_loaded,
                "model_config_state": _model_config_state(self.server),
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
            body["model"] = model
            started = time.time()
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
                return self._json(502, {"type": "error", "error": {"type": "api_error", "message": str(exc)}})
            if resp.status_code >= 400:
                _write_jsonl(self.server.log_file, {
                    "ts": time.time(),
                    "provider": self.server.provider,
                    "model": model,
                    "status": resp.status_code,
                    "latency_ms": int((time.time() - started) * 1000),
                    "error": resp.text[:1000],
                })
                return self._json(resp.status_code, {"type": "error", "error": _friendly_error(resp.status_code, resp.text)})
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
            return self._json(200, data)

        if path != "/v1/messages":
            return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "not found"}})

        body = self._read_json()
        budget_error = _budget_error(self.server.cost_file, self.server.budget_file)
        if budget_error:
            return self._json(402, {"type": "error", "error": budget_error})
        requested_model = body.get("model", self.server.default_model)
        model = _resolve_model(requested_model, self.server.model_aliases)
        if model not in self.server.models:
            return self._json(404, {
                "type": "error",
                "error": {
                    "type": "not_found_error",
                    "message": "model is not configured for Matts Value Set",
                    "model": model,
                },
            })
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
            return self._json(409, _dedicated_not_ready_error(model, lifecycle))
        route = _dedicated_route(model)
        payload_model = route["model"] if route else model
        payload = _anthropic_to_openai(body, payload_model, self.server.capabilities)
        token_clamp = None
        if route and "qwen3" in str(route["config"].get("model_slug") or "").lower():
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            token_clamp = _apply_dedicated_runtime_limits(payload, route["config"])
        upstream_url = route["url"] if route else self.server.chat_url
        upstream_token = route["token"] if route else self._token()
        started = time.time()
        try:
            resp = requests.post(
                upstream_url,
                headers={
                    "authorization": "Bearer " + upstream_token,
                    "content-type": "application/json",
                    "user-agent": "matts-claude-code-proxy/1.0",
                },
                json=payload,
                timeout=600,
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
            return self._json(502, {"type": "error", "error": {"type": "api_error", "message": str(exc)}})

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
                        timeout=600,
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
                    return self._json(502, {"type": "error", "error": {"type": "api_error", "message": str(exc)}})

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
            return self._json(resp.status_code, {"type": "error", "error": _friendly_error(resp.status_code, resp.text)})

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
        anthropic["claude_do"] = {
            "provider": self.server.provider,
            "requested_model": requested_model,
            "upstream_model": payload.get("model"),
            "upstream_url": upstream_url,
            "cost": cost,
        }
        if token_clamp:
            anthropic["claude_do"]["token_clamp"] = token_clamp
        record = {
            "ts": time.time(),
            "provider": self.server.provider,
            "requested_model": requested_model,
            "upstream_model": payload.get("model"),
            "upstream_url": upstream_url,
            "status": resp.status_code,
            "latency_ms": int((time.time() - started) * 1000),
            "stream": bool(body.get("stream")),
            "cost": cost,
        }
        if token_clamp:
            record["token_clamp"] = token_clamp
        _write_jsonl(self.server.log_file, record)
        _write_jsonl(self.server.cost_file, record)

        if body.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-cache")
            self.end_headers()
            _write_anthropic_stream(self.wfile, anthropic)
            return

        self._json(200, anthropic)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--provider", default=os.environ.get("CLAUDE_DO_PROVIDER", "private"))
    parser.add_argument("--default-model", default=os.environ.get("CLAUDE_DO_DEFAULT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--token-file", default=os.path.join(os.path.expanduser("~"), ".mcnf-do-token"))
    parser.add_argument("--base-url", default=DEFAULT_DO_BASE_URL)
    parser.add_argument("--model-aliases", default=os.environ.get("CLAUDE_DO_MODEL_ALIASES", ""))
    parser.add_argument("--models", default=os.environ.get("CLAUDE_DO_MODELS", ""))
    parser.add_argument("--model-config-file", default=os.environ.get("MATTS_MODEL_CONFIG_FILE", _model_config_path()))
    parser.add_argument("--capabilities", default=os.environ.get("CLAUDE_DO_CAPABILITIES", ""))
    parser.add_argument("--costs", default=os.environ.get("CLAUDE_DO_COSTS", ""))
    parser.add_argument("--cost-file", default=os.environ.get("CLAUDE_DO_COST_FILE", DEFAULT_COST_FILE))
    parser.add_argument("--budget-file", default=os.environ.get("CLAUDE_DO_BUDGET_FILE", DEFAULT_BUDGET_FILE))
    parser.add_argument("--log-file", default=os.environ.get("CLAUDE_DO_LOG_FILE", DEFAULT_LOG_FILE))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.provider = args.provider
    server.default_model = args.default_model
    server.token_file = args.token_file
    server.capabilities = _load_json_env(args.capabilities, {})
    server.fallback_model_aliases = dict(DEFAULT_ALIASES)
    server.fallback_model_aliases.update(_load_json_env(args.model_aliases, {}))
    server.fallback_models = _load_json_env(args.models, MATTS_VALUE_SET_MODELS)
    server.fallback_costs = dict(DEFAULT_COSTS_PER_MTOK)
    server.fallback_costs.update(_load_json_env(args.costs, {}))
    server.model_aliases = dict(server.fallback_model_aliases)
    server.models = list(server.fallback_models)
    server.costs = dict(server.fallback_costs)
    server.model_config_file = args.model_config_file
    server.model_config_loaded = False
    server.model_config_fingerprint = None
    server.model_config_last_check_at = 0
    server.model_config_last_loaded_at = 0
    server.model_config_last_error = ""
    server.cost_file = args.cost_file
    server.budget_file = args.budget_file
    server.log_file = args.log_file
    server.base_url = args.base_url.rstrip("/")
    server.chat_url = _chat_url(args.base_url)
    server.images_url = _images_url(args.base_url)
    _refresh_model_registry(server, force=True)
    print("listening on http://%s:%d -> %s" % (args.host, args.port, server.chat_url), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
