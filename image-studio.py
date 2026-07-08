#!/usr/bin/env python3
"""Pure Python unified web console for Matts Value Set."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import pty
import re
import secrets
import select
import signal
import socket
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

from src.console.handlers.auth_handler import AuthHandler
from src.console.handlers.static_handler import StaticHandler
from src.console.handlers.template_handler import TemplateHandler
from src.console.services.agentboard import AgentBoardService
from src.console.services.chat import ChatRoutingService
from src.console.services.health import ConsoleHealthService
from src.console.services.dedicated import DedicatedInferenceService
from src.console.services.digitalocean import DigitalOceanHealthService
from src.console.services.image_generation import ImageGenerationService
from src.console.services.model_registry import ModelRegistryService
from src.console.services.persistence import LocalPersistenceService
from src.console.services.proxy_process import ProxyProcessService
from src.console.services.session import SessionService
from src.console.services.terminal import TerminalSessionService
from src.console.services.tmux_control import TmuxControlService
from src.console.services.usage import UsageService
from src.console.services.wallpaper import WallpaperService
from src.console.services.websocket import WebSocketProtocolService


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


def model_registry_service():
    return ModelRegistryService(DEFAULT_MODEL_REGISTRY, MODEL_TYPES, MODEL_AUTO_ENABLE_MAX_USD)


def model_enabled_by_default(pricing):
    return model_registry_service().enabled_by_default(pricing)


def model_route_enabled(model):
    return model_registry_service().route_enabled(model)


def _normalized_model(item):
    return model_registry_service().normalize(item)


def load_model_registry(include_disabled=True):
    return model_registry_service().load(model_config_file(), include_disabled=include_disabled)


def save_model_registry(models):
    return model_registry_service().save(model_config_file(), models)


def serverless_model_type(model_id):
    return model_registry_service().serverless_model_type(model_id)


def display_name_from_model_id(model_id):
    return model_registry_service().display_name_from_model_id(model_id)


def _catalog_price_value(item, keys):
    return model_registry_service().catalog_price_value(item, keys)


def catalog_pricing_from_item(item):
    return model_registry_service().catalog_pricing_from_item(item)


def model_brand_profile(model):
    return model_registry_service().brand_profile(model)


def readable_model_cost(model):
    return model_registry_service().readable_cost(model)


def model_use_case(model, profile):
    return model_registry_service().use_case(model, profile)


def model_status_label(model):
    return model_registry_service().status_label(model)


def enriched_model_option(model):
    return model_registry_service().enriched_option(model)


def model_options(model_type=None, include_disabled=True):
    rows = load_model_registry(include_disabled=True)
    return model_registry_service().options(rows, model_type=model_type, include_disabled=include_disabled)


def model_metadata_map():
    return model_registry_service().metadata_map(model_options(include_disabled=True))


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


def proxy_process_service(proxy_in_sync_func=None):
    return ProxyProcessService(
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        port_open=port_open,
        request_json=request_json,
        proxy_capabilities_raw=proxy_capabilities_raw,
        model_config_fingerprint=model_config_fingerprint,
        same_model_config_fingerprint=same_model_config_fingerprint,
        all_models=lambda: ALL_MODELS,
        base_url=lambda: os.environ.get("MATTS_VALUE_SET_BASE_URL", "https://inference.do-ai.run"),
        write_token=write_token,
        default_text_model=default_text_model,
        token_file=token_file,
        model_config_file=model_config_file,
        cost_file=cost_file,
        budget_file=budget_file,
        log_file=log_file,
        proxy_script=lambda: Path(os.environ.get("MATTS_VALUE_SET_PROXY_SCRIPT", script_dir() / "do-anthropic-proxy.py")),
        executable=sys.executable,
        env=os.environ,
        sleep_func=time.sleep,
        proxy_in_sync_func=proxy_in_sync_func,
    )


def proxy_in_sync():
    return proxy_process_service().in_sync()


def stop_proxy():
    return proxy_process_service().stop()


def start_proxy_if_needed(force=False):
    return proxy_process_service().start_if_needed(force=force)


def proxy_sync_payload(force=False):
    return proxy_process_service().sync_payload(force=force)


def registry_sync_issue_for_model(model):
    return proxy_process_service(proxy_in_sync_func=proxy_in_sync).registry_sync_issue_for_model(model)


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


def dedicated_service():
    return DedicatedInferenceService(
        default_config=DEFAULT_DEDICATED_CONFIG,
        steps=DEDICATED_STEPS,
        config_file=dedicated_config_file,
        events_file=dedicated_events_file,
        tail_jsonl=tail_jsonl,
        digitalocean_token=digitalocean_token,
        do_request=do_request,
        load_model_registry=load_model_registry,
        save_model_registry=save_model_registry,
        refresh_model_globals=refresh_model_globals,
        models_payload=models_payload,
        digitalocean_health_snapshot=digitalocean_health_snapshot,
        serverless_chat_completion=serverless_chat_completion,
        active_text_models=lambda: TEXT_MODELS,
        default_text_model=default_text_model,
        clock=time.time,
    )


def load_dedicated_config():
    return dedicated_service().load_config()


def save_dedicated_config(cfg):
    return dedicated_service().save_config(cfg)


def append_dedicated_event(state, message, severity="info", details=None):
    return dedicated_service().append_event(state, message, severity, details)


def dedicated_events(limit=80):
    return dedicated_service().events(limit)


def dedicated_elapsed_seconds(cfg, now=None):
    return dedicated_service().elapsed_seconds(cfg, now)


def dedicated_cost_usd(cfg, now=None):
    return dedicated_service().cost_usd(cfg, now)


def dedicated_runtime_cost_summary(cfg, now=None):
    return dedicated_service().runtime_cost_summary(cfg, now)


def dedicated_idle_seconds(cfg, now=None):
    return dedicated_service().idle_seconds(cfg, now)


DO_HEALTH_CACHE = {"ts": 0, "payload": None}


def digitalocean_health_service():
    return DigitalOceanHealthService(
        public_json_url=public_json_url,
        do_get=do_get,
        digitalocean_token=digitalocean_token,
        cache=DO_HEALTH_CACHE,
        clock=time.time,
    )


def mask_email(value):
    return digitalocean_health_service().mask_email(value)


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


def wallpaper_service():
    return WallpaperService(
        cache_dir=wallpaper_cache_dir,
        public_json_url=public_json_url,
        randbelow=secrets.randbelow,
    )


def wallpaper_payload(randomize=False):
    return wallpaper_service().payload(randomize=randomize)


def wallpaper_image_response(remote_url, image_id):
    return wallpaper_service().image_response(remote_url, image_id)


def digitalocean_platform_status():
    return digitalocean_health_service().platform_status()


def digitalocean_health_snapshot():
    return digitalocean_health_service().snapshot()


def dedicated_public_payload(cfg):
    return dedicated_service().public_payload(cfg)


def dedicated_extract_id(response):
    return dedicated_service().extract_id(response)


def dedicated_extract_resource(response):
    return dedicated_service().extract_resource(response)


def dedicated_endpoint(cfg):
    return dedicated_service().endpoint(cfg)


def dedicated_status_message(cfg):
    return dedicated_service().status_message(cfg)


def dedicated_not_ready_payload(cfg, requested_model):
    return dedicated_service().not_ready_payload(cfg, requested_model)


def dedicated_model_entry(cfg, enabled=None):
    return dedicated_service().model_entry(cfg, enabled=enabled)


def register_dedicated_model(cfg, enabled=None):
    return dedicated_service().register_model(cfg, enabled=enabled)


def remove_dedicated_model(cfg):
    return dedicated_service().remove_model(cfg)


def dedicated_preflight(data=None):
    return dedicated_service().preflight(data)


def dedicated_update_from_resource(cfg, resource):
    return dedicated_service().update_from_resource(cfg, resource)


def dedicated_resource_issue(resource):
    return dedicated_service().resource_issue(resource)


def dedicated_status_payload(poll=True):
    return dedicated_service().status_payload(poll=poll)


def dedicated_create_token(cfg):
    return dedicated_service().create_token(cfg)


def dedicated_build(data):
    return dedicated_service().build(data)


def dedicated_teardown(data=None):
    return dedicated_service().teardown(data)


def dedicated_policy(data):
    return dedicated_service().policy(data)


def dedicated_discovery(path):
    return dedicated_service().discovery(path)


def is_dedicated_model(model):
    return dedicated_service().is_model(model)


def dedicated_chat_completion(data, cfg):
    return dedicated_service().chat_completion(data, cfg)


def persistence_service():
    return LocalPersistenceService(
        app_dir=app_dir,
        chat_cost_per_mtok=CHAT_COST_PER_MTOK,
        default_text_model=default_text_model,
        clock=time.time,
        uuid_factory=uuid.uuid4,
    )


def history_path():
    return persistence_service().history_path()


def read_history(limit=300):
    return persistence_service().read_history(limit)


def append_history(record):
    return persistence_service().append_history(record)


def image_generation_service():
    return ImageGenerationService(
        styles=STYLES,
        sizes=SIZES,
        image_models=lambda: IMAGE_MODELS,
        image_cost_usd=lambda: IMAGE_COST_USD,
        default_image_model=default_image_model,
        start_proxy_if_needed=start_proxy_if_needed,
        request_json=request_json,
        proxy_url=proxy_url,
        save_image_item=save_image_item,
        append_history=append_history,
        clock=time.time,
        uuid_factory=uuid.uuid4,
    )


def build_prompt(data):
    return image_generation_service().build_prompt(data)


def save_image_item(item, image_id):
    return persistence_service().save_image_item(item, image_id)


def generate_images(data):
    return image_generation_service().generate(data)


def chat_routing_service():
    return ChatRoutingService(
        start_proxy_if_needed=start_proxy_if_needed,
        request_json=request_json,
        proxy_url=proxy_url,
        text_models=lambda: TEXT_MODELS,
        default_text_model=default_text_model,
        registry_sync_issue_for_model=registry_sync_issue_for_model,
        chat_cost_usd=_chat_cost_usd,
        is_dedicated_model=is_dedicated_model,
        dedicated_status_payload=dedicated_status_payload,
        dedicated_chat_completion=dedicated_chat_completion,
        load_dedicated_config=load_dedicated_config,
    )


def serverless_chat_completion(data, model, allow_unregistered=False):
    return chat_routing_service().serverless_completion(data, model, allow_unregistered=allow_unregistered)


def chat_completion(data):
    return chat_routing_service().completion(data)


def proxy_get(path):
    return chat_routing_service().proxy_get(path)


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


def usage_service():
    return UsageService(
        cost_file=cost_file,
        budget_file=budget_file,
        tail_jsonl=tail_jsonl,
        do_get=do_get,
        digitalocean_token=digitalocean_token,
        digitalocean_account_urn=digitalocean_account_urn,
        digitalocean_health_snapshot=digitalocean_health_snapshot,
        load_dedicated_config=load_dedicated_config,
        dedicated_runtime_cost_summary=dedicated_runtime_cost_summary,
        clock=time.time,
    )


def parse_date(value, default):
    return usage_service().parse_date(value, default)


def local_usage_report(start_date, end_date):
    return usage_service().local_usage_report(start_date, end_date)


def local_usage_since(since_ts, now=None):
    return usage_service().local_usage_since(since_ts, now)


def insight_rows(insights):
    return usage_service().insight_rows(insights)


def insight_amount(row):
    return usage_service().insight_amount(row)


def digitalocean_insights_total(token, account_urn, start_date, end_date):
    return usage_service().digitalocean_insights_total(token, account_urn, start_date, end_date)


def cost_summary_payload():
    return usage_service().cost_summary_payload()


def digitalocean_report(data):
    return usage_service().digitalocean_report(data)


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
    return usage_service().save_budget(data)


def delete_history_item(image_id):
    return persistence_service().delete_history_item(image_id)


# ── Chat persistence ──────────────────────────────────────────────────────────


def chats_dir():
    return persistence_service().chats_dir()


def _estimate_tokens(text):
    return persistence_service().estimate_tokens(text)


def _chat_cost_usd(model, input_text, output_text):
    return persistence_service().chat_cost_usd(model, input_text, output_text)


def chat_filename(chat_id):
    return persistence_service().chat_filename(chat_id)


def _make_title(messages):
    return persistence_service().make_title(messages)


def save_chat(data):
    return persistence_service().save_chat(data)


def list_chats():
    return persistence_service().list_chats()


def load_chat(chat_id):
    return persistence_service().load_chat(chat_id)


def delete_chat(chat_id):
    return persistence_service().delete_chat(chat_id)


# ── End chat persistence ─────────────────────────────────────────────────────


def session_service():
    return SessionService(
        registry_file=tmux_session_registry_file,
        log_file=log_file,
        script_dir=script_dir,
        tmux_exists=tmux_exists,
        tmux_cmd=tmux_cmd,
        model_metadata_map=model_metadata_map,
        clock=time.time,
    )


def tmux_session_name(value):
    return session_service().session_name(value)


def unique_tmux_session_name(base, reserved=None):
    return session_service().unique_name(base, reserved=reserved)


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
    return session_service().read_registry()


def write_tmux_session_registry(data):
    session_service().write_registry(data)


def tmux_registry_upsert(name, data=None, live=True, stopped=False):
    return session_service().upsert(name, data=data, live=live, stopped=stopped)


def proxy_usage_since(model, since_ts):
    return session_service().proxy_usage_since(model, since_ts)


def tmux_live_session_rows():
    return session_service().live_session_rows()


def tmux_session_items():
    return session_service().session_items()


def tmux_rename_session(old_name, new_name, display_name=None):
    return session_service().rename_session(old_name, new_name, display_name=display_name)


def terminal_session_service():
    return TerminalSessionService(
        script_dir=script_dir,
        text_models=lambda: TEXT_MODELS,
        default_text_model=default_text_model,
        sessions=TERMINALS,
    )


def terminal_start(data):
    return terminal_session_service().start(data)


def terminal_read(session_id):
    return terminal_session_service().read(session_id)


def terminal_write(session_id, text):
    return terminal_session_service().write(session_id, text)


def terminal_stop(session_id):
    return terminal_session_service().stop(session_id)


def terminal_stop_all():
    return terminal_session_service().stop_all()


def tmux_control_service():
    return TmuxControlService(
        script_dir=script_dir,
        text_models=lambda: TEXT_MODELS,
        default_text_model=default_text_model,
        tmux_cmd=tmux_cmd,
        tmux_exists=tmux_exists,
        tmux_target=tmux_target,
        tmux_capture_target=tmux_capture_target,
        unique_tmux_session_name=unique_tmux_session_name,
        tmux_session_name=tmux_session_name,
        tmux_registry_upsert=tmux_registry_upsert,
        tmux_session_items=tmux_session_items,
        live_session_names=lambda: session_service().live_session_names(),
        clock=time.time,
        sleep=time.sleep,
        geteuid=os.geteuid if hasattr(os, "geteuid") else None,
    )


def launcher_health():
    return tmux_control_service().launcher_health()


def tmux_screen(name, lines="-80"):
    return tmux_control_service().screen(name, lines)


def tmux_has_completed_claude(name):
    return tmux_control_service().has_completed_claude(name)


def split_lines(value):
    return tmux_control_service().split_lines(value)


def claude_launch_args(data):
    return tmux_control_service().claude_launch_args(data)


def tmux_start(data):
    return tmux_control_service().start(data)


def tmux_capture(name):
    return tmux_control_service().capture(name)


def tmux_send_text(name, text, enter=False):
    return tmux_control_service().send_text(name, text, enter)


def tmux_send_key(name, key):
    return tmux_control_service().send_key(name, key)


def tmux_stop(name):
    return tmux_control_service().stop(name)


def tmux_sessions():
    return tmux_control_service().sessions()


def agentboard_service():
    return AgentBoardService(
        ansi_re=ANSI_RE,
        permission_re=PERMISSION_RE,
        cache=AGENTBOARD_CACHE,
        tmux_cmd=tmux_cmd,
        local_usage_report=local_usage_report,
        tail_jsonl=tail_jsonl,
        log_file=log_file,
        clock=time.time,
    )


def strip_ansi(value):
    return agentboard_service().strip_ansi(value)


def tmux_target(value, default="matts-claude"):
    return agentboard_service().tmux_target(value, default)


def tmux_capture_target(target, lines="-200"):
    return agentboard_service().tmux_capture_target(target, lines)


def infer_agent_status(target, screen, width=0, height=0):
    return agentboard_service().infer_status(target, screen, width, height)


def last_prompt_from_screen(screen):
    return agentboard_service().last_prompt_from_screen(screen)


def agentboard_sessions():
    return agentboard_service().sessions()


def agentboard_usage():
    return agentboard_service().usage()


def agentboard_payload():
    return agentboard_service().payload()


def websocket_protocol_service():
    return WebSocketProtocolService(
        select_func=select.select,
        ioctl_func=fcntl.ioctl,
        clock=time.time,
    )


def websocket_accept_key(key):
    return websocket_protocol_service().accept_key(key)


def websocket_recv_exact(conn, size, timeout=2.0):
    return websocket_protocol_service().recv_exact(conn, size, timeout)


def websocket_read_frame(conn):
    return websocket_protocol_service().read_frame(conn)


def websocket_send(conn, text):
    return websocket_protocol_service().send(conn, text)


def set_pty_size(fd, rows, cols):
    return websocket_protocol_service().set_pty_size(fd, rows, cols)


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


def auth_handler():
    return AuthHandler(auth_enabled=auth_enabled, auth_token=auth_token)




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
        return auth_handler().request_token(self.path, self.headers)

    def authorized(self):
        return auth_handler().authorized(self.path, self.headers)

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
            status, payload = terminal_start(data)
            return self.send_json(status, payload)
        if path == "/api/terminal/read":
            status, payload = terminal_read(data.get("id"))
            return self.send_json(status, payload)
        if path == "/api/terminal/write":
            status, payload = terminal_write(data.get("id"), data.get("text") or "")
            return self.send_json(status, payload)
        if path == "/api/terminal/stop":
            status, payload = terminal_stop(data.get("id"))
            return self.send_json(status, payload)
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
        terminal_stop_all()


if __name__ == "__main__":
    main()
