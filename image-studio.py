#!/usr/bin/env python3
"""Pure Python unified web console for Matts Value Set."""
import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import mimetypes
import os
import pty
import re
import secrets
import select
import shlex
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen, urlretrieve

from src.console.handlers.static_handler import StaticHandler
from src.console.handlers.template_handler import TemplateHandler
from src.console.services.health import ConsoleHealthService


EMBEDDED_ACCESS_KEY = ""
DEFAULT_MODEL_REGISTRY = [
    {"id": "deepseek-3.2", "display_name": "DeepSeek 3.2", "type": "text", "provider": "DigitalOcean", "enabled": True, "aliases": ["deepseek"], "pricing": {"input": 0.50, "output": 1.50}, "context_window": 128000},
    {"id": "deepseek-v4-pro", "display_name": "DeepSeek V4 Pro", "type": "text", "provider": "DigitalOcean", "enabled": True, "aliases": ["deepseek-v4"], "pricing": {"input": 1.00, "output": 3.00}, "context_window": 128000},
    {"id": "glm-5", "display_name": "GLM 5", "type": "text", "provider": "DigitalOcean", "enabled": True, "aliases": ["glm"], "pricing": {"input": 1.00, "output": 3.00}, "context_window": 128000},
    {"id": "mistral-3-14B", "display_name": "Mistral 3 14B", "type": "text", "provider": "DigitalOcean", "enabled": True, "aliases": ["mistral"], "pricing": {"input": 0.50, "output": 1.50}, "context_window": 32768},
    {"id": "openai-gpt-5.3-codex", "display_name": "GPT 5.3 Codex", "type": "text", "provider": "DigitalOcean", "enabled": True, "aliases": ["codex"], "pricing": {"input": 2.00, "output": 6.00}, "context_window": 128000},
    {"id": "stable-diffusion-3.5-large", "display_name": "Stable Diffusion 3.5 Large", "type": "image", "provider": "DigitalOcean", "enabled": True, "aliases": ["sd35"], "pricing": {"image": 0.08}, "context_window": 0},
]
APP_VERSION = "1.0.0"
SERVER_STARTED_AT = time.time()
REQUEST_COUNTS = {"GET": 0, "POST": 0}
MODEL_AUTO_ENABLE_MAX_USD = float(os.environ.get("MATTS_MODEL_AUTO_ENABLE_MAX_USD", "0.45"))
SERVERLESS_CATALOG_TTL_SECONDS = int(os.environ.get("MATTS_SERVERLESS_CATALOG_TTL_SECONDS", "3600"))
MODEL_TYPES = {"text", "image", "embedding", "rerank", "audio", "video", "router", "unknown"}
SERVERLESS_MODEL_PRICING = {
    "alibaba-qwen3-32b": {"input": 0.25, "output": 0.55},
    "arcee-trinity-large-thinking": {"input": 0.25, "output": 0.90},
    "deepseek-3.2": {"input": 0.425, "output": 1.36},
    "deepseek-4-flash": {"input": 0.112, "output": 0.224},
    "deepseek-r1-distill-llama-70b": {"input": 0.99, "output": 0.99},
    "deepseek-v4-pro": {"input": 1.392, "output": 2.784},
    "gemma-4-31B-it": {"input": 0.18, "output": 0.50},
    "glm-5": {"input": 0.75, "output": 2.40},
    "glm-5.1": {"input": 0.975, "output": 4.30},
    "glm-5.2": {"input": 1.05, "output": 4.40},
    "kimi-k2.5": {"input": 0.375, "output": 2.025},
    "kimi-k2.6": {"input": 0.76, "output": 3.20},
    "llama-4-maverick": {"input": 0.25, "output": 0.87},
    "llama3.3-70b-instruct": {"input": 0.65, "output": 0.65},
    "mimo-v2.5": {"input": 0.105, "output": 0.28},
    "mimo-v2.5-pro": {"input": 0.60, "output": 3.00},
    "minimax-m2.5": {"input": 0.225, "output": 0.90},
    "mistral-3-14B": {"input": 0.20, "output": 0.20},
    "nemotron-3-nano-omni": {"input": 0.50, "output": 0.90},
    "nemotron-3-ultra-550b": {"input": 0.90, "output": 1.70},
    "nemotron-nano-12b-v2-vl": {"input": 0.20, "output": 0.60},
    "nvidia-nemotron-3-super-120b": {"input": 0.21, "output": 0.455},
    "openai-gpt-4.1": {"input": 2.00, "output": 8.00},
    "openai-gpt-4o": {"input": 2.50, "output": 10.00},
    "openai-gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai-gpt-5": {"input": 1.25, "output": 10.00},
    "openai-gpt-5-mini": {"input": 0.25, "output": 2.00},
    "openai-gpt-5-nano": {"input": 0.05, "output": 0.40},
    "openai-gpt-5.1-codex-max": {"input": 1.25, "output": 10.00},
    "openai-gpt-5.2": {"input": 1.75, "output": 14.00},
    "openai-gpt-5.2-pro": {"input": 21.00, "output": 168.00},
    "openai-gpt-5.3-codex": {"input": 1.75, "output": 14.00},
    "openai-gpt-5.4": {"input": 2.50, "output": 15.00},
    "openai-gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "openai-gpt-5.4-nano": {"input": 0.20, "output": 1.25},
    "openai-gpt-5.4-pro": {"input": 30.00, "output": 180.00},
    "openai-gpt-5.5": {"input": 5.00, "output": 30.00},
    "openai-gpt-oss-120b": {"input": 0.10, "output": 0.70},
    "openai-gpt-oss-20b": {"input": 0.05, "output": 0.45},
    "openai-o1": {"input": 15.00, "output": 60.00},
    "openai-o3": {"input": 2.00, "output": 8.00},
    "openai-o3-mini": {"input": 1.10, "output": 4.40},
    "qwen3-coder-flash": {"input": 0.45, "output": 1.70},
    "qwen3.5-397b-a17b": {"input": 0.385, "output": 2.45},
    "stable-diffusion-3.5-large": {"image": 0.08},
    "all-mini-lm-l6-v2": {"input": 0.009},
    "bge-m3": {"input": 0.02},
    "bge-reranker-v2-m3": {"input": 0.01},
    "e5-large-v2": {"input": 0.02},
    "gte-large-en-v1.5": {"input": 0.09},
    "multi-qa-mpnet-base-dot-v1": {"input": 0.009},
    "qwen3-embedding-0.6b": {"input": 0.04},
}
DEDICATED_STEPS = [
    "Checking DigitalOcean permissions",
    "Matching model to GPU profile",
    "Preparing region and VPC placement",
    "Requesting Dedicated Inference capacity",
    "Waiting for endpoint assignment",
    "Creating access token",
    "Testing endpoint readiness",
    "Registering model globally",
    "Routing new traffic to Dedicated",
]
DEFAULT_DEDICATED_CONFIG = {
    "state": "not_configured",
    "name": "matts-dedicated-inference",
    "version": "1",
    "region": "nyc2",
    "vpc_uuid": "",
    "model_slug": "",
    "model_provider": "",
    "deployment_name": "primary",
    "accelerator_slug": "",
    "accelerator_type": "prefill_decode",
    "scale": 1,
    "enable_public_endpoint": True,
    "inference_id": "",
    "model_id": "dedicated-inference",
    "display_name": "Dedicated Inference",
    "fallback_model": "deepseek-3.2",
    "price_per_hour": 0.0,
    "daily_budget_usd": 0.0,
    "warning_threshold": 0.80,
    "cooldown_threshold": 0.95,
    "idle_warning_seconds": 300,
    "idle_teardown_seconds": 600,
    "auto_rebuild": True,
    "public_endpoint_fqdn": "",
    "private_endpoint_fqdn": "",
    "access_token": "",
    "ca_certificate": "",
    "created_at": 0,
    "run_started_at": 0,
    "last_work_at": 0,
    "last_status_at": 0,
    "last_error": "",
    "raw": {},
}


def model_config_file():
    return Path(os.environ.get("MATTS_MODEL_CONFIG_FILE", Path(__file__).resolve().parent / "config" / "models.json"))


def serverless_catalog_cache_file():
    return Path(os.environ.get("MATTS_SERVERLESS_CATALOG_CACHE_FILE", app_dir() / "serverless-model-catalog.json"))


def dedicated_config_file():
    return Path(os.environ.get("MATTS_DEDICATED_CONFIG_FILE", Path(__file__).resolve().parent / "config" / "dedicated-inference.json"))


def dedicated_events_file():
    return Path(os.environ.get("MATTS_DEDICATED_EVENTS_FILE", app_dir() / "dedicated-events.jsonl"))


def tmux_session_registry_file():
    return Path(os.environ.get("MATTS_TMUX_SESSION_REGISTRY_FILE", app_dir() / "tmux-sessions.json"))


def wallpaper_cache_dir():
    return Path(os.environ.get("MATTS_WALLPAPER_CACHE_DIR", home_dir() / ".cache/matts-value-set/wallpapers"))


def model_enabled_by_default(pricing):
    prices = []
    for key in ("input", "output", "image"):
        if key in pricing:
            try:
                price = float(pricing.get(key) or 0)
                if price > 0:
                    prices.append(price)
            except (TypeError, ValueError):
                return False
    return bool(prices) and all(price < MODEL_AUTO_ENABLE_MAX_USD for price in prices)


def model_route_enabled(model):
    if not model.get("enabled"):
        return False
    if model.get("serverless") and model.get("type") == "text":
        return model.get("access_status") == "ok"
    return True


def _normalized_model(item):
    if not isinstance(item, dict):
        return None
    model_id = str(item.get("id") or "").strip()
    if not model_id:
        return None
    model_type = str(item.get("type") or "text").strip().lower()
    if model_type not in MODEL_TYPES:
        model_type = "unknown"
    aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
    raw_pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    pricing = {key: float(value or 0) for key, value in raw_pricing.items() if key in ("input", "output", "image", "hourly")}
    enabled = bool(item["enabled"]) if "enabled" in item else model_enabled_by_default(pricing)
    normalized = {
        "id": model_id,
        "display_name": str(item.get("display_name") or model_id),
        "type": model_type,
        "provider": str(item.get("provider") or "DigitalOcean"),
        "enabled": enabled,
        "aliases": [str(alias).strip() for alias in aliases if str(alias).strip()],
        "pricing": pricing,
        "context_window": int(item.get("context_window") or 0),
    }
    if isinstance(item.get("dedicated"), dict):
        normalized["dedicated"] = item["dedicated"]
    for key in ("state", "inference_id", "serverless", "owned_by", "created", "max_output_tokens", "pricing_source", "auto_managed", "access_status", "last_error"):
        if item.get(key):
            normalized[key] = item[key]
    return normalized


def load_model_registry(include_disabled=True):
    path = model_config_file()
    models = None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            models = data.get("models") if isinstance(data, dict) else data
        except (OSError, ValueError):
            models = None
    if not isinstance(models, list):
        models = DEFAULT_MODEL_REGISTRY
    normalized = [item for item in (_normalized_model(model) for model in models) if item]
    if not normalized:
        normalized = [_normalized_model(model) for model in DEFAULT_MODEL_REGISTRY]
    return normalized if include_disabled else [model for model in normalized if model_route_enabled(model)]


def save_model_registry(models):
    normalized = [item for item in (_normalized_model(model) for model in models) if item]
    path = model_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": normalized}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def serverless_model_type(model_id):
    lower = str(model_id or "").lower()
    if lower.startswith("router:"):
        return "router"
    if "rerank" in lower:
        return "rerank"
    if "embedding" in lower or lower in {"all-mini-lm-l6-v2", "bge-m3", "e5-large-v2", "gte-large-en-v1.5", "multi-qa-mpnet-base-dot-v1"}:
        return "embedding"
    if "tts" in lower or "audio" in lower:
        return "audio"
    if "t2v" in lower or "video" in lower or lower.startswith("wan"):
        return "video"
    if "image" in lower or "stable-diffusion" in lower or "flux" in lower or "sdxl" in lower:
        return "image"
    return "text"


def display_name_from_model_id(model_id):
    text = str(model_id or "").replace("router:", "router ").replace("/", " ").replace("-", " ").replace("_", " ")
    return " ".join(part.upper() if part.lower() in {"ai", "vl", "tts", "bge", "glm"} else part[:1].upper() + part[1:] for part in text.split())


def _catalog_price_value(item, keys):
    for key in keys:
        if key in item:
            try:
                value = float(item.get(key) or 0)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                continue
    return 0.0


def catalog_pricing_from_item(item):
    if not isinstance(item, dict):
        return {}
    sources = []
    for key in ("pricing", "prices", "rates", "cost", "costs"):
        value = item.get(key)
        if isinstance(value, dict):
            sources.append(value)
    sources.append(item)
    pricing = {}
    for source in sources:
        input_price = _catalog_price_value(source, ("input", "input_usd_per_million", "input_price", "prompt", "prompt_usd_per_million", "prompt_price"))
        output_price = _catalog_price_value(source, ("output", "output_usd_per_million", "output_price", "completion", "completion_usd_per_million", "completion_price"))
        image_price = _catalog_price_value(source, ("image", "image_usd", "image_price", "price_per_image"))
        if input_price:
            pricing["input"] = input_price
        if output_price:
            pricing["output"] = output_price
        if image_price:
            pricing["image"] = image_price
        if pricing:
            break
    return pricing


BRAND_PROFILES = [
    ("anthropic", {"brand": "Anthropic", "origin": "United States", "logo": "https://cdn.simpleicons.org/anthropic/000000", "family": "Claude"}),
    ("openai", {"brand": "OpenAI", "origin": "United States", "logo": "https://cdn.simpleicons.org/openai/000000", "family": "GPT"}),
    ("deepseek", {"brand": "DeepSeek", "origin": "China", "logo": "https://cdn.simpleicons.org/deepseek/4D6BFE", "family": "DeepSeek"}),
    ("mistral", {"brand": "Mistral AI", "origin": "France", "logo": "https://cdn.simpleicons.org/mistralai/FA520F", "family": "Mistral"}),
    ("qwen", {"brand": "Alibaba Qwen", "origin": "China", "logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "family": "Qwen"}),
    ("alibaba", {"brand": "Alibaba Qwen", "origin": "China", "logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "family": "Qwen"}),
    ("glm", {"brand": "Zhipu AI", "origin": "China", "logo": "", "family": "GLM"}),
    ("kimi", {"brand": "Moonshot AI", "origin": "China", "logo": "", "family": "Kimi"}),
    ("llama", {"brand": "Meta", "origin": "United States", "logo": "https://cdn.simpleicons.org/meta/0467DF", "family": "Llama"}),
    ("gemma", {"brand": "Google", "origin": "United States", "logo": "https://cdn.simpleicons.org/google/4285F4", "family": "Gemma"}),
    ("nemotron", {"brand": "NVIDIA", "origin": "United States", "logo": "https://cdn.simpleicons.org/nvidia/76B900", "family": "Nemotron"}),
    ("nvidia", {"brand": "NVIDIA", "origin": "United States", "logo": "https://cdn.simpleicons.org/nvidia/76B900", "family": "Nemotron"}),
    ("minimax", {"brand": "MiniMax", "origin": "China", "logo": "", "family": "MiniMax"}),
    ("mimo", {"brand": "Xiaomi", "origin": "China", "logo": "https://cdn.simpleicons.org/xiaomi/FF6900", "family": "MiMo"}),
    ("arcee", {"brand": "Arcee AI", "origin": "United States", "logo": "", "family": "Arcee"}),
    ("stable-diffusion", {"brand": "Stability AI", "origin": "United Kingdom", "logo": "https://cdn.simpleicons.org/stabilityai/000000", "family": "Stable Diffusion"}),
    ("flux", {"brand": "Black Forest Labs", "origin": "Germany", "logo": "", "family": "FLUX"}),
    ("bge", {"brand": "BAAI", "origin": "China", "logo": "", "family": "BGE"}),
    ("e5", {"brand": "Microsoft", "origin": "United States", "logo": "https://cdn.simpleicons.org/microsoft/5E5E5E", "family": "E5"}),
    ("gte", {"brand": "Alibaba", "origin": "China", "logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "family": "GTE"}),
]


def model_brand_profile(model):
    model_id = str((model or {}).get("id") or "").lower()
    owned_by = str((model or {}).get("owned_by") or "").lower()
    haystack = model_id + " " + owned_by
    for needle, profile in BRAND_PROFILES:
        if needle in haystack:
            return dict(profile)
    return {"brand": (model or {}).get("owned_by") or (model or {}).get("provider") or "DigitalOcean", "origin": "Unknown", "logo": "", "family": "General"}


def readable_model_cost(model):
    pricing = (model or {}).get("pricing") if isinstance((model or {}).get("pricing"), dict) else {}
    parts = []
    if float(pricing.get("input") or 0) > 0:
        parts.append("$%.3g input / 1M tokens" % float(pricing.get("input")))
    if float(pricing.get("output") or 0) > 0:
        parts.append("$%.3g output / 1M tokens" % float(pricing.get("output")))
    if float(pricing.get("image") or 0) > 0:
        parts.append("$%.3g / image" % float(pricing.get("image")))
    if float(pricing.get("hourly") or 0) > 0:
        parts.append("$%.2f / hour" % float(pricing.get("hourly")))
    return " ; ".join(parts) if parts else "Pricing unavailable"


def model_use_case(model, profile):
    model_id = str((model or {}).get("id") or "").lower()
    model_type = str((model or {}).get("type") or "text")
    if model_type == "image":
        return "Image generation and visual ideation; compare against other image models when prompt fidelity or style range matters."
    if model_type in {"embedding", "rerank"}:
        return "Search, retrieval, and ranking infrastructure; compare by vector quality, latency, and index cost rather than chat quality."
    if "coder" in model_id or "codex" in model_id:
        return "Strong fit for coding and agentic tool use; compare with DeepSeek and Qwen models when cost matters."
    if "flash" in model_id or "nano" in model_id or "mimo" in model_id:
        return "Fast, economical everyday work; compare with Mistral or smaller DeepSeek models for latency-sensitive tasks."
    if "r1" in model_id or "thinking" in model_id:
        return "Reasoning-heavy analysis and multi-step problem solving; compare with larger Qwen, GLM, and DeepSeek models."
    if "qwen" in model_id:
        return "Broad multilingual coding and reasoning; compare with DeepSeek for coding and GLM/Kimi for long-form analysis."
    if "deepseek" in model_id:
        return "Practical coding, reasoning, and low-cost automation; compare with Qwen for multilingual work."
    if "glm" in model_id or "kimi" in model_id:
        return "Long-context writing, analysis, and general assistant work; compare with Qwen and Llama for breadth."
    if "llama" in model_id or "gemma" in model_id:
        return "General open-model chat and summarization; compare with Mistral for concise answers and Qwen for coding."
    if "nemotron" in model_id or "nvidia" in model_id:
        return "Enterprise-style instruction following and structured outputs; compare with Llama and OpenAI OSS models."
    if "anthropic" in model_id:
        return "Claude-style writing and careful reasoning when available; compare with OpenAI and Mistral for general chat."
    if "openai" in model_id:
        return "General assistant, coding, and structured output workloads when available; compare with Claude and DeepSeek families."
    if "mistral" in model_id:
        return "Concise general chat, summarization, and fast drafting; compare with DeepSeek and Llama for cost and tone."
    return "%s-family general assistant model; compare with similarly priced models for latency, context, and output style." % profile.get("family", "General")


def model_status_label(model):
    if model_route_enabled(model):
        return "Available"
    access = (model or {}).get("access_status") or "not_checked"
    if access == "forbidden":
        return "Unavailable for this key"
    if access == "rate_limited":
        return "Temporarily rate limited"
    if access == "probe_failed":
        return "Probe failed"
    if (model or {}).get("enabled") is False:
        return "Disabled"
    return "Needs key audit"


def enriched_model_option(model):
    profile = model_brand_profile(model)
    disabled = not model_route_enabled(model)
    name = str((model or {}).get("display_name") or (model or {}).get("id") or "")
    cost = readable_model_cost(model)
    status = model_status_label(model)
    label = "%s - %s - Training origin: %s - %s" % (name, profile["brand"], profile["origin"], cost)
    if disabled:
        label += " - " + status
    return {
        "id": (model or {}).get("id") or "",
        "label": label,
        "display_name": name,
        "type": (model or {}).get("type") or "text",
        "brand": profile["brand"],
        "family": profile["family"],
        "origin": profile["origin"],
        "logo_url": profile["logo"],
        "cost_label": cost,
        "status": status,
        "disabled": disabled,
        "enabled": bool((model or {}).get("enabled")),
        "access_status": (model or {}).get("access_status") or "not_checked",
        "use_case": model_use_case(model, profile),
        "comparison": model_use_case(model, profile),
    }


def model_options(model_type=None, include_disabled=True):
    rows = load_model_registry(include_disabled=True)
    if model_type:
        rows = [model for model in rows if model.get("type") == model_type]
    if not include_disabled:
        rows = [model for model in rows if model_route_enabled(model)]
    return [enriched_model_option(model) for model in rows]


def model_metadata_map():
    return {item["id"]: item for item in model_options(include_disabled=True)}


def model_access_key_candidates():
    candidates = []
    for name in ("MODEL_ACCESS_KEY", "DIGITALOCEAN_MODEL_ACCESS_KEY", "MATTS_VALUE_SET_ACCESS_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            candidates.append({"source": "env:%s" % name, "token": value, "path": ""})
    for path in (token_file(), home_dir() / ".mcnf-do-model-access-token", script_dir() / ".mcnf-do-model-access-token", Path("/root/.mcnf-do-model-access-token")):
        try:
            token = path.read_text(encoding="utf-8").strip()
            if token:
                candidates.append({"source": "file:%s" % path, "token": token, "path": str(path)})
        except OSError:
            continue
    candidates.append({"source": "embedded:fallback", "token": EMBEDDED_ACCESS_KEY, "path": ""})
    return candidates


def active_model_access_key_info():
    item = model_access_key_candidates()[0]
    token = item["token"]
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    masked = token[:6] + "..." + token[-4:] if len(token) > 12 else "***"
    return {
        "source": item["source"],
        "path": item.get("path") or "",
        "fingerprint": fingerprint,
        "masked": masked,
        "length": len(token),
        "configured": bool(token),
    }


def read_model_access_token():
    return model_access_key_candidates()[0]["token"]


def fetch_serverless_catalog():
    token = read_model_access_token()
    req = Request("https://inference.do-ai.run/v1/models", headers={
        "content-type": "application/json",
        "authorization": "Bearer " + token,
        "user-agent": "matts-console/1.0",
    }, method="GET")
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload


def serverless_catalog_payload(force=False):
    path = serverless_catalog_cache_file()
    if not force and path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("fetched_at") or 0) < SERVERLESS_CATALOG_TTL_SECONDS:
                return cached
        except (OSError, ValueError, TypeError):
            pass
    try:
        payload = fetch_serverless_catalog()
        cached = {"ok": True, "fetched_at": time.time(), "source": "https://inference.do-ai.run/v1/models", "payload": payload, "error": ""}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cached, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)
        return cached
    except Exception as exc:
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                cached["ok"] = False
                cached["error"] = str(exc)
                cached["source"] = "cache_after_fetch_error"
                return cached
            except (OSError, ValueError):
                pass
        return {"ok": False, "fetched_at": 0, "source": "fallback", "payload": {"data": []}, "error": str(exc)}


def serverless_registry_entry(item, existing=None):
    model_id = str(item.get("id") or "").strip()
    pricing = catalog_pricing_from_item(item)
    pricing_source = "digitalocean_catalog" if pricing else ""
    if not pricing:
        pricing = dict(SERVERLESS_MODEL_PRICING.get(model_id) or {})
        pricing_source = "digitalocean_pricing_docs_2026_07_01" if pricing else ""
    if not pricing and isinstance((existing or {}).get("pricing"), dict):
        pricing = dict(existing["pricing"])
        pricing_source = (existing or {}).get("pricing_source") or "existing_registry"
    model_type = serverless_model_type(model_id)
    auto_enabled = model_enabled_by_default(pricing)
    if existing:
        enabled = bool(existing.get("enabled"))
    else:
        enabled = auto_enabled
    return {
        "id": model_id,
        "display_name": (existing or {}).get("display_name") or display_name_from_model_id(model_id),
        "type": (existing or {}).get("type") if (existing or {}).get("type") in MODEL_TYPES else model_type,
        "provider": "DigitalOcean",
        "enabled": enabled,
        "aliases": (existing or {}).get("aliases") if isinstance((existing or {}).get("aliases"), list) else [],
        "pricing": pricing,
        "context_window": int(item.get("context_length") or (existing or {}).get("context_window") or 0),
        "serverless": True,
        "owned_by": item.get("owned_by") or (existing or {}).get("owned_by") or "",
        "created": item.get("created") or (existing or {}).get("created") or 0,
        "max_output_tokens": item.get("max_output_tokens") or (existing or {}).get("max_output_tokens") or 0,
        "pricing_source": pricing_source or "unknown",
        "auto_managed": not bool(existing),
        "access_status": (existing or {}).get("access_status") or "not_checked",
        "last_error": (existing or {}).get("last_error") or "",
    }


def probe_serverless_text_model(model_id):
    token = read_model_access_token()
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply only ok"}],
        "max_tokens": 2,
        "stream": False,
    }
    req = Request("https://inference.do-ai.run/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={
        "content-type": "application/json",
        "authorization": "Bearer " + token,
        "user-agent": "matts-console/1.0",
    }, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return True, resp.status, ""
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, exc.code, body[:1000]
    except URLError as exc:
        return False, 502, str(exc.reason)


def validate_serverless_access(models):
    checked = 0
    disabled = 0
    for model in models:
        if not model.get("serverless") or model.get("type") != "text":
            continue
        pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
        if not model_enabled_by_default(pricing):
            continue
        checked += 1
        ok, status, detail = probe_serverless_text_model(model["id"])
        if ok:
            model["enabled"] = True
            model["access_status"] = "ok"
            model["last_error"] = ""
            continue
        model["access_status"] = "forbidden" if int(status) in {401, 403} else ("rate_limited" if int(status) == 429 else "probe_failed")
        model["last_error"] = detail
        if int(status) in {401, 403}:
            model["enabled"] = False
            disabled += 1
    return {"checked": checked, "disabled": disabled}


def audit_model_access_key():
    sync_serverless_model_catalog(force=False, validate_access=False)
    models = load_model_registry(include_disabled=True)
    checked = 0
    allowed = []
    blocked = []
    skipped = []
    for model in models:
        if not model.get("serverless") or model.get("type") != "text":
            continue
        checked += 1
        ok, status, detail = probe_serverless_text_model(model["id"])
        row = {
            "id": model["id"],
            "display_name": model.get("display_name") or model["id"],
            "owned_by": model.get("owned_by") or "",
            "pricing": model.get("pricing") or {},
            "status": int(status),
        }
        if ok:
            model["access_status"] = "ok"
            model["last_error"] = ""
            model["enabled"] = True
            allowed.append(row)
            continue
        access_status = "forbidden" if int(status) in {401, 403} else ("rate_limited" if int(status) == 429 else "probe_failed")
        model["access_status"] = access_status
        model["last_error"] = detail
        row["access_status"] = access_status
        row["error"] = detail
        if int(status) in {401, 403}:
            model["enabled"] = False
            blocked.append(row)
        else:
            skipped.append(row)
    save_model_registry(models)
    refresh_model_globals()
    sync = proxy_sync_payload(force=True)
    return {
        "ok": True,
        "checked_at": time.time(),
        "key": active_model_access_key_info(),
        "checked": checked,
        "allowed_count": len(allowed),
        "blocked_count": len(blocked),
        "skipped_count": len(skipped),
        "allowed": allowed,
        "blocked": blocked,
        "skipped": skipped,
        "active_text_models": TEXT_MODELS,
        "text_model_options": model_options("text", include_disabled=True),
        "image_model_options": model_options("image", include_disabled=True),
        "model_metadata": model_metadata_map(),
        "proxy_sync": sync,
        "note": "DigitalOcean does not expose the selected-model scope for a secret key through the serverless runtime API; this audit verifies access by probing each serverless text model.",
    }


def sync_serverless_model_catalog(force=False, validate_access=False):
    catalog = serverless_catalog_payload(force=force)
    data = catalog.get("payload", {}).get("data", []) if isinstance(catalog.get("payload"), dict) else []
    if not isinstance(data, list) or not data:
        return {"ok": False, "error": catalog.get("error") or "DigitalOcean catalog did not return models", "added": 0, "updated": 0, "total": len(load_model_registry(include_disabled=True)), "catalog": catalog}
    existing_models = load_model_registry(include_disabled=True)
    by_id = {model["id"]: model for model in existing_models}
    added = 0
    updated = 0
    seen_catalog_ids = set()
    for item in data:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        model_id = str(item["id"])
        seen_catalog_ids.add(model_id)
        existing = by_id.get(model_id)
        if existing and isinstance(existing.get("dedicated"), dict):
            continue
        entry = serverless_registry_entry(item, existing=existing)
        if model_enabled_by_default(entry.get("pricing") or {}) and not validate_access and entry.get("access_status") != "forbidden":
            entry["enabled"] = True
        if existing != entry:
            updated += 1 if existing else 0
            added += 0 if existing else 1
            by_id[model_id] = entry
    removed = 0
    for model_id, model in list(by_id.items()):
        if model_id in seen_catalog_ids or not model.get("serverless") or isinstance(model.get("dedicated"), dict):
            continue
        if model.get("access_status") != "removed" or model.get("enabled") is not False:
            model["enabled"] = False
            model["access_status"] = "removed"
            model["last_error"] = "DigitalOcean catalog no longer lists this model."
            by_id[model_id] = model
            removed += 1
    dedicated = [model for model in existing_models if isinstance(model.get("dedicated"), dict) and model["id"] not in by_id]
    merged = list(by_id.values()) + dedicated
    access = validate_serverless_access(merged) if validate_access else {"checked": 0, "disabled": 0}
    merged.sort(key=lambda model: (0 if model.get("serverless") else 1, str(model.get("type") or ""), str(model.get("id") or "")))
    saved = save_model_registry(merged)
    refresh_model_globals()
    return {"ok": True, "added": added, "updated": updated, "removed": removed, "total": len(saved), "catalog": {"ok": catalog.get("ok"), "source": catalog.get("source"), "fetched_at": catalog.get("fetched_at"), "error": catalog.get("error")}, "auto_enable_threshold_usd": MODEL_AUTO_ENABLE_MAX_USD, "access_validation": access, "text_model_options": model_options("text", include_disabled=True), "image_model_options": model_options("image", include_disabled=True), "model_metadata": model_metadata_map()}


def refresh_model_globals():
    global MODEL_REGISTRY, TEXT_MODELS, IMAGE_MODELS, ALL_MODELS, CHAT_COST_PER_MTOK, IMAGE_COST_USD
    MODEL_REGISTRY = load_model_registry(include_disabled=False)
    TEXT_MODELS = [model["id"] for model in MODEL_REGISTRY if model.get("type") == "text"]
    IMAGE_MODELS = [model["id"] for model in MODEL_REGISTRY if model.get("type") == "image"]
    ALL_MODELS = TEXT_MODELS + IMAGE_MODELS
    CHAT_COST_PER_MTOK = {model["id"]: model.get("pricing", {}) for model in MODEL_REGISTRY if model.get("type") == "text"}
    IMAGE_COST_USD = {model["id"]: float((model.get("pricing") or {}).get("image") or 0.0) for model in MODEL_REGISTRY if model.get("type") == "image"}


refresh_model_globals()


def default_text_model():
    if TEXT_MODELS:
        return TEXT_MODELS[0]
    for model in DEFAULT_MODEL_REGISTRY:
        if model.get("type") == "text" and model.get("enabled"):
            return model["id"]
    return "text-model-unavailable"


def default_image_model():
    if IMAGE_MODELS:
        return IMAGE_MODELS[0]
    for model in DEFAULT_MODEL_REGISTRY:
        if model.get("type") == "image" and model.get("enabled"):
            return model["id"]
    return "image-model-unavailable"


def selectable_text_models():
    models = list(TEXT_MODELS)
    for model in load_model_registry(include_disabled=True):
        dedicated = model.get("dedicated") if isinstance(model.get("dedicated"), dict) else {}
        if model.get("type") == "text" and dedicated.get("managed") and model.get("id") not in models:
            models.append(model["id"])
    return models
SIZES = ["512x512", "768x768", "1024x1024", "1024x768", "768x1024"]
STYLES = {
    "none": "",
    "product": "clean premium product photography, sharp detail, controlled studio lighting",
    "editorial": "editorial magazine style, refined composition, natural contrast",
    "cinematic": "cinematic lighting, dramatic depth, film still composition",
    "technical": "precise technical visualization, clear labels, neutral background",
    "illustration": "polished digital illustration, expressive shapes, crisp edges",
    "photoreal": "photorealistic, natural materials, realistic lighting",
    "interface": "modern software interface mockup, precise layout, readable panels, polished controls",
}
TERMINALS = {}
AGENTBOARD_CACHE = {}
ANSI_RE = re.compile(r"\[[0-?]*[ -/]*[@-~]")
PERMISSION_RE = re.compile(
    r"(do you want to (proceed|continue|allow|run)\?|yes,?\s+(and\s+)?(do not|don't|never)\s+ask\s+again|"
    r"\[(approve|accept|allow)\].*\[(reject|deny)\]|\?\s*\[?[yY](es)?/[nN](o)?\]?\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


def home_dir():
    return Path(os.environ.get("HOME") or "/root")


def script_dir():
    return Path(__file__).resolve().parent


def app_dir():
    path = Path(os.environ.get("MATTS_STUDIO_DIR", home_dir() / ".cache/matts-value-set/studio"))
    path.mkdir(parents=True, exist_ok=True)
    (path / "images").mkdir(exist_ok=True)
    return path


def auth_token_file():
    return Path(os.environ.get("MATTS_CONSOLE_AUTH_FILE", app_dir() / "console-auth-token"))


def auth_token():
    env_token = os.environ.get("MATTS_CONSOLE_AUTH_TOKEN")
    if env_token:
        return env_token.strip()
    path = auth_token_file()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    return token


def auth_enabled():
    return os.environ.get("MATTS_CONSOLE_DISABLE_AUTH") != "1"


def token_file():
    return Path(os.environ.get("MATTS_VALUE_SET_TOKEN_FILE", home_dir() / ".mcnf-do-model-access-token"))


def access_key():
    if os.environ.get("MATTS_VALUE_SET_ALLOW_KEY_OVERRIDE") == "1" and os.environ.get("MATTS_VALUE_SET_ACCESS_KEY"):
        return os.environ["MATTS_VALUE_SET_ACCESS_KEY"]
    try:
        existing = token_file().read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    return EMBEDDED_ACCESS_KEY


def write_token():
    path = token_file()
    key = access_key()
    if not key:
        raise SystemExit("Set MATTS_VALUE_SET_ACCESS_KEY or write a model access key to %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    path.chmod(0o600)


def proxy_host():
    return os.environ.get("MATTS_VALUE_SET_PROXY_HOST", "127.0.0.1")


def proxy_port():
    return int(os.environ.get("MATTS_VALUE_SET_PROXY_PORT", "18081"))


def proxy_url(path):
    return "http://%s:%d%s" % (proxy_host(), proxy_port(), path)


def cost_file():
    return Path(os.environ.get("MATTS_VALUE_SET_COST_FILE", home_dir() / ".cache/matts-value-set/usage.jsonl"))


def budget_file():
    return Path(os.environ.get("MATTS_VALUE_SET_BUDGET_FILE", home_dir() / ".cache/matts-value-set/budgets.json"))


def log_file():
    return Path(os.environ.get("MATTS_VALUE_SET_LOG_FILE", "/tmp/matts-value-set-proxy.jsonl"))


def digitalocean_token_file():
    return Path(os.environ.get("DIGITALOCEAN_TOKEN_FILE", home_dir() / ".config/digitalocean/token"))


def digitalocean_token_paths():
    paths = [digitalocean_token_file(), home_dir() / ".mcnf-do-token", script_dir() / ".mcnf-do-token"]
    root_token = Path("/root/.mcnf-do-token")
    if root_token not in paths:
        paths.append(root_token)
    return paths


def digitalocean_token():
    token = os.environ.get("DIGITALOCEAN_TOKEN", "").strip()
    if token:
        return token
    for path in digitalocean_token_paths():
        if path.exists():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    return ""


def digitalocean_account_urn():
    return os.environ.get("DIGITALOCEAN_ACCOUNT_URN", "").strip()


def port_open(host, port):
    sock = socket.socket()
    sock.settimeout(0.25)
    try:
        sock.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def health_service():
    return ConsoleHealthService(
        service="matts-unified-console",
        version=APP_VERSION,
        started_at=SERVER_STARTED_AT,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        port_open=port_open,
        launcher_health=launcher_health,
        auth_enabled=auth_enabled,
        tmux_sessions=tmux_sessions,
        request_counts=REQUEST_COUNTS,
        clock=time.time,
    )


def console_status():
    return health_service().status()


def console_metrics_text():
    return health_service().metrics_text(status=console_status())


def local_addresses():
    addresses = []
    try:
        output = subprocess.check_output(["hostname", "-I"], text=True, timeout=2)
        for item in output.split():
            if item and ":" not in item and not item.startswith("127."):
                addresses.append(item)
    except (OSError, subprocess.SubprocessError):
        pass
    return addresses


def proxy_capabilities_raw():
    try:
        status, payload = request_json("http://%s:%d/v1/claude-do/capabilities" % (proxy_host(), proxy_port()), payload=None, timeout=2, method="GET")
        return status, payload
    except Exception as exc:
        return 599, {"error": str(exc)}


def model_config_fingerprint():
    path = model_config_file()
    try:
        stat = path.stat()
        return {"path": str(path), "exists": True, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
    except OSError as exc:
        return {"path": str(path), "exists": False, "mtime_ns": 0, "size": 0, "error": str(exc)}


def same_model_config_fingerprint(left, right):
    return (
        bool(left)
        and bool(right)
        and left.get("exists") == right.get("exists")
        and left.get("mtime_ns") == right.get("mtime_ns")
        and left.get("size") == right.get("size")
    )


def proxy_in_sync():
    if not port_open(proxy_host(), proxy_port()):
        return False, {"reason": "proxy is not listening"}
    status, payload = proxy_capabilities_raw()
    expected_base = os.environ.get("MATTS_VALUE_SET_BASE_URL", "https://inference.do-ai.run").rstrip("/")
    actual_base = str(payload.get("base_url", "")).rstrip("/") if isinstance(payload, dict) else ""
    actual_models = payload.get("models") if isinstance(payload, dict) else []
    expected_fingerprint = model_config_fingerprint()
    model_state = payload.get("model_config_state") if isinstance(payload, dict) else {}
    actual_fingerprint = model_state.get("fingerprint") if isinstance(model_state, dict) else {}
    registry_seen = (
        isinstance(model_state, dict)
        and model_state.get("loaded")
        and not model_state.get("stale")
        and same_model_config_fingerprint(expected_fingerprint, actual_fingerprint)
    )
    ok = (
        status < 400
        and isinstance(payload, dict)
        and payload.get("provider") == "matts-value-set"
        and actual_base == expected_base
        and actual_models == ALL_MODELS
        and registry_seen
    )
    reason = "in sync" if ok else "proxy config differs from GUI registry"
    if isinstance(model_state, dict) and model_state.get("stale"):
        reason = "proxy has not reloaded the latest model registry file"
    elif isinstance(model_state, dict) and model_state.get("last_error"):
        reason = "proxy model registry load failed: %s" % model_state.get("last_error")
    return ok, {"reason": reason, "status": status, "capabilities": payload, "expected_models": ALL_MODELS, "expected_base_url": expected_base, "expected_model_config": expected_fingerprint}


def stop_proxy():
    tmux_name = os.environ.get("MATTS_VALUE_SET_TMUX_SESSION", "matts-value-set-proxy")
    subprocess.run(["tmux", "kill-session", "-t", tmux_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    for tool, args in (("lsof", ["lsof", "-tiTCP:%d" % proxy_port(), "-sTCP:LISTEN"]), ("fuser", ["fuser", "-n", "tcp", str(proxy_port())])):
        try:
            found = subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).split()
        except (OSError, subprocess.SubprocessError):
            continue
        for pid in found:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        if found:
            time.sleep(0.4)
            break


def start_proxy_if_needed(force=False):
    in_sync, _ = proxy_in_sync()
    if in_sync and not force:
        return
    if force and port_open(proxy_host(), proxy_port()):
        try:
            request_json(proxy_url("/v1/claude-do/reload"), {})
            in_sync, _ = proxy_in_sync()
            if in_sync:
                return
        except Exception:
            pass
    if port_open(proxy_host(), proxy_port()):
        stop_proxy()
    write_token()
    proxy_script = Path(os.environ.get("MATTS_VALUE_SET_PROXY_SCRIPT", script_dir() / "do-anthropic-proxy.py"))
    cmd = [
        sys.executable,
        str(proxy_script),
        "--provider",
        "matts-value-set",
        "--default-model",
        default_text_model(),
        "--host",
        proxy_host(),
        "--port",
        str(proxy_port()),
        "--token-file",
        str(token_file()),
        "--base-url",
        os.environ.get("MATTS_VALUE_SET_BASE_URL", "https://inference.do-ai.run"),
        "--model-config-file",
        str(model_config_file()),
        "--models",
        json.dumps(ALL_MODELS),
        "--cost-file",
        str(cost_file()),
        "--budget-file",
        str(budget_file()),
        "--log-file",
        str(log_file()),
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(50):
        if port_open(proxy_host(), proxy_port()):
            return
        time.sleep(0.1)
    raise RuntimeError("proxy did not start on %s:%d" % (proxy_host(), proxy_port()))


def proxy_sync_payload(force=False):
    start_error = ""
    try:
        start_proxy_if_needed(force=force)
    except Exception as exc:
        start_error = str(exc)
    in_sync, details = proxy_in_sync()
    if start_error:
        details["start_error"] = start_error
    return {
        "listening": port_open(proxy_host(), proxy_port()),
        "in_sync": in_sync,
        "host": proxy_host(),
        "port": proxy_port(),
        "url": "http://%s:%d" % (proxy_host(), proxy_port()),
        "details": details,
    }


def registry_sync_issue_for_model(model):
    in_sync, details = proxy_in_sync()
    if in_sync:
        return None
    details = details if isinstance(details, dict) else {}
    caps = details.get("capabilities") if isinstance(details.get("capabilities"), dict) else {}
    proxy_models = caps.get("models") if isinstance(caps.get("models"), list) else []
    registry_state = caps.get("model_config_state") if isinstance(caps.get("model_config_state"), dict) else {}
    reason = details.get("reason") or "proxy registry is not synchronized"
    selected_loaded = model in proxy_models
    blocking = not selected_loaded
    message = (
        "The selected model '%s' is not loaded by the Claude Code proxy yet. %s. "
        "Use Sync Proxy from Console or wait for the registry reload to finish before sending."
    ) % (model, reason) if blocking else (
        "The proxy registry needs attention (%s), but the selected model '%s' is already loaded and the request can continue."
    ) % (reason, model)
    return {
        "ok": False,
        "blocking": blocking,
        "message": message,
        "reason": reason,
        "selected_model": model,
        "selected_model_loaded": selected_loaded,
        "proxy_models": proxy_models,
        "registry_state": registry_state,
        "expected_models": details.get("expected_models") or [],
        "expected_model_config": details.get("expected_model_config") or {},
    }


def request_json(url, payload=None, timeout=240, method="POST"):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"content-type": "application/json"}, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace"))
        except ValueError:
            detail = {"error": {"message": "provider request failed"}}
        return exc.code, detail
    except URLError as exc:
        return 502, {"error": {"message": str(exc.reason)}}


def do_get(path, token, query=None, timeout=30):
    url = "https://api.digitalocean.com" + path
    if query:
        url += "?" + urlencode(query)
    req = Request(url, headers={
        "content-type": "application/json",
        "authorization": "Bearer " + token,
    }, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace"))
        except ValueError:
            detail = {"error": exc.read().decode("utf-8", errors="replace")}
        return exc.code, detail
    except URLError as exc:
        return 502, {"error": str(exc.reason)}



def do_request(path, token, payload=None, timeout=60, method="GET"):
    url = "https://api.digitalocean.com" + path
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={
        "content-type": "application/json",
        "authorization": "Bearer " + token,
    }, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
        except ValueError:
            detail = {"error": body or exc.reason}
        return exc.code, detail
    except URLError as exc:
        return 502, {"error": str(exc.reason)}


def load_dedicated_config():
    cfg = dict(DEFAULT_DEDICATED_CONFIG)
    path = dedicated_config_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except (OSError, ValueError):
            pass
    return cfg


def save_dedicated_config(cfg):
    merged = dict(DEFAULT_DEDICATED_CONFIG)
    merged.update(cfg or {})
    path = dedicated_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return merged


def append_dedicated_event(state, message, severity="info", details=None):
    event = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ts": time.time(),
        "state": state,
        "severity": severity,
        "message": message,
        "details": details or {},
    }
    path = dedicated_events_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def dedicated_events(limit=80):
    rows = tail_jsonl(dedicated_events_file(), limit=limit)
    rows.sort(key=lambda item: item.get("ts", 0), reverse=True)
    return rows


def dedicated_elapsed_seconds(cfg, now=None):
    now = now or time.time()
    start = float(cfg.get("run_started_at") or 0)
    if not start or cfg.get("state") in {"not_configured", "deleted", "failed"}:
        return 0
    return max(0, int(now - start))


def dedicated_cost_usd(cfg, now=None):
    hourly = float(cfg.get("price_per_hour") or 0)
    return round((dedicated_elapsed_seconds(cfg, now) / 3600.0) * hourly, 8)


def clipped_seconds(start, end, window_start, window_end):
    left = max(float(start), float(window_start))
    right = min(float(end), float(window_end))
    return max(0.0, right - left)


def dedicated_runtime_cost_summary(cfg, now=None):
    now = now or time.time()
    hourly = float(cfg.get("price_per_hour") or 0)
    month_start = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    day_start = now - 86400
    rows = tail_jsonl(dedicated_events_file(), limit=100000)
    rows.sort(key=lambda item: float(item.get("ts") or 0))
    intervals = []
    open_start = None
    for row in rows:
        try:
            ts = float(row.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        state = str(row.get("state") or "")
        message = str(row.get("message") or "")
        if state in {"new", "provisioning", "active"} and (
            "creation accepted" in message.lower() or "state changed" in message.lower()
        ):
            if open_start is None:
                open_start = ts
        if state in {"deleted", "failed"} or (state == "tearing_down" and "destroying dedicated" in message.lower()):
            if open_start is not None and ts >= open_start:
                intervals.append((open_start, ts))
                open_start = None
    if open_start is None and cfg.get("state") in {"new", "creating", "provisioning", "active", "idle_warning", "draining", "cooldown", "tearing_down"}:
        open_start = float(cfg.get("run_started_at") or cfg.get("created_at") or 0) or None
    if open_start is not None:
        intervals.append((open_start, now))
    month_seconds = sum(clipped_seconds(start, end, month_start, now) for start, end in intervals)
    day_seconds = sum(clipped_seconds(start, end, day_start, now) for start, end in intervals)
    return {
        "hourly_usd": hourly,
        "month_seconds": int(month_seconds),
        "last_24h_seconds": int(day_seconds),
        "month_cost_usd": round((month_seconds / 3600.0) * hourly, 8),
        "last_24h_cost_usd": round((day_seconds / 3600.0) * hourly, 8),
        "interval_count": len(intervals),
        "source": "local Dedicated lifecycle events",
    }


def dedicated_idle_seconds(cfg, now=None):
    now = now or time.time()
    last = float(cfg.get("last_work_at") or cfg.get("run_started_at") or 0)
    if not last:
        return 0
    return max(0, int(now - last))


def mask_email(value):
    email = str(value or "")
    if "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked = name[:1] + "*"
    else:
        masked = name[:2] + "***" + name[-1:]
    return masked + "@" + domain


DO_HEALTH_CACHE = {"ts": 0, "payload": None}


def public_json_url(url, timeout=12):
    req = Request(url, headers={"accept": "application/json", "user-agent": "matts-console/1.0"}, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace"))
        except ValueError:
            detail = {"error": exc.reason}
        return exc.code, detail
    except URLError as exc:
        return 502, {"error": str(exc.reason)}


def wallpaper_payload(randomize=False):
    idx = secrets.randbelow(8) if randomize else 0
    status, payload = public_json_url("https://www.bing.com/HPImageArchive.aspx?format=js&idx=%d&n=1&mkt=en-US" % idx, timeout=12)
    fallback = {
        "ok": False,
        "source": "fallback",
        "url": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=2200&q=80",
        "title": "Scenic workspace",
        "copyright": "Fallback scenic background",
        "caption": "Scenic workspace",
        "idx": idx,
        "errors": [],
    }
    if status >= 400 or not isinstance(payload, dict):
        fallback["errors"].append({"status": status, "response": payload})
        return fallback
    images = payload.get("images") if isinstance(payload.get("images"), list) else []
    item = images[0] if images and isinstance(images[0], dict) else {}
    path = str(item.get("url") or "")
    if not path:
        fallback["errors"].append("Bing wallpaper response did not include an image URL.")
        return fallback
    full_url = path if path.startswith("http") else "https://www.bing.com" + path
    image_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(item.get("hsh") or item.get("startdate") or hashlib.sha1(full_url.encode("utf-8")).hexdigest()))[:80]
    return {
        "ok": True,
        "source": "bing_hpimagearchive",
        "url": "/api/wallpaper/image?id=%s&remote=%s" % (quote(image_id), quote(full_url, safe="")),
        "remote_url": full_url,
        "title": item.get("title") or "Daily scenic wallpaper",
        "copyright": item.get("copyright") or "",
        "copyrightlink": item.get("copyrightlink") or "",
        "caption": item.get("copyright") or item.get("title") or "Daily scenic wallpaper",
        "startdate": item.get("startdate") or "",
        "idx": idx,
        "errors": [],
    }


def wallpaper_image_response(remote_url, image_id):
    if not remote_url.startswith("https://www.bing.com/"):
        return HTTPStatus.BAD_REQUEST, b"", "text/plain"
    cache_dir = wallpaper_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urlparse(remote_url).path).suffix or ".jpg"
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", image_id or hashlib.sha1(remote_url.encode("utf-8")).hexdigest())[:80]
    path = cache_dir / (safe_id + suffix)
    if not path.exists():
        req = Request(remote_url, headers={"user-agent": "matts-console/1.0"}, method="GET")
        with urlopen(req, timeout=30) as resp:
            path.write_bytes(resp.read())
    return HTTPStatus.OK, path.read_bytes(), "image/jpeg"


def digitalocean_platform_status():
    status_code, status_payload = public_json_url("https://status.digitalocean.com/api/v2/status.json")
    incidents_code, incidents_payload = public_json_url("https://status.digitalocean.com/api/v2/incidents/unresolved.json")
    result = {
        "reachable": status_code < 400,
        "indicator": "unknown",
        "description": "DigitalOcean status unavailable",
        "updated_at": "",
        "unresolved_incidents": [],
        "errors": [],
    }
    if status_code < 400:
        page = status_payload.get("page") if isinstance(status_payload, dict) else {}
        status = status_payload.get("status") if isinstance(status_payload, dict) else {}
        result.update({
            "indicator": status.get("indicator") or "unknown",
            "description": status.get("description") or "unknown",
            "updated_at": page.get("updated_at") or "",
        })
    else:
        result["errors"].append({"status_status": status_code, "response": status_payload})
    if incidents_code < 400:
        incidents = incidents_payload.get("incidents") if isinstance(incidents_payload, dict) else []
        result["unresolved_incidents"] = [{
            "name": item.get("name"),
            "status": item.get("status"),
            "impact": item.get("impact"),
            "updated_at": item.get("updated_at"),
            "shortlink": item.get("shortlink"),
        } for item in incidents[:5] if isinstance(item, dict)]
    else:
        result["errors"].append({"incidents_status": incidents_code, "response": incidents_payload})
    return result


def digitalocean_health_snapshot():
    now = time.time()
    if DO_HEALTH_CACHE.get("payload") and now - float(DO_HEALTH_CACHE.get("ts") or 0) < 60:
        return DO_HEALTH_CACHE["payload"]
    token = digitalocean_token()
    payload = {
        "configured": bool(token),
        "checked_at": now,
        "platform": digitalocean_platform_status(),
        "account": None,
        "prepay": None,
        "errors": [],
    }
    if not token:
        payload["errors"].append("DigitalOcean token is not configured.")
        DO_HEALTH_CACHE.update({"ts": now, "payload": payload})
        return payload
    status, account = do_get("/v2/account", token, timeout=20)
    if status < 400:
        acct = account.get("account") if isinstance(account, dict) else {}
        payload["account"] = {
            "status": acct.get("status") or "unknown",
            "status_message": acct.get("status_message") or "",
            "email": mask_email(acct.get("email")),
            "email_verified": bool(acct.get("email_verified")),
            "droplet_limit": acct.get("droplet_limit"),
            "floating_ip_limit": acct.get("floating_ip_limit"),
            "team_uuid": acct.get("team_uuid") or "",
        }
    else:
        payload["errors"].append({"account_status": status, "response": account})
    status, balance = do_get("/v2/customers/my/balance", token, timeout=20)
    if status < 400:
        def money_value(key):
            try:
                return float(balance.get(key) or 0)
            except (TypeError, ValueError, AttributeError):
                return 0.0
        account_balance = money_value("account_balance")
        payload["prepay"] = {
            "account_balance": account_balance,
            "month_to_date_balance": money_value("month_to_date_balance"),
            "month_to_date_usage": money_value("month_to_date_usage"),
            "generated_at": balance.get("generated_at") if isinstance(balance, dict) else "",
            "status": "credit_available" if account_balance < 0 else ("payment_due" if account_balance > 0 else "settled"),
        }
    else:
        payload["errors"].append({"balance_status": status, "response": balance})
    DO_HEALTH_CACHE.update({"ts": now, "payload": payload})
    return payload


def dedicated_public_payload(cfg):
    now = time.time()
    clean = dict(cfg)
    if clean.get("access_token"):
        clean["access_token_configured"] = True
        clean["access_token"] = ""
    clean.update({
        "elapsed_seconds": dedicated_elapsed_seconds(cfg, now),
        "idle_seconds": dedicated_idle_seconds(cfg, now),
        "estimated_cost_usd": dedicated_cost_usd(cfg, now),
        "build_age_seconds": max(0, int(now - float(cfg.get("created_at") or now))),
        "status_age_seconds": max(0, int(now - float(cfg.get("last_status_at") or cfg.get("created_at") or now))),
        "token_configured": bool(digitalocean_token()),
        "config_file": str(dedicated_config_file()),
        "events_file": str(dedicated_events_file()),
        "steps": DEDICATED_STEPS,
    })
    budget = float(cfg.get("daily_budget_usd") or 0)
    clean["budget_percent"] = round((clean["estimated_cost_usd"] / budget) * 100, 2) if budget else 0
    return clean


def dedicated_extract_id(response):
    if not isinstance(response, dict):
        return ""
    for key in ("dedicated_inference", "inference", "data"):
        item = response.get(key)
        if isinstance(item, dict) and item.get("id"):
            return str(item.get("id"))
    return str(response.get("id") or "")


def dedicated_extract_resource(response):
    if not isinstance(response, dict):
        return {}
    for key in ("dedicated_inference", "inference", "data"):
        item = response.get(key)
        if isinstance(item, dict):
            return item
    return response


def dedicated_endpoint(cfg):
    endpoint = cfg.get("public_endpoint_fqdn") if cfg.get("enable_public_endpoint") else cfg.get("private_endpoint_fqdn")
    endpoint = str(endpoint or cfg.get("public_endpoint_fqdn") or cfg.get("private_endpoint_fqdn") or "").strip()
    if endpoint and not endpoint.startswith("http"):
        endpoint = "https://" + endpoint
    return endpoint.rstrip("/")


def dedicated_status_message(cfg):
    state = cfg.get("state") or "not_configured"
    model = cfg.get("display_name") or cfg.get("model_id") or "Dedicated Inference"
    server_id = cfg.get("inference_id") or "not assigned yet"
    region = cfg.get("region") or "unknown region"
    gpu = cfg.get("accelerator_slug") or "unknown accelerator"
    endpoint = dedicated_endpoint(cfg)
    if state in {"creating", "new", "provisioning", "updating"}:
        step = "DigitalOcean is still building the Dedicated Inference endpoint."
        if not endpoint:
            step += " A public endpoint has not been assigned yet."
        return "%s is not ready yet. %s Current state: %s. Server: %s. Region/GPU: %s / %s. The request was not sent to the model; refresh Dedicated Inference status or wait for the build to reach active." % (model, step, state, server_id, region, gpu)
    if state in {"failed", "error"}:
        return "%s is unavailable because the Dedicated Inference build failed. Server: %s. Last error: %s" % (model, server_id, cfg.get("last_error") or "DigitalOcean did not provide a detailed error.")
    if state in {"deleted", "tearing_down", "not_configured"}:
        return "%s is not available because the Dedicated Inference instance is %s. Build a server before selecting this model." % (model, state)
    if not endpoint:
        return "%s is marked %s, but no endpoint is available yet. Server: %s. Refresh status before retrying." % (model, state, server_id)
    if not cfg.get("access_token"):
        return "%s has an endpoint, but the access token has not been issued yet. Server: %s. Refresh status before retrying." % (model, server_id)
    return "%s is not ready for requests. Current state: %s. Server: %s." % (model, state, server_id)


def dedicated_not_ready_payload(cfg, requested_model):
    lifecycle = dedicated_public_payload(cfg)
    message = dedicated_status_message(cfg)
    do_health = digitalocean_health_snapshot()
    state = lifecycle.get("state")
    if state in {"failed", "error"}:
        next_step = "Rebuild Dedicated Inference with another available GPU or region, or select a Serverless model."
    elif state in {"deleted", "tearing_down", "not_configured"}:
        next_step = "Build a Dedicated Inference server before selecting this model."
    else:
        next_step = "Wait for DigitalOcean to report active, then the app will register and enable the Dedicated model globally."
    return {
        "error": message,
        "message": message,
        "dedicated": lifecycle,
        "digitalocean": do_health,
        "lifecycle": {
            "requested_model": requested_model,
            "state": lifecycle.get("state"),
            "server_id": lifecycle.get("inference_id"),
            "region": lifecycle.get("region"),
            "model_slug": lifecycle.get("model_slug"),
            "accelerator_slug": lifecycle.get("accelerator_slug"),
            "endpoint_ready": bool(dedicated_endpoint(cfg)),
            "access_token_ready": bool(cfg.get("access_token")),
            "build_age_seconds": lifecycle.get("build_age_seconds"),
            "status_age_seconds": lifecycle.get("status_age_seconds"),
            "last_error": lifecycle.get("last_error") or "",
            "next_step": next_step,
        },
    }


def dedicated_model_entry(cfg, enabled=None):
    hourly = float(cfg.get("price_per_hour") or 0)
    endpoint = dedicated_endpoint(cfg)
    active = cfg.get("state") == "active" and bool(endpoint)
    if enabled is None:
        enabled = active
    return {
        "id": cfg.get("model_id") or "dedicated-inference",
        "display_name": cfg.get("display_name") or "Dedicated Inference",
        "type": "text",
        "provider": "DigitalOcean Dedicated",
        "enabled": bool(enabled),
        "aliases": ["dedicated", "dedicated-inference"],
        "pricing": {"input": 0, "output": 0, "hourly": hourly},
        "context_window": int(cfg.get("context_window") or 0),
        "state": cfg.get("state") or "not_configured",
        "endpoint": endpoint,
        "inference_id": cfg.get("inference_id") or "",
        "dedicated": {
            "managed": True,
            "server_id": cfg.get("inference_id") or "",
            "state": cfg.get("state") or "not_configured",
            "region": cfg.get("region") or "",
            "model_slug": cfg.get("model_slug") or "",
            "accelerator_slug": cfg.get("accelerator_slug") or "",
            "scale": int(cfg.get("scale") or 1),
            "endpoint": endpoint,
            "hourly_usd": hourly,
        },
    }


def register_dedicated_model(cfg, enabled=None):
    entry = dedicated_model_entry(cfg, enabled=enabled)
    models = load_model_registry(include_disabled=True)
    existing = next((m for m in models if m.get("id") == entry["id"]), None)
    models = [m for m in models if m.get("id") != entry["id"]]
    models.append(entry)
    save_model_registry(models)
    refresh_model_globals()
    if existing != entry:
        append_dedicated_event("registering_model", "Updated Dedicated model registry entry", "success", {"model_id": entry["id"], "enabled": entry["enabled"], "state": entry.get("state")})
    return entry


def remove_dedicated_model(cfg):
    model_id = cfg.get("model_id") or "dedicated-inference"
    models = [m for m in load_model_registry(include_disabled=True) if m.get("id") != model_id]
    save_model_registry(models)
    refresh_model_globals()
    append_dedicated_event("tearing_down", "Removed Dedicated model from global registry", "warning", {"model_id": model_id})


def dedicated_preflight(data=None):
    cfg = load_dedicated_config()
    cfg.update({k: v for k, v in (data or {}).items() if k in DEFAULT_DEDICATED_CONFIG})
    errors = []
    warnings = []
    if not digitalocean_token():
        errors.append("Set DIGITALOCEAN_TOKEN or DIGITALOCEAN_TOKEN_FILE for Dedicated Inference automation.")
    for key, label in (("name", "Name"), ("region", "Region"), ("vpc_uuid", "VPC UUID"), ("model_slug", "Model slug"), ("model_provider", "Model provider"), ("accelerator_slug", "Accelerator slug")):
        if not str(cfg.get(key) or "").strip():
            errors.append("%s is required." % label)
    if cfg.get("region") not in {"atl1", "nyc2", "tor1"}:
        warnings.append("DigitalOcean currently documents Dedicated Inference regions as atl1, nyc2, and tor1.")
    budget = float(cfg.get("daily_budget_usd") or 0)
    hourly = float(cfg.get("price_per_hour") or 0)
    if budget and hourly and hourly > budget:
        warnings.append("Selected hourly cost exceeds the configured daily budget.")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "config": dedicated_public_payload(cfg)}


def dedicated_update_from_resource(cfg, resource):
    status = str(resource.get("status") or cfg.get("state") or "provisioning")
    endpoints = resource.get("endpoints") if isinstance(resource.get("endpoints"), dict) else {}
    cfg["raw"] = resource
    cfg["last_status_at"] = time.time()
    latest_public = endpoints.get("public_endpoint_fqdn") or resource.get("public_endpoint_fqdn") or ""
    latest_private = endpoints.get("private_endpoint_fqdn") or resource.get("private_endpoint_fqdn") or ""
    cfg["public_endpoint_fqdn"] = latest_public or (cfg.get("public_endpoint_fqdn") if status in {"active", "ready"} else "")
    cfg["private_endpoint_fqdn"] = latest_private or (cfg.get("private_endpoint_fqdn") if status in {"active", "ready"} else "")
    if status in {"active", "ready"}:
        cfg["state"] = "active"
        if not cfg.get("run_started_at"):
            cfg["run_started_at"] = time.time()
        if not cfg.get("last_work_at"):
            cfg["last_work_at"] = cfg["run_started_at"]
    elif status in {"deleting", "deleted"}:
        cfg["state"] = "tearing_down" if status == "deleting" else "deleted"
    elif status == "error":
        cfg["state"] = "failed"
        cfg["last_error"] = resource.get("error") or "DigitalOcean reported error state"
    elif status:
        cfg["state"] = status
    issue = dedicated_resource_issue(resource)
    if issue:
        cfg["state"] = "failed"
        cfg["last_error"] = issue
    elif str(cfg.get("last_error") or "").startswith("DigitalOcean marked "):
        cfg["last_error"] = ""
    return cfg


def dedicated_resource_issue(resource):
    if not isinstance(resource, dict):
        return ""
    specs = []
    for key in ("pending_deployment_spec", "deployment_spec", "current_deployment_spec", "spec"):
        if isinstance(resource.get(key), dict):
            specs.append(resource[key])
    for spec in specs:
        spec_state = str(spec.get("status") or spec.get("state") or "").strip().lower()
        for deployment in spec.get("model_deployments") or []:
            if not isinstance(deployment, dict):
                continue
            model_slug = deployment.get("model_slug") or deployment.get("provider_model_id") or "model"
            for accelerator in deployment.get("accelerators") or []:
                if not isinstance(accelerator, dict):
                    continue
                state = str(accelerator.get("status") or accelerator.get("state") or "").strip().lower()
                if state in {"invalid", "error", "failed"}:
                    if spec_state in {"", "pending", "provisioning"} and not accelerator.get("accelerator_id"):
                        continue
                    slug = accelerator.get("accelerator_slug") or accelerator.get("accelerator_id") or "accelerator"
                    return "DigitalOcean marked %s for %s as %s. Rebuild with another available GPU or region." % (slug, model_slug, state)
    return ""


def dedicated_status_payload(poll=True):
    cfg = load_dedicated_config()
    token = digitalocean_token()
    if poll and token and cfg.get("inference_id") and cfg.get("state") not in {"deleted", "not_configured"}:
        status, response = do_request("/v2/dedicated-inferences/%s" % quote(str(cfg["inference_id"]), safe=""), token, method="GET")
        if status < 400:
            previous = cfg.get("state")
            cfg = dedicated_update_from_resource(cfg, dedicated_extract_resource(response))
            if cfg.get("state") != previous:
                append_dedicated_event(cfg.get("state"), "DigitalOcean state changed to %s" % cfg.get("state"), "info", {"previous": previous})
            if cfg.get("state") == "active":
                if not cfg.get("access_token"):
                    cfg, _ = dedicated_create_token(cfg)
            if cfg.get("inference_id") and cfg.get("state") not in {"deleted", "not_configured", "tearing_down"}:
                register_dedicated_model(cfg)
            save_dedicated_config(cfg)
        else:
            cfg["last_error"] = json.dumps(response)[:1000]
            save_dedicated_config(cfg)
            append_dedicated_event("status", "Failed to refresh Dedicated status", "error", {"status": status, "response": response})
    return {"dedicated": dedicated_public_payload(cfg), "events": dedicated_events(), "models": models_payload(), "digitalocean": digitalocean_health_snapshot()}


def dedicated_create_token(cfg):
    token = digitalocean_token()
    if not token or not cfg.get("inference_id"):
        return cfg, None
    status, response = do_request("/v2/dedicated-inferences/%s/tokens" % quote(str(cfg["inference_id"]), safe=""), token, {"name": "matts-console"}, method="POST")
    if status < 400:
        item = dedicated_extract_resource(response)
        cfg["access_token"] = item.get("token") or item.get("access_key") or item.get("value") or cfg.get("access_token") or ""
        append_dedicated_event("token_issuing", "Dedicated access token created", "success")
    else:
        append_dedicated_event("token_issuing", "Dedicated access token creation failed", "warning", {"status": status, "response": response})
    return cfg, {"status": status, "response": response}


def dedicated_build(data):
    cfg = load_dedicated_config()
    for key in DEFAULT_DEDICATED_CONFIG:
        if key in data:
            cfg[key] = data[key]
    cfg["scale"] = max(1, int(cfg.get("scale") or 1))
    cfg["price_per_hour"] = float(cfg.get("price_per_hour") or 0)
    cfg["daily_budget_usd"] = float(cfg.get("daily_budget_usd") or 0)
    preflight = dedicated_preflight(cfg)
    append_dedicated_event("preflight", "Checking DigitalOcean permissions and required fields", "info", {"ok": preflight["ok"]})
    if not preflight["ok"]:
        cfg["state"] = "failed"
        cfg["last_error"] = "; ".join(preflight["errors"])
        save_dedicated_config(cfg)
        return HTTPStatus.BAD_REQUEST, {"error": cfg["last_error"], "preflight": preflight, "dedicated": dedicated_public_payload(cfg)}
    cfg["state"] = "creating"
    cfg["created_at"] = time.time()
    cfg["run_started_at"] = 0
    cfg["last_work_at"] = 0
    cfg["last_error"] = ""
    save_dedicated_config(cfg)
    append_dedicated_event("planning", "Build plan accepted", "info", {"region": cfg["region"], "model_slug": cfg["model_slug"], "accelerator_slug": cfg["accelerator_slug"]})
    payload = {
        "spec": {
            "version": int(cfg.get("version") or 1),
            "name": cfg["name"],
            "region": cfg["region"],
            "vpc": {"uuid": cfg["vpc_uuid"]},
            "enable_public_endpoint": bool(cfg.get("enable_public_endpoint")),
            "model_deployments": [{
                "name": cfg.get("deployment_name") or "primary",
                "model_slug": cfg["model_slug"],
                "model_provider": cfg["model_provider"],
                "accelerators": [{
                    "scale": int(cfg.get("scale") or 1),
                    "type": cfg.get("accelerator_type") or "gpu",
                    "accelerator_slug": cfg["accelerator_slug"],
                }],
            }],
        },
    }
    append_dedicated_event("creating", "Requesting Dedicated Inference capacity", "info", {"payload": payload})
    status, response = do_request("/v2/dedicated-inferences", digitalocean_token(), payload, method="POST", timeout=120)
    cfg["raw"] = response
    if status >= 400:
        cfg["state"] = "failed"
        cfg["last_error"] = json.dumps(response)[:1200]
        save_dedicated_config(cfg)
        append_dedicated_event("failed", "DigitalOcean rejected Dedicated build", "error", {"status": status, "response": response})
        return status, {"error": cfg["last_error"], "response": response, "dedicated": dedicated_public_payload(cfg)}
    cfg["inference_id"] = dedicated_extract_id(response)
    create_token = response.get("token") if isinstance(response, dict) and isinstance(response.get("token"), dict) else {}
    if create_token.get("value"):
        cfg["access_token"] = create_token.get("value")
    cfg["state"] = "provisioning"
    save_dedicated_config(cfg)
    register_dedicated_model(cfg, enabled=False)
    append_dedicated_event("provisioning", "Dedicated Inference creation accepted by DigitalOcean", "success", {"inference_id": cfg.get("inference_id"), "status": status})
    if cfg.get("inference_id") and not cfg.get("access_token"):
        cfg, token_result = dedicated_create_token(cfg)
        save_dedicated_config(cfg)
    return HTTPStatus.ACCEPTED, dedicated_status_payload(poll=True)


def dedicated_teardown(data=None):
    cfg = load_dedicated_config()
    remove_dedicated_model(cfg)
    cfg["state"] = "tearing_down"
    cfg["last_error"] = ""
    save_dedicated_config(cfg)
    token = digitalocean_token()
    status = HTTPStatus.ACCEPTED
    response = {"ok": True, "note": "No Dedicated inference id was configured."}
    if token and cfg.get("inference_id"):
        append_dedicated_event("tearing_down", "Destroying Dedicated Inference immediately", "warning", {"inference_id": cfg["inference_id"]})
        status, response = do_request("/v2/dedicated-inferences/%s" % quote(str(cfg["inference_id"]), safe=""), token, method="DELETE", timeout=60)
    if int(status) >= 400:
        cfg["state"] = "failed"
        cfg["last_error"] = json.dumps(response)[:1200]
        append_dedicated_event("failed", "Dedicated teardown failed", "error", {"status": int(status), "response": response})
    else:
        cfg["state"] = "deleted"
        cfg["inference_id"] = ""
        cfg["access_token"] = ""
        cfg["public_endpoint_fqdn"] = ""
        cfg["private_endpoint_fqdn"] = ""
        cfg["run_started_at"] = 0
        cfg["last_work_at"] = 0
        append_dedicated_event("deleted", "Dedicated model removed and teardown requested", "success", {"response": response})
    save_dedicated_config(cfg)
    return status, dedicated_status_payload(poll=False)


def dedicated_policy(data):
    cfg = load_dedicated_config()
    for key in ("daily_budget_usd", "warning_threshold", "cooldown_threshold", "idle_warning_seconds", "idle_teardown_seconds", "auto_rebuild", "fallback_model"):
        if key in data:
            cfg[key] = data[key]
    cfg["daily_budget_usd"] = float(cfg.get("daily_budget_usd") or 0)
    cfg["warning_threshold"] = float(cfg.get("warning_threshold") or 0.8)
    cfg["cooldown_threshold"] = float(cfg.get("cooldown_threshold") or 0.95)
    cfg["idle_warning_seconds"] = int(cfg.get("idle_warning_seconds") or 300)
    cfg["idle_teardown_seconds"] = int(cfg.get("idle_teardown_seconds") or 600)
    save_dedicated_config(cfg)
    append_dedicated_event("policy", "Dedicated policy updated", "success", {"policy": dedicated_public_payload(cfg)})
    return HTTPStatus.OK, dedicated_status_payload(poll=False)


def dedicated_discovery(path):
    token = digitalocean_token()
    if not token:
        return HTTPStatus.BAD_REQUEST, {"error": "DigitalOcean token is not configured"}
    status, response = do_request(path, token, method="GET", timeout=60)
    return status, response


def is_dedicated_model(model):
    cfg = load_dedicated_config()
    return bool(model and model == cfg.get("model_id"))


def dedicated_chat_completion(data, cfg):
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    fallback = cfg.get("fallback_model") if cfg.get("fallback_model") in TEXT_MODELS else default_text_model()
    endpoint = dedicated_endpoint(cfg)
    if cfg.get("state") != "active" or not endpoint or not cfg.get("access_token"):
        payload = dedicated_not_ready_payload(cfg, data.get("model"))
        append_dedicated_event("waiting", "Dedicated request blocked because endpoint is not ready", "warning", payload.get("lifecycle"))
        return HTTPStatus.CONFLICT, payload
    payload = {
        "model": cfg.get("model_slug") or data.get("model"),
        "messages": messages,
        "max_tokens": max(1, min(8192, int(data.get("max_tokens") or 512))),
        "stream": False,
    }
    if "qwen3" in str(cfg.get("model_slug") or "").lower():
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if data.get("temperature") not in (None, ""):
        payload["temperature"] = float(data["temperature"])
    req = Request(endpoint + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={
        "content-type": "application/json",
        "authorization": "Bearer " + cfg.get("access_token"),
        "user-agent": "matts-console/1.0",
    }, method="POST")
    try:
        with urlopen(req, timeout=240) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8", errors="replace"))
        except ValueError:
            error = {"error": exc.reason}
        append_dedicated_event("fallback", "Dedicated request failed; routed chat to Serverless", "warning", {"status": exc.code, "response": error})
        status, fallback_payload = serverless_chat_completion(data, fallback, allow_unregistered=True)
        if isinstance(fallback_payload, dict):
            fallback_payload["routing"] = {"requested": data.get("model"), "used": fallback, "reason": "Dedicated request failed", "backend": "serverless"}
        return status, fallback_payload
    except URLError as exc:
        append_dedicated_event("fallback", "Dedicated endpoint unreachable; routed chat to Serverless", "warning", {"error": str(exc.reason)})
        status, fallback_payload = serverless_chat_completion(data, fallback, allow_unregistered=True)
        if isinstance(fallback_payload, dict):
            fallback_payload["routing"] = {"requested": data.get("model"), "used": fallback, "reason": "Dedicated endpoint unreachable", "backend": "serverless"}
        return status, fallback_payload
    text = ""
    choices = raw.get("choices") if isinstance(raw, dict) else []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
        text = message.get("content") or choices[0].get("text") or ""
    cfg["last_work_at"] = time.time()
    save_dedicated_config(cfg)
    append_dedicated_event("active", "Dedicated served chat request", "success", {"model": cfg.get("model_id")})
    usage = raw.get("usage") if isinstance(raw, dict) else {}
    return HTTPStatus.OK, {"text": text, "raw": raw, "usage": usage or {}, "cost": {"total_cost_usd": dedicated_cost_usd(cfg)}, "routing": {"requested": data.get("model"), "used": cfg.get("model_id"), "backend": "dedicated"}}

def history_path():
    return app_dir() / "history.jsonl"


def read_history(limit=300):
    rows = []
    path = history_path()
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    rows.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return rows[:limit]


def append_history(record):
    with history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def build_prompt(data):
    prompt = (data.get("prompt") or "").strip()
    builder = data.get("builder") if isinstance(data.get("builder"), dict) else {}
    parts = []
    for key in ("subject", "environment", "lighting", "camera", "mood", "materials", "palette"):
        value = (builder.get(key) or "").strip()
        if value:
            parts.append(value)
    if parts:
        prompt = ", ".join([prompt] + parts) if prompt else ", ".join(parts)
    style = data.get("style") or "none"
    if STYLES.get(style):
        prompt = prompt + ", " + STYLES[style] if prompt else STYLES[style]
    negative = (data.get("negative_prompt") or "").strip()
    if negative:
        prompt += ". Avoid: " + negative
    source_prompt = (data.get("source_prompt") or "").strip()
    iteration = (data.get("iteration") or "").strip()
    if source_prompt and iteration:
        prompt = "%s. Revise with: %s" % (source_prompt, iteration)
    return prompt.strip()


def save_image_item(item, image_id):
    image_dir = app_dir() / "images"
    if item.get("b64_json"):
        data = base64.b64decode(item["b64_json"])
        ext = ".png"
    elif item.get("url"):
        with urlopen(item["url"], timeout=240) as resp:
            data = resp.read()
            ext = mimetypes.guess_extension(resp.headers.get_content_type()) or ".png"
    else:
        raise ValueError("image response did not include b64_json or url")
    out = image_dir / ("%s%s" % (image_id, ext))
    out.write_bytes(data)
    return out


def generate_images(data):
    start_proxy_if_needed()
    model = data.get("model") or default_image_model()
    if model not in IMAGE_MODELS:
        return HTTPStatus.BAD_REQUEST, {"error": "unknown image model"}
    prompt = build_prompt(data)
    if not prompt:
        return HTTPStatus.BAD_REQUEST, {"error": "prompt is required"}
    try:
        count = max(1, min(4, int(data.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    size = data.get("size") if data.get("size") in SIZES else "1024x1024"
    payload = {"model": model, "prompt": prompt, "size": size, "n": count}
    if str(data.get("seed") or "").strip():
        payload["seed"] = str(data["seed"]).strip()
    status, response = request_json(proxy_url("/v1/images/generations"), payload)
    if status >= 400:
        return status, response
    records = []
    for item in response.get("data") or []:
        image_id = uuid.uuid4().hex
        path = save_image_item(item, image_id)
        record = {
            "id": image_id,
            "created_at": time.time(),
            "model": model,
            "prompt": prompt,
            "negative_prompt": data.get("negative_prompt") or "",
            "style": data.get("style") or "none",
            "size": size,
            "seed": data.get("seed") or "",
            "cost_usd": IMAGE_COST_USD.get(model, 0.0),
            "filename": path.name,
        }
        append_history(record)
        records.append(record)
    return HTTPStatus.OK, {"images": records}


def serverless_chat_completion(data, model, allow_unregistered=False):
    start_proxy_if_needed()
    if not allow_unregistered and model not in TEXT_MODELS:
        return HTTPStatus.BAD_REQUEST, {"error": "unknown text model"}
    registry_issue = registry_sync_issue_for_model(model)
    if registry_issue and registry_issue.get("blocking"):
        return HTTPStatus.CONFLICT, {
            "error": registry_issue["message"],
            "message": registry_issue["message"],
            "registry_sync": registry_issue,
            "routing": {"requested": model, "used": None, "backend": "serverless", "reason": "registry_sync_blocked"},
        }
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    if not messages:
        return HTTPStatus.BAD_REQUEST, {"error": "message is required"}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max(1, min(8192, int(data.get("max_tokens") or 512))),
        "stream": False,
    }
    if data.get("temperature") not in (None, ""):
        payload["temperature"] = float(data["temperature"])
    status, response = request_json(proxy_url("/v1/messages"), payload, timeout=240)
    if status >= 400:
        return status, response
    text = "".join(part.get("text", "") for part in response.get("content", []) if isinstance(part, dict))
    input_text = "\n".join(str(msg.get("content") or "") for msg in messages if isinstance(msg, dict))
    routing = {"requested": model, "used": model, "backend": "serverless"}
    if registry_issue:
        routing["reason"] = "registry_sync_warning"
        routing["registry_sync"] = registry_issue
    return HTTPStatus.OK, {"text": text, "raw": response, "usage": response.get("usage") or {}, "cost": _chat_cost_usd(model, input_text, text), "routing": routing}


def chat_completion(data):
    model = data.get("model") or default_text_model()
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    if not messages:
        return HTTPStatus.BAD_REQUEST, {"error": "message is required"}
    if is_dedicated_model(model):
        dedicated_status_payload(poll=True)
        return dedicated_chat_completion(data, load_dedicated_config())
    return serverless_chat_completion(data, model)


def proxy_get(path):
    start_proxy_if_needed()
    return request_json(proxy_url(path), payload=None, timeout=10, method="GET")


def tail_jsonl(path, limit=80):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            rows.append({"raw": line})
    return rows


def parse_date(value, default):
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return default


def local_usage_report(start_date, end_date):
    rows = tail_jsonl(cost_file(), limit=100000)
    daily = {}
    by_model = {}
    total = 0.0
    for row in rows:
        try:
            day = datetime.datetime.fromtimestamp(float(row.get("ts", 0))).date()
        except (TypeError, ValueError, OSError):
            continue
        if day < start_date or day > end_date:
            continue
        cost = float((row.get("cost") or {}).get("total_cost_usd") or 0.0)
        model = (row.get("upstream_model") or row.get("requested_model") or "unknown")
        total += cost
        key = day.isoformat()
        daily[key] = round(daily.get(key, 0.0) + cost, 8)
        by_model[model] = round(by_model.get(model, 0.0) + cost, 8)
    return {
        "total_usd": round(total, 8),
        "daily": [{"date": key, "amount_usd": value} for key, value in sorted(daily.items())],
        "by_model": [{"model": key, "amount_usd": value} for key, value in sorted(by_model.items(), key=lambda item: item[1], reverse=True)],
    }


def local_usage_since(since_ts, now=None):
    now = now or time.time()
    total = 0.0
    for row in tail_jsonl(cost_file(), limit=100000):
        try:
            ts = float(row.get("ts", 0))
        except (TypeError, ValueError):
            continue
        if ts < since_ts or ts > now:
            continue
        total += float((row.get("cost") or {}).get("total_cost_usd") or 0.0)
    return round(total, 8)


def insight_rows(insights):
    if not isinstance(insights, dict):
        return []
    for key in ("insights", "billing_insights", "data", "items"):
        rows = insights.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def insight_amount(row):
    for key in ("amount", "amount_usd", "cost", "cost_usd", "total", "total_usd"):
        try:
            return float(row.get(key))
        except (TypeError, ValueError):
            continue
    return 0.0


def digitalocean_insights_total(token, account_urn, start_date, end_date):
    if not token or not account_urn:
        return None, "missing_account_urn"
    path = "/v2/billing/%s/insights/%s/%s" % (
        quote(account_urn, safe=":"),
        start_date.isoformat(),
        end_date.isoformat(),
    )
    status, payload = do_get(path, token, {"per_page": 100, "page": 1}, timeout=30)
    if status >= 400:
        return None, {"status": status, "response": payload}
    total = sum(insight_amount(row) for row in insight_rows(payload))
    return round(total, 8), "digitalocean_billing_insights"


def cost_summary_payload():
    now = time.time()
    health = digitalocean_health_snapshot()
    prepay = health.get("prepay") if isinstance(health, dict) else {}
    cfg = load_dedicated_config()
    dedicated = dedicated_runtime_cost_summary(cfg, now)
    local_24h = local_usage_since(now - 86400, now)
    token = digitalocean_token()
    account_urn = digitalocean_account_urn()
    today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).date()
    day_total, day_source = digitalocean_insights_total(token, account_urn, today - datetime.timedelta(days=1), today)
    if day_total is None:
        day_total = round(local_24h + dedicated["last_24h_cost_usd"], 8)
        day_source = "local_proxy_plus_dedicated_estimate"
    month_total = None
    if isinstance(prepay, dict) and isinstance(prepay.get("month_to_date_usage"), (int, float)):
        month_total = float(prepay.get("month_to_date_usage"))
    return {
        "checked_at": now,
        "digitalocean_configured": bool(token),
        "account_urn_configured": bool(account_urn),
        "month_to_date_total_usd": month_total,
        "last_24h_total_usd": day_total,
        "last_24h_source": day_source,
        "dedicated_month_to_date_usd": dedicated["month_cost_usd"],
        "dedicated_last_24h_usd": dedicated["last_24h_cost_usd"],
        "dedicated_runtime": dedicated,
        "local_proxy_last_24h_usd": local_24h,
        "digitalocean": {
            "account": health.get("account") if isinstance(health, dict) else None,
            "prepay": prepay,
            "errors": health.get("errors", []) if isinstance(health, dict) else [],
        },
    }


def digitalocean_report(data):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    days = max(1, min(31, int(data.get("days") or 7)))
    start_date = parse_date(data.get("start_date"), today - datetime.timedelta(days=days - 1))
    end_date = parse_date(data.get("end_date"), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    token = str(data.get("do_token") or "").strip() or digitalocean_token()
    account_urn = str(data.get("account_urn") or "").strip() or digitalocean_account_urn()
    report = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": (end_date - start_date).days + 1,
        "digitalocean_configured": bool(token),
        "account_urn": account_urn,
        "local_usage": local_usage_report(start_date, end_date),
        "balance": None,
        "billing_history": None,
        "insights": None,
        "errors": [],
        "docs": {
            "billing": "https://docs.digitalocean.com/reference/api/reference/billing/",
            "spend_by_date_range": "https://docs.digitalocean.com/platform/billing/spend-by-date-range/",
        },
    }
    if not token:
        report["errors"].append("Set DIGITALOCEAN_TOKEN or DIGITALOCEAN_TOKEN_FILE for DigitalOcean billing data. Required scope: billing:read.")
        return report
    status, balance = do_get("/v2/customers/my/balance", token)
    if status < 400:
        report["balance"] = balance
    else:
        report["errors"].append({"balance_status": status, "response": balance})
    status, history = do_get("/v2/customers/my/billing_history", token, {"per_page": 50})
    if status < 400:
        report["billing_history"] = history
    else:
        report["errors"].append({"billing_history_status": status, "response": history})
    if account_urn:
        path = "/v2/billing/%s/insights/%s/%s" % (
            quote(account_urn, safe=":"),
            start_date.isoformat(),
            end_date.isoformat(),
        )
        status, insights = do_get(path, token, {"per_page": 100, "page": 1})
        if status < 400:
            report["insights"] = insights
        else:
            report["errors"].append({"insights_status": status, "response": insights})
    else:
        report["errors"].append("Set DIGITALOCEAN_ACCOUNT_URN, for example do:team:uuid, to load daily spend insights.")
    return report


def models_payload(refresh_catalog=True):
    catalog_sync = sync_serverless_model_catalog(force=False) if refresh_catalog else None
    return {
        "config_file": str(model_config_file()),
        "models": load_model_registry(include_disabled=True),
        "active_text_models": TEXT_MODELS,
        "selectable_text_models": selectable_text_models(),
        "text_model_options": model_options("text", include_disabled=True),
        "image_model_options": model_options("image", include_disabled=True),
        "model_metadata": model_metadata_map(),
        "active_image_models": IMAGE_MODELS,
        "proxy_sync": proxy_sync_payload(force=False),
        "serverless_catalog": catalog_sync,
        "auto_enable_threshold_usd": MODEL_AUTO_ENABLE_MAX_USD,
        "model_access_key": active_model_access_key_info(),
    }


def save_models_payload(data):
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return HTTPStatus.BAD_REQUEST, {"error": "models must be a list"}
    normalized = [item for item in (_normalized_model(model) for model in models) if item]
    ids = [model["id"] for model in normalized]
    if len(ids) != len(set(ids)):
        return HTTPStatus.BAD_REQUEST, {"error": "model ids must be unique"}
    if not any(model.get("enabled") and model.get("type") == "text" for model in normalized):
        return HTTPStatus.BAD_REQUEST, {"error": "at least one text model must remain enabled"}
    saved = save_model_registry(normalized)
    refresh_model_globals()
    sync = proxy_sync_payload(force=True)
    return HTTPStatus.OK, {"models": saved, "active_text_models": TEXT_MODELS, "selectable_text_models": selectable_text_models(), "text_model_options": model_options("text", include_disabled=True), "image_model_options": model_options("image", include_disabled=True), "model_metadata": model_metadata_map(), "active_image_models": IMAGE_MODELS, "config_file": str(model_config_file()), "proxy_sync": sync, "auto_enable_threshold_usd": MODEL_AUTO_ENABLE_MAX_USD}


def save_budget(data):
    allowed = {}
    for key in ("daily_usd", "monthly_usd", "total_usd"):
        value = data.get(key)
        if value in (None, ""):
            continue
        allowed[key] = float(value)
    budget_file().parent.mkdir(parents=True, exist_ok=True)
    budget_file().write_text(json.dumps(allowed, indent=2) + "\n", encoding="utf-8")
    budget_file().chmod(0o600)
    return allowed


def delete_history_item(image_id):
    path = history_path()
    if not path.exists():
        return False
    original = read_history(limit=100000)
    kept = []
    removed = None
    for row in original:
        if row.get("id") == image_id:
            removed = row
        else:
            kept.append(row)
    with path.open("w", encoding="utf-8") as f:
        for row in reversed(kept):
            f.write(json.dumps(row, sort_keys=True) + "\n")
    if removed:
        try:
            (app_dir() / "images" / removed["filename"]).unlink()
        except OSError:
            pass
    return bool(removed)


# ── Chat persistence ──────────────────────────────────────────────────────────


def chats_dir():
    path = app_dir() / "chats"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _estimate_tokens(text):
    """Simple heuristic: words * 1.3 gives a rough token count."""
    return max(1, int(len(str(text or "").split()) * 1.3))


def _chat_cost_usd(model, input_text, output_text):
    rates = CHAT_COST_PER_MTOK.get(model, {})
    in_tokens = _estimate_tokens(input_text)
    out_tokens = _estimate_tokens(output_text)
    in_cost = in_tokens * float(rates.get("input", 0.0)) / 1_000_000
    out_cost = out_tokens * float(rates.get("output", 0.0)) / 1_000_000
    return {
        "input_tokens_est": in_tokens,
        "output_tokens_est": out_tokens,
        "total_tokens_est": in_tokens + out_tokens,
        "input_cost_usd": round(in_cost, 8),
        "output_cost_usd": round(out_cost, 8),
        "total_cost_usd": round(in_cost + out_cost, 8),
    }


def chat_filename(chat_id):
    return chats_dir() / ("chat_%s.json" % chat_id)


def _make_title(messages):
    """Use the first user message (first 60 chars) as title."""
    for msg in (messages or []):
        if msg.get("role") == "user":
            text = str(msg.get("content") or "").strip()
            if text:
                return text[:60]
    return "Untitled"


def save_chat(data):
    now = time.time()
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    model = data.get("model") or default_text_model()
    chat_id = data.get("id") or ("chat_%d_%s" % (now, uuid.uuid4().hex[:12]))
    title = data.get("title") or _make_title(messages)

    # Stamp each message with timestamp and token estimate if missing
    for msg in messages:
        if not msg.get("timestamp"):
            msg["timestamp"] = now
        if not msg.get("tokens"):
            msg["tokens"] = _estimate_tokens(msg.get("content") or "")

    # Compute total cost from user-assistant pairs
    running_cost = 0.0
    in_text = ""
    for msg in messages:
        if msg.get("role") == "user":
            in_text += (msg.get("content") or "") + " "
        elif msg.get("role") == "assistant":
            out_text = msg.get("content") or ""
            cost_info = _chat_cost_usd(model, in_text, out_text)
            running_cost += cost_info["total_cost_usd"]
            in_text = ""

    running_tokens = sum(int(m.get("tokens", 0)) for m in messages)

    doc = {
        "id": chat_id,
        "created_at": data.get("created_at") or now,
        "updated_at": now,
        "model": model,
        "messages": messages,
        "title": title,
        "total_tokens": running_tokens,
        "total_cost_usd": round(running_cost, 8),
    }
    path = chat_filename(chat_id)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def list_chats():
    result = []
    directory = chats_dir()
    for path in sorted(directory.glob("chat_*.json"), reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        result.append({
            "id": doc.get("id", path.stem),
            "title": doc.get("title", "Untitled")[:60],
            "model": doc.get("model", ""),
            "created_at": doc.get("created_at", 0),
            "updated_at": doc.get("updated_at", doc.get("created_at", 0)),
            "message_count": len(doc.get("messages") or []),
            "total_cost_usd": doc.get("total_cost_usd", 0),
        })
    return result


def load_chat(chat_id):
    path = chat_filename(chat_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def delete_chat(chat_id):
    path = chat_filename(chat_id)
    if not path.exists():
        return False
    path.unlink()
    return True


# ── End chat persistence ─────────────────────────────────────────────────────


class TerminalSession:
    def __init__(self, model, project_dir, extra_args):
        self.id = uuid.uuid4().hex
        self.created_at = time.time()
        self.output = ""
        self.closed = False
        cmd = [str(script_dir() / "claude-DO.sh"), "--model", model]
        if project_dir:
            cmd += ["--project-dir", project_dir]
        if extra_args:
            cmd += extra_args
        env = os.environ.copy()
        env["TERM"] = env.get("TERM", "xterm-256color")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(project_dir or str(script_dir()))
            os.execvpe(cmd[0], cmd, env)
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def read(self):
        if self.closed:
            return {"id": self.id, "output": "", "closed": True}
        chunks = []
        while True:
            ready, _, _ = select.select([self.fd], [], [], 0)
            if not ready:
                break
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                self.closed = True
                break
            if not data:
                self.closed = True
                break
            chunks.append(data.decode("utf-8", errors="replace"))
        text = "".join(chunks)
        self.output = (self.output + text)[-100000:]
        try:
            ended, _ = os.waitpid(self.pid, os.WNOHANG)
            if ended:
                self.closed = True
        except ChildProcessError:
            self.closed = True
        return {"id": self.id, "output": text, "closed": self.closed}

    def write(self, text):
        if not self.closed:
            os.write(self.fd, text.encode("utf-8"))

    def stop(self):
        if not self.closed:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except OSError:
                pass
            self.closed = True
        try:
            os.close(self.fd)
        except OSError:
            pass


def tmux_session_name(value):
    raw = str(value or "").strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")
    return cleaned[:80] if cleaned else "matts-claude"


def unique_tmux_session_name(base, reserved=None):
    reserved = set(reserved or [])
    root = tmux_session_name(base)
    candidate = root
    index = 2
    registry = read_tmux_session_registry()
    while tmux_exists(candidate) or candidate in registry or candidate in reserved:
        suffix = "-%d" % index
        candidate = (root[: max(1, 80 - len(suffix))] + suffix) if len(root) + len(suffix) > 80 else root + suffix
        index += 1
    return candidate


def tmux_cmd(args, check=True):
    try:
        result = subprocess.run(
            ["tmux"] + args,
            text=True,
            capture_output=True,
            check=check,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return 127, "", "tmux is not installed"
    except subprocess.CalledProcessError as exc:
        return exc.returncode, exc.stdout or "", exc.stderr or ""


def tmux_exists(name):
    return tmux_cmd(["has-session", "-t", name], check=False)[0] == 0


def read_tmux_session_registry():
    path = tmux_session_registry_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_tmux_session_registry(data):
    path = tmux_session_registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def tmux_registry_upsert(name, data=None, live=True, stopped=False):
    registry = read_tmux_session_registry()
    record = registry.get(name) if isinstance(registry.get(name), dict) else {}
    now = time.time()
    record.update({
        "name": name,
        "display_name": (data or {}).get("display_name") or record.get("display_name") or name,
        "updated_at": now,
        "live": bool(live),
    })
    if data:
        record.update({
            "model": data.get("model") or record.get("model") or "",
            "project_dir": data.get("project_dir") or record.get("project_dir") or str(script_dir()),
            "run_mode": data.get("run_mode") or record.get("run_mode") or "interactive",
            "permission_mode": data.get("permission_mode") or record.get("permission_mode") or "",
            "profile": data.get("profile") or record.get("profile") or "",
            "output_format": data.get("output_format") or record.get("output_format") or "",
            "claude_session_name": data.get("claude_session_name") or record.get("claude_session_name") or "",
            "max_budget_usd": data.get("max_budget_usd") or record.get("max_budget_usd") or "",
        })
    record.setdefault("created_at", now)
    if stopped:
        record["live"] = False
        record["stopped_at"] = now
    registry[name] = record
    write_tmux_session_registry(registry)
    return record


def proxy_usage_since(model, since_ts):
    if not model:
        return {"cost_usd": 0.0, "tokens": 0, "requests": 0}
    total_cost = 0.0
    total_tokens = 0
    requests = 0
    path = log_file()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-5000:]
    except OSError:
        return {"cost_usd": 0.0, "tokens": 0, "requests": 0}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if model and row.get("model") != model:
            continue
        if float(row.get("ts") or 0) < float(since_ts or 0):
            continue
        cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
        total_cost += float(cost.get("total_cost_usd") or 0)
        total_tokens += int(cost.get("total_tokens_est") or 0)
        requests += 1
    return {"cost_usd": total_cost, "tokens": total_tokens, "requests": requests}


def tmux_live_session_rows():
    fmt = "#{session_name}\t#{session_created}\t#{session_activity}\t#{session_attached}\t#{session_windows}"
    code, out, _ = tmux_cmd(["list-sessions", "-F", fmt], check=False)
    if code != 0:
        return {}
    rows = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        rows[parts[0]] = {
            "name": parts[0],
            "created_at": float(parts[1] or 0),
            "last_activity_at": float(parts[2] or 0),
            "attached": str(parts[3]) == "1",
            "windows": int(parts[4] or 0),
        }
    return rows


def tmux_session_items():
    registry = read_tmux_session_registry()
    live_rows = tmux_live_session_rows()
    hidden = {"matts-console-web", "matts-value-set-proxy"}
    for name, live in live_rows.items():
        if name in hidden:
            continue
        record = registry.get(name) if isinstance(registry.get(name), dict) else {}
        record.update({
            "name": name,
            "display_name": record.get("display_name") or name,
            "live": True,
            "created_at": record.get("created_at") or live.get("created_at") or time.time(),
            "last_activity_at": live.get("last_activity_at") or time.time(),
            "attached": live.get("attached"),
            "windows": live.get("windows"),
            "updated_at": time.time(),
        })
        registry[name] = record
    for name, record in list(registry.items()):
        if name in hidden:
            continue
        if name not in live_rows:
            record["live"] = False
            record.setdefault("stopped_at", record.get("updated_at") or time.time())
    write_tmux_session_registry(registry)

    items = []
    for name, record in registry.items():
        if name in hidden:
            continue
        created = float(record.get("created_at") or 0)
        spend = proxy_usage_since(record.get("model") or "", created)
        model_id = record.get("model") or ""
        meta = model_metadata_map().get(model_id) or {}
        item = dict(record)
        item.update({
            "name": name,
            "display_name": record.get("display_name") or name,
            "model_display": meta.get("display_name") or model_id or "Unknown model",
            "model_cost": meta.get("cost_label") or "Pricing unavailable",
            "uptime_seconds": int(max(0, time.time() - created)) if created else 0,
            "idle_seconds": int(max(0, time.time() - float(record.get("last_activity_at") or created or time.time()))),
            "estimated_cost_usd": spend["cost_usd"],
            "estimated_tokens": spend["tokens"],
            "estimated_requests": spend["requests"],
            "cost_attribution": "model_since_session_start" if model_id else "unattributed",
            "unattributed": not bool(model_id),
            "process_status": "running" if record.get("live") else "stopped",
            "status": "live" if record.get("live") else "previous",
            "read_only": not bool(record.get("live")),
        })
        items.append(item)
    items.sort(key=lambda item: (0 if item.get("live") else 1, -float(item.get("created_at") or item.get("stopped_at") or 0)))
    return items


def tmux_rename_session(old_name, new_name, display_name=None):
    old_name = tmux_session_name(old_name)
    display_name = str(display_name or new_name or old_name).strip() or old_name
    requested_name = tmux_session_name(new_name or display_name)
    registry = read_tmux_session_registry()
    record = registry.get(old_name) if isinstance(registry.get(old_name), dict) else {}
    if record and not record.get("live") and not tmux_exists(old_name):
        return HTTPStatus.BAD_REQUEST, {"error": "previous sessions are read-only"}
    reserved = {old_name}
    new_name = old_name if requested_name == old_name else unique_tmux_session_name(requested_name, reserved=reserved)
    if old_name == new_name:
        record = registry.get(old_name) if isinstance(registry.get(old_name), dict) else {}
        record["display_name"] = display_name
        record["updated_at"] = time.time()
        registry[old_name] = record
        write_tmux_session_registry(registry)
        return HTTPStatus.OK, {"ok": True, "name": new_name, "display_name": display_name, "renamed": False, "sessions": tmux_session_items()}
    if tmux_exists(old_name):
        code, _, err = tmux_cmd(["rename-session", "-t", old_name, new_name], check=False)
        if code != 0:
            return HTTPStatus.BAD_REQUEST, {"error": err or "tmux rename-session failed"}
    record = registry.pop(old_name, {}) if isinstance(registry.get(old_name), dict) else {}
    record["name"] = new_name
    record["display_name"] = display_name
    record["updated_at"] = time.time()
    registry[new_name] = record
    write_tmux_session_registry(registry)
    return HTTPStatus.OK, {"ok": True, "name": new_name, "display_name": display_name, "renamed": True, "sessions": tmux_session_items()}


def launcher_health():
    launcher = script_dir() / "claude-DO.sh"
    backup = script_dir() / "claude-DO.sh.backup"
    required = ("start_proxy()", "exec claude")

    def valid(text):
        return all(item in text for item in required)

    try:
        text = launcher.read_text()
    except OSError as exc:
        text = ""
        read_error = str(exc)
    else:
        read_error = ""
    if valid(text):
        return {"ok": True, "healed": False, "path": str(launcher)}
    try:
        backup_text = backup.read_text()
    except OSError as exc:
        return {"ok": False, "healed": False, "path": str(launcher), "error": read_error or str(exc)}
    if not valid(backup_text):
        return {"ok": False, "healed": False, "path": str(launcher), "error": "launcher and backup are incomplete"}
    try:
        launcher.write_text(backup_text)
        launcher.chmod(0o755)
    except OSError as exc:
        return {"ok": False, "healed": False, "path": str(launcher), "error": str(exc)}
    return {"ok": True, "healed": True, "path": str(launcher)}


def tmux_screen(name, lines="-80"):
    code, out, err = tmux_cmd(["capture-pane", "-p", "-e", "-J", "-S", lines, "-t", name], check=False)
    return code, out, err


def tmux_has_completed_claude(name):
    code, out, _ = tmux_screen(name)
    if code != 0:
        return False, ""
    markers = ("[Claude Code exited with status", "Session remains open for inspection")
    return all(marker in out for marker in markers), out


def split_lines(value):
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def claude_launch_args(data):
    args = []
    permission_mode = data.get("permission_mode")
    if permission_mode == "bypassPermissions" and hasattr(os, "geteuid") and os.geteuid() == 0:
        permission_mode = "acceptEdits"
    if permission_mode in {"acceptEdits", "bypassPermissions", "plan", "manual", "dontAsk", "auto"}:
        args += ["--permission-mode", permission_mode]
    setting_sources = data.get("setting_sources")
    if setting_sources:
        args += ["--setting-sources", str(setting_sources)]
    if data.get("safe_mode"):
        args.append("--safe-mode")
    if data.get("bare"):
        args.append("--bare")
    for directory in split_lines(data.get("add_dirs")):
        args += ["--add-dir", directory]
    allowed = str(data.get("allowed_tools") or "").strip()
    if allowed:
        args += ["--allowedTools", allowed]
    disallowed = str(data.get("disallowed_tools") or "").strip()
    if disallowed:
        args += ["--disallowedTools", disallowed]
    session_name = str(data.get("claude_session_name") or "").strip()
    if session_name:
        args += ["--name", session_name]
    run_mode = data.get("run_mode") or "interactive"
    prompt = str(data.get("print_prompt") or "").strip()
    budget = str(data.get("max_budget_usd") or "").strip()
    if run_mode in {"print", "json", "stream-json"}:
        args.append("--print")
        if budget:
            args += ["--max-budget-usd", budget]
        if run_mode == "json":
            args += ["--output-format", "json"]
        elif run_mode == "stream-json":
            args += ["--output-format", "stream-json"]
        else:
            output_format = data.get("output_format")
            if output_format in {"text", "json", "stream-json"}:
                args += ["--output-format", output_format]
        if data.get("no_session_persistence"):
            args.append("--no-session-persistence")
        if prompt:
            args.append(prompt)
    elif run_mode == "background":
        args.append("--bg")
        if prompt:
            args.append(prompt)
    elif run_mode == "continue":
        args.append("--continue")
    elif run_mode == "resume":
        resume_value = str(data.get("resume") or "").strip()
        args.append("--resume")
        if resume_value:
            args.append(resume_value)
    args += shlex.split(str(data.get("extra_args") or ""))
    return args


def tmux_start(data):
    health = launcher_health()
    if not health.get("ok"):
        return HTTPStatus.BAD_REQUEST, {"error": "Claude launcher is not runnable", "launcher": health}
    model = data.get("model") if data.get("model") in TEXT_MODELS else default_text_model()
    project_dir = data.get("project_dir") or str(script_dir())
    if not Path(project_dir).is_dir():
        return HTTPStatus.BAD_REQUEST, {"error": "project directory does not exist"}
    display_name = str(data.get("display_name") or data.get("name") or "matts-claude").strip() or "matts-claude"
    requested_name = data.get("name") or display_name
    name = unique_tmux_session_name(requested_name) if data.get("new_session") else tmux_session_name(requested_name)
    run_mode = data.get("run_mode") or "interactive"
    reset_dead_session = False
    if tmux_exists(name):
        completed, screen = tmux_has_completed_claude(name)
        if completed and run_mode == "interactive":
            tmux_stop(name)
            reset_dead_session = True
        else:
            payload_data = dict(data)
            payload_data["display_name"] = display_name
            tmux_registry_upsert(name, data=payload_data, live=True)
            return HTTPStatus.OK, {"name": name, "attached": True, "launcher": health, "sessions": tmux_session_items()}
    command = [str(script_dir() / "claude-DO.sh"), "--model", model] + claude_launch_args(data)
    shell_command = (
        "printf 'Starting Claude Code session: %s\\n'; "
        "%s; "
        "code=$?; "
        "printf '\\n[Claude Code exited with status %%s]\\n' \"$code\"; "
        "printf 'Session remains open for inspection. Press Ctrl-D or kill the session from the console.\\n'; "
        "exec ${SHELL:-/bin/bash}"
    ) % (shlex.quote(name), shlex.join(command))
    code, _, err = tmux_cmd([
        "new-session",
        "-d",
        "-s",
        name,
        "-x",
        str(int(data.get("cols") or 120)),
        "-y",
        str(int(data.get("rows") or 40)),
        "-c",
        project_dir,
        shell_command,
    ], check=False)
    if code != 0:
        return HTTPStatus.BAD_REQUEST, {"error": err or "tmux failed to start"}
    for _ in range(10):
        if tmux_exists(name):
            if run_mode == "interactive":
                time.sleep(0.3)
                completed, screen = tmux_has_completed_claude(name)
                if completed:
                    tmux_stop(name)
                    return HTTPStatus.BAD_REQUEST, {
                        "error": "Claude exited immediately after tmux start",
                        "name": name,
                        "launcher": health,
                        "screen": screen[-4000:],
                    }
            payload_data = dict(data)
            payload_data["display_name"] = display_name
            tmux_registry_upsert(name, data=payload_data, live=True)
            return HTTPStatus.OK, {"name": name, "display_name": display_name, "attached": False, "launcher": health, "reset": reset_dead_session, "sessions": tmux_session_items()}
        time.sleep(0.1)
    code, out, err = tmux_cmd(["list-sessions", "-F", "#{session_name}"], check=False)
    return HTTPStatus.BAD_REQUEST, {"error": "tmux session did not become addressable", "name": name, "sessions": out.splitlines(), "detail": err}


def tmux_capture(name):
    name = tmux_target(name)
    code, out, err = tmux_capture_target(name, "-200")
    if code != 0:
        return HTTPStatus.NOT_FOUND, {"error": err or "tmux session not found", "name": name}
    return HTTPStatus.OK, {"name": name, "screen": out}


def tmux_send_text(name, text, enter=False):
    name = tmux_target(name)
    buffer_name = name + "-paste"
    code, _, err = tmux_cmd(["set-buffer", "-b", buffer_name, text or ""], check=False)
    if code != 0:
        return HTTPStatus.BAD_REQUEST, {"error": err or "tmux set-buffer failed"}
    code, _, err = tmux_cmd(["paste-buffer", "-t", name, "-b", buffer_name], check=False)
    if code != 0:
        return HTTPStatus.BAD_REQUEST, {"error": err or "tmux paste failed"}
    if enter:
        tmux_cmd(["send-keys", "-t", name, "Enter"], check=False)
    return HTTPStatus.OK, {"ok": True}


def tmux_send_key(name, key):
    name = tmux_target(name)
    allowed = {
        "Enter", "Escape", "Up", "Down", "Left", "Right", "Tab", "BTab",
        "C-c", "C-d", "C-u", "C-l", "PageUp", "PageDown", "Home", "End",
    }
    if key not in allowed:
        return HTTPStatus.BAD_REQUEST, {"error": "key is not allowed"}
    code, _, err = tmux_cmd(["send-keys", "-t", name, key], check=False)
    if code != 0:
        return HTTPStatus.BAD_REQUEST, {"error": err or "tmux send-keys failed"}
    return HTTPStatus.OK, {"ok": True}


def tmux_stop(name):
    name = tmux_target(name)
    code, _, err = tmux_cmd(["kill-session", "-t", name], check=False)
    if code not in (0, 1):
        return HTTPStatus.BAD_REQUEST, {"error": err or "tmux kill-session failed"}
    tmux_registry_upsert(name, live=False, stopped=True)
    return HTTPStatus.OK, {"ok": True}


def tmux_sessions():
    items = tmux_session_items()
    names = [item["name"] for item in items if item.get("live")]
    app_names = [name for name in names if name.startswith("matts-")]
    return app_names or names


def strip_ansi(value):
    return ANSI_RE.sub("", str(value or ""))


def tmux_target(value, default="matts-claude"):
    raw = str(value or default).strip()
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_:.")
    return cleaned[:140] if cleaned else default


def tmux_capture_target(target, lines="-200"):
    target = tmux_target(target)
    code, out, err = tmux_cmd(["capture-pane", "-p", "-e", "-J", "-S", str(lines), "-t", target], check=False)
    if code != 0:
        return code, "", err or "tmux capture failed"
    return code, out, ""


def infer_agent_status(target, screen, width=0, height=0):
    now = time.time()
    clean = strip_ansi(screen)
    recent = "\n".join([line for line in clean.splitlines() if line.strip()][-10:])
    digest = hashlib.sha1((clean + "|%s|%s" % (width, height)).encode("utf-8", errors="replace")).hexdigest()
    previous = AGENTBOARD_CACHE.get(target)
    changed = bool(previous and previous.get("digest") != digest)
    last_changed = now if changed or not previous else float(previous.get("last_changed") or now)
    AGENTBOARD_CACHE[target] = {"digest": digest, "last_changed": last_changed}
    if changed:
        status = "working"
    elif PERMISSION_RE.search(recent):
        status = "permission"
    elif previous and now - last_changed < 10:
        status = "working"
    else:
        status = "waiting"
    return status, last_changed


def last_prompt_from_screen(screen):
    clean = strip_ansi(screen)
    candidates = []
    for line in clean.splitlines():
        text = line.strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered.startswith((">", "user:", "human:")) or "prompt" in lowered or "task" in lowered:
            candidates.append(text)
    if not candidates:
        candidates = [line.strip() for line in clean.splitlines() if line.strip()]
    return (candidates[-1] if candidates else "")[:240]


def agentboard_sessions():
    fmt = "#{session_name}	#{window_index}	#{window_name}	#{pane_index}	#{pane_current_command}	#{pane_current_path}	#{pane_width}	#{pane_height}	#{pane_pid}	#{pane_active}"
    code, out, err = tmux_cmd(["list-panes", "-a", "-F", fmt], check=False)
    if code != 0:
        return [], err or "tmux is unavailable"
    sessions = {}
    for line in out.splitlines():
        parts = line.split("	")
        if len(parts) < 10:
            continue
        session, window_index, window_name, pane_index, command, path, width, height, pid, active = parts[:10]
        target = "%s:%s.%s" % (session, window_index, pane_index)
        _, screen, _ = tmux_capture_target(target, "-120")
        try:
            width_i = int(width or 0)
            height_i = int(height or 0)
        except ValueError:
            width_i = height_i = 0
        status, last_changed = infer_agent_status(target, screen, width_i, height_i)
        item = sessions.setdefault(session, {
            "name": session, "target": session, "status": status, "panes": [], "path": path,
            "last_changed": last_changed, "last_prompt": "", "active": False,
        })
        item["panes"].append({
            "target": target, "window": window_name, "window_index": window_index, "pane_index": pane_index,
            "command": command, "path": path, "pid": pid, "active": active == "1",
            "width": width_i, "height": height_i, "status": status, "preview": strip_ansi(screen)[-1200:],
        })
        if active == "1" or not item.get("last_prompt"):
            item["status"] = status
            item["path"] = path
            item["last_changed"] = last_changed
            item["last_prompt"] = last_prompt_from_screen(screen)
            item["active"] = item["active"] or active == "1"
    order = {"permission": 0, "working": 1, "waiting": 2}
    rows = list(sessions.values())
    rows.sort(key=lambda item: (order.get(item.get("status"), 9), item.get("name", "")))
    return rows, ""


def agentboard_usage():
    today = datetime.datetime.now(datetime.timezone.utc).date()
    usage = local_usage_report(today - datetime.timedelta(days=6), today)
    logs = tail_jsonl(log_file(), limit=200)
    status_counts = {"ok": 0, "error": 0}
    for row in logs:
        if not isinstance(row, dict):
            continue
        try:
            code = int(row.get("status") or row.get("status_code") or 0)
        except (TypeError, ValueError):
            code = 0
        if code >= 400 or row.get("error"):
            status_counts["error"] += 1
        elif code:
            status_counts["ok"] += 1
    return usage, logs[-25:], status_counts


def agentboard_payload():
    sessions, error = agentboard_sessions()
    usage, logs, status_counts = agentboard_usage()
    counts = {"working": 0, "waiting": 0, "permission": 0, "unknown": 0}
    for session in sessions:
        counts[session.get("status") if session.get("status") in counts else "unknown"] += 1
    leaderboard = []
    for row in usage.get("by_model") or []:
        leaderboard.append({"name": row.get("model"), "score": row.get("amount_usd"), "metric": "local spend usd"})
    if not leaderboard:
        for session in sessions:
            leaderboard.append({"name": session.get("name"), "score": len(session.get("panes") or []), "metric": "active panes"})
    return {
        "generated_at": time.time(), "error": error, "sessions": sessions, "counts": counts,
        "tasks": [{"session": s.get("name"), "status": s.get("status"), "path": s.get("path"), "last_prompt": s.get("last_prompt"), "panes": len(s.get("panes") or [])} for s in sessions],
        "evals": {"source": "local proxy logs and tmux status", "requests_ok": status_counts["ok"], "requests_error": status_counts["error"], "active_sessions": len(sessions), "spend_usd": usage.get("total_usd", 0)},
        "leaderboard": leaderboard[:20], "usage": usage, "logs": logs,
    }


def websocket_accept_key(key):
    raw = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
    return base64.b64encode(hashlib.sha1(raw).digest()).decode("ascii")


def websocket_recv_exact(conn, size, timeout=2.0):
    chunks = []
    remaining = size
    deadline = time.time() + timeout
    while remaining > 0:
        wait = deadline - time.time()
        if wait <= 0:
            return None
        ready, _, _ = select.select([conn], [], [], wait)
        if not ready:
            return None
        try:
            chunk = conn.recv(remaining)
        except BlockingIOError:
            continue
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def websocket_read_frame(conn):
    header = websocket_recv_exact(conn, 2)
    if not header:
        return None
    first, second = header
    opcode = first & 0x0F
    masked = second & 0x80
    length = second & 0x7F
    if length == 126:
        data = websocket_recv_exact(conn, 2)
        if not data:
            return None
        length = struct.unpack("!H", data)[0]
    elif length == 127:
        data = websocket_recv_exact(conn, 8)
        if not data:
            return None
        length = struct.unpack("!Q", data)[0]
    mask = websocket_recv_exact(conn, 4) if masked else b""
    if masked and mask is None:
        return None
    payload = websocket_recv_exact(conn, length) if length else b""
    if payload is None:
        return None
    if masked:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    if opcode == 8:
        return None
    if opcode == 9:
        return {"ping": payload}
    return payload.decode("utf-8", errors="replace")


def websocket_send(conn, text):
    payload = text.encode("utf-8", errors="replace")
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    conn.sendall(bytes(header) + payload)


def set_pty_size(fd, rows, cols):
    try:
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
    except Exception:
        pass


def template_dir():
    return script_dir() / "templates"


_TEMPLATE_HANDLER = None


def template_handler():
    global _TEMPLATE_HANDLER
    path = template_dir()
    if _TEMPLATE_HANDLER is None or _TEMPLATE_HANDLER.template_dir != path:
        _TEMPLATE_HANDLER = TemplateHandler(path)
    return _TEMPLATE_HANDLER


def load_template(name):
    return template_handler().load(name)


def render_template(name, replacements=None):
    return template_handler().render(name, replacements)


def static_images_handler():
    return StaticHandler(app_dir() / "images")




class StudioHandler(BaseHTTPRequestHandler):
    server_version = "matts-unified-console/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(int(status))
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, status, text, content_type="text/plain; charset=utf-8"):
        data = text.encode("utf-8")
        self.send_response(int(status))
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        length = int(self.headers.get("content-length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def request_token(self):
        parsed = urlparse(self.path)
        query_token = (parse_qs(parsed.query).get("token") or [""])[0]
        if query_token:
            return query_token
        header_token = self.headers.get("x-matts-console-token", "").strip()
        if header_token:
            return header_token
        auth = self.headers.get("authorization", "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def authorized(self):
        return not auth_enabled() or secrets.compare_digest(self.request_token(), auth_token())

    def send_html(self, html):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_login(self):
        self.send_html(load_template("login.html"))

    def send_unauthorized(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_login()
            return
        self.send_json(401, {"error": "console auth token required"})

    def do_websocket_tmux(self):
        if not self.authorized():
            self.send_response(401)
            self.end_headers()
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        name = tmux_target((query.get("name") or ["matts-claude"])[0])
        cols = int((query.get("cols") or ["120"])[0] or 120)
        rows = int((query.get("rows") or ["40"])[0] or 40)
        if tmux_cmd(["has-session", "-t", name], check=False)[0] != 0:
            self.send_response(404)
            self.end_headers()
            return
        key = self.headers.get("sec-websocket-key", "")
        if not key:
            self.send_response(400)
            self.end_headers()
            return
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", websocket_accept_key(key))
        self.end_headers()
        pid, fd = pty.fork()
        if pid == 0:
            os.environ.setdefault("TERM", "xterm-256color")
            os.environ.setdefault("COLORTERM", "truecolor")
            os.execvp("tmux", ["tmux", "attach-session", "-t", name])
        set_pty_size(fd, rows, cols)
        conn = self.connection
        conn.setblocking(True)
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        try:
            while True:
                ready, _, _ = select.select([conn, fd], [], [], 0.05)
                if fd in ready:
                    try:
                        data = os.read(fd, 4096)
                    except OSError as exc:
                        print('tmux websocket pty read failed for %s: %r' % (name, exc), flush=True)
                        break
                    if not data:
                        print('tmux websocket pty eof for %s' % name, flush=True)
                        break
                    try:
                        websocket_send(conn, data.decode("utf-8", errors="replace"))
                    except OSError as exc:
                        print('tmux websocket send failed for %s: %r' % (name, exc), flush=True)
                        break
                if conn in ready:
                    try:
                        frame = websocket_read_frame(conn)
                    except OSError as exc:
                        print('tmux websocket client read failed for %s: %r' % (name, exc), flush=True)
                        break
                    if frame is None:
                        print('tmux websocket client closed for %s' % name, flush=True)
                        break
                    if isinstance(frame, dict):
                        continue
                    if frame.startswith("{"):
                        try:
                            message = json.loads(frame)
                            resize = message.get("resize")
                            if resize:
                                set_pty_size(fd, int(resize.get("rows") or rows), int(resize.get("cols") or cols))
                                continue
                        except ValueError:
                            pass
                    os.write(fd, frame.encode("utf-8", errors="replace"))
        finally:
            try:
                os.kill(pid, signal.SIGHUP)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass

    def do_GET(self):
        REQUEST_COUNTS["GET"] += 1
        path = urlparse(self.path).path
        if path == "/ws/tmux":
            return self.do_websocket_tmux()
        if path == "/health":
            return self.send_json(200, {"status": "ok", "service": "matts-unified-console", "version": APP_VERSION})
        if path == "/ready":
            status = console_status()
            code = 200 if status["status"] == "ok" else 503
            return self.send_json(code, status)
        if path == "/version":
            return self.send_json(200, {"service": "matts-unified-console", "version": APP_VERSION, "server": self.server_version})
        if path == "/metrics":
            return self.send_text(200, console_metrics_text(), "text/plain; version=0.0.4; charset=utf-8")
        if not self.authorized():
            return self.send_unauthorized()
        if path == "/":
            html = render_template("main.html", {
                "TEXT_MODELS": selectable_text_models(),
                "ACTIVE_TEXT_MODELS": TEXT_MODELS,
                "TEXT_MODEL_OPTIONS": model_options("text", include_disabled=True),
                "IMAGE_MODELS": IMAGE_MODELS,
                "IMAGE_MODEL_OPTIONS": model_options("image", include_disabled=True),
                "MODEL_META": model_metadata_map(),
                "SIZES": SIZES,
                "STYLES": STYLES,
                "SCRIPT_DIR": str(script_dir()),
            })
            self.send_html(html)
            return
        if path == "/terminal":
            self.send_html(load_template("terminal.html"))
            return
        if path == "/api/history":
            return self.send_json(200, read_history())
        if path == "/api/chat/history":
            return self.send_json(200, list_chats())
        if path == "/api/chat/load":
            parsed = urlparse(self.path)
            chat_id = (parse_qs(parsed.query).get("id") or [""])[0]
            if not chat_id:
                return self.send_json(400, {"error": "id query parameter is required"})
            doc = load_chat(chat_id)
            if doc is None:
                return self.send_json(404, {"error": "chat not found"})
            return self.send_json(200, doc)
        if path == "/api/tmux/sessions":
            items = tmux_session_items()
            return self.send_json(200, {"sessions": [item["name"] for item in items if item.get("live")], "items": items})
        if path == "/api/agentboard":
            return self.send_json(200, agentboard_payload())
        if path == "/api/models":
            return self.send_json(200, models_payload())
        if path == "/api/models/serverless-catalog":
            result = sync_serverless_model_catalog(force=True, validate_access=True)
            payload = models_payload(refresh_catalog=False)
            payload["serverless_catalog"] = result
            payload["proxy_sync"] = proxy_sync_payload(force=True)
            return self.send_json(200 if result.get("ok") else 502, payload)
        if path == "/api/model-access-key":
            return self.send_json(200, {"key": active_model_access_key_info()})
        if path == "/api/proxy/status":
            return self.send_json(200, proxy_sync_payload(force=False))
        if path == "/api/cost-summary":
            return self.send_json(200, cost_summary_payload())
        if path == "/api/wallpaper":
            query = parse_qs(urlparse(self.path).query)
            return self.send_json(200, wallpaper_payload(randomize=(query.get("random") or ["0"])[0] == "1"))
        if path == "/api/wallpaper/image":
            query = parse_qs(urlparse(self.path).query)
            remote = (query.get("remote") or [""])[0]
            image_id = (query.get("id") or ["wallpaper"])[0]
            try:
                status, data, content_type = wallpaper_image_response(remote, image_id)
            except Exception as exc:
                return self.send_json(502, {"error": "wallpaper image fetch failed", "message": str(exc)})
            self.send_response(int(status))
            self.send_header("content-type", content_type)
            self.send_header("cache-control", "public, max-age=86400")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/dedicated/status":
            return self.send_json(200, dedicated_status_payload(poll=True))
        if path == "/api/dedicated/events":
            return self.send_json(200, {"events": dedicated_events()})
        if path == "/api/dedicated/sizes":
            status, payload = dedicated_discovery("/v2/dedicated-inferences/sizes")
            return self.send_json(status, payload)
        if path == "/api/dedicated/gpu-model-config":
            status, payload = dedicated_discovery("/v2/dedicated-inferences/gpu-model-config")
            return self.send_json(status, payload)
        if path == "/api/status":
            proxy_sync = proxy_sync_payload(force=False)
            models_status, models = proxy_get("/v1/models")
            costs_status, costs = proxy_get("/v1/claude-do/costs")
            budget_status, budget = proxy_get("/v1/claude-do/budget")
            return self.send_json(200, {
                "proxy_listening": port_open(proxy_host(), proxy_port()),
                "proxy": "http://%s:%d" % (proxy_host(), proxy_port()),
                "proxy_sync": proxy_sync,
                "token_file": str(token_file()),
                "models": models if models_status < 400 else {"error": models},
                "costs": costs if costs_status < 400 else {"error": costs},
                "budget": budget if budget_status < 400 else {"error": budget},
                "logs": tail_jsonl(log_file()),
                "tmux_sessions": tmux_sessions(),
                "launcher": launcher_health(),
                "model_registry": models_payload(),
                "dedicated_inference": dedicated_status_payload(poll=False),
            })
        if path.startswith("/images/"):
            response = static_images_handler().file_response(path, default_content_type="image/png")
            if response is None:
                self.send_error(404)
                return
            self.send_response(response["status"])
            self.send_header("content-type", response["content_type"])
            for key, value in response["headers"].items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response["data"])
            return
        self.send_error(404)

    def do_POST(self):
        REQUEST_COUNTS["POST"] += 1
        path = urlparse(self.path).path
        if not self.authorized():
            return self.send_unauthorized()
        data = self.read_json()
        if path == "/api/generate":
            status, payload = generate_images(data)
            return self.send_json(status, payload)
        if path == "/api/chat":
            status, payload = chat_completion(data)
            return self.send_json(status, payload)
        if path == "/api/chat/save":
            doc = save_chat(data)
            return self.send_json(200, doc)
        if path == "/api/chat/delete":
            deleted = delete_chat(data.get("id"))
            return self.send_json(200, {"deleted": deleted})
        if path == "/api/delete":
            return self.send_json(200, {"deleted": delete_history_item(data.get("id"))})
        if path == "/api/models":
            status, payload = save_models_payload(data)
            return self.send_json(status, payload)
        if path == "/api/proxy/sync":
            return self.send_json(200, proxy_sync_payload(force=True))
        if path == "/api/model-access-audit":
            return self.send_json(200, audit_model_access_key())
        if path == "/api/dedicated/preflight":
            preflight = dedicated_preflight(data)
            payload = dedicated_status_payload(poll=False)
            payload["preflight"] = preflight
            payload["dedicated"] = preflight.get("config") or payload.get("dedicated")
            if preflight.get("errors"):
                append_dedicated_event("preflight", "Dedicated preflight needs attention", "warning", {"errors": preflight.get("errors"), "warnings": preflight.get("warnings")})
            else:
                append_dedicated_event("preflight", "Dedicated preflight passed", "success", {"warnings": preflight.get("warnings")})
            payload["events"] = dedicated_events()
            return self.send_json(200, payload)
        if path == "/api/dedicated/build":
            status, payload = dedicated_build(data)
            return self.send_json(status, payload)
        if path == "/api/dedicated/teardown":
            status, payload = dedicated_teardown(data)
            return self.send_json(status, payload)
        if path == "/api/dedicated/resume":
            status, payload = dedicated_build(data)
            return self.send_json(status, payload)
        if path == "/api/dedicated/policy":
            status, payload = dedicated_policy(data)
            return self.send_json(status, payload)
        if path == "/api/budget":
            return self.send_json(200, {"budgets": save_budget(data)})
        if path == "/api/reporting":
            return self.send_json(200, digitalocean_report(data))
        if path == "/api/test-models":
            results = []
            for model in TEXT_MODELS:
                status, payload = chat_completion({"model": model, "messages": [{"role": "user", "content": "Reply only ok"}], "max_tokens": 8})
                results.append({"model": model, "status": int(status), "ok": int(status) < 400, "response": payload})
            image_model = default_image_model()
            status, payload = generate_images({"model": image_model, "prompt": "small smoke test tile with the word OK", "size": "512x512", "count": 1, "style": "technical"})
            results.append({"model": image_model, "status": int(status), "ok": int(status) < 400, "response": payload})
            return self.send_json(200, {"results": results})
        if path == "/api/tmux/start":
            status, payload = tmux_start(data)
            return self.send_json(status, payload)
        if path == "/api/tmux/capture":
            status, payload = tmux_capture(data.get("name"))
            return self.send_json(status, payload)
        if path == "/api/tmux/send":
            status, payload = tmux_send_text(data.get("name"), data.get("text") or "", bool(data.get("enter")))
            return self.send_json(status, payload)
        if path == "/api/tmux/key":
            status, payload = tmux_send_key(data.get("name"), data.get("key"))
            return self.send_json(status, payload)
        if path == "/api/tmux/stop":
            status, payload = tmux_stop(data.get("name"))
            return self.send_json(status, payload)
        if path == "/api/tmux/rename":
            status, payload = tmux_rename_session(data.get("old_name"), data.get("new_name"), data.get("display_name"))
            return self.send_json(status, payload)
        if path == "/api/terminal/start":
            model = data.get("model") if data.get("model") in TEXT_MODELS else default_text_model()
            project_dir = data.get("project_dir") or str(script_dir())
            if not Path(project_dir).is_dir():
                return self.send_json(400, {"error": "project directory does not exist"})
            extra_args = [part for part in str(data.get("extra_args") or "").split() if part]
            session = TerminalSession(model, project_dir, extra_args)
            TERMINALS[session.id] = session
            return self.send_json(200, {"id": session.id})
        if path == "/api/terminal/read":
            session = TERMINALS.get(data.get("id"))
            if not session:
                return self.send_json(404, {"error": "terminal not found"})
            return self.send_json(200, session.read())
        if path == "/api/terminal/write":
            session = TERMINALS.get(data.get("id"))
            if not session:
                return self.send_json(404, {"error": "terminal not found"})
            session.write(data.get("text") or "")
            return self.send_json(200, {"ok": True})
        if path == "/api/terminal/stop":
            session = TERMINALS.pop(data.get("id"), None)
            if session:
                session.stop()
            return self.send_json(200, {"ok": True})
        self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="Run the Matts Value Set unified web console.")
    parser.add_argument("--host", default=os.environ.get("MATTS_STUDIO_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MATTS_STUDIO_PORT", "18181")))
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    write_token()
    console_token = auth_token()
    start_proxy_if_needed()
    server = ThreadingHTTPServer((args.host, args.port), StudioHandler)
    url = "http://%s:%d/" % (args.host, args.port)
    print("Mackes Code : FOR PRIVATE USE: %s" % url, flush=True)
    if auth_enabled():
        print("Console token file: %s" % auth_token_file(), flush=True)
        print("Console token: %s" % console_token, flush=True)
    for address in local_addresses():
        print("Reachable URL: http://%s:%d/?token=%s" % (address, args.port, console_token), flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        for session in list(TERMINALS.values()):
            session.stop()


if __name__ == "__main__":
    main()
