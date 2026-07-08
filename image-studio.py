#!/usr/bin/env python3
"""Pure Python unified web console for Matts Value Set."""
import argparse
import datetime
import fcntl
import json
import os
import re
import secrets
import select
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

from src.console.handlers.api_handler import ConsoleApiHandler
from src.console.handlers.auth_handler import AuthHandler
from src.console.handlers.static_handler import StaticHandler
from src.console.handlers.template_handler import TemplateHandler
from src.console.handlers.websocket_handler import TmuxWebSocketHandler
from src.console.services.agentboard import AgentBoardService
from src.console.services.app_config import ConsoleConfigService
from src.console.services.chat import ChatRoutingService
from src.console.services.health import ConsoleHealthService
from src.console.services.http_json import JsonHttpService
from src.console.services.dedicated import DedicatedInferenceService
from src.console.services.digitalocean import DigitalOceanHealthService
from src.console.services.image_generation import ImageGenerationService
from src.console.services.model_registry import ModelRegistryService
from src.console.services.persistence import LocalPersistenceService
from src.console.services.proxy_process import ProxyProcessService
from src.console.services.runtime_config import RuntimeConfigService
from src.console.services.serverless_catalog import ServerlessCatalogService
from src.console.services.session import SessionService
from src.console.services.terminal import TerminalSessionService
from src.console.services.tmux_control import TmuxControlService
from src.console.services.usage import UsageService
from src.console.services.wallpaper import WallpaperService
from src.console.services.websocket import WebSocketProtocolService
from src.console.utils.error_logging import configure_console_logging, log_error_response
from src.console.utils.errors import error_payload


EMBEDDED_ACCESS_KEY = ""
PROJECT_DIR = Path(__file__).resolve().parent
STARTUP_CONFIG = ConsoleConfigService(file_path=PROJECT_DIR / "image-studio.py").load()


def configured_path(key, default, env_name=None, base_dir=None):
    raw = os.environ.get(env_name, "") if env_name else ""
    if not raw:
        raw = STARTUP_CONFIG.get("paths", {}).get(key, default)
    path = Path(str(raw))
    if not path.is_absolute():
        path = Path(base_dir or PROJECT_DIR) / path
    return path


def load_default_model_registry():
    path = configured_path("default_model_registry_file", "config/default-models.json", None, PROJECT_DIR)
    data = json.loads(path.read_text(encoding="utf-8"))
    models = data.get("models") if isinstance(data, dict) else data
    if not isinstance(models, list):
        raise ValueError("default model registry must contain a models list")
    return models


DEFAULT_MODEL_REGISTRY = load_default_model_registry()
APP_VERSION = "1.0.0"
SERVER_STARTED_AT = time.time()
REQUEST_COUNTS = {"GET": 0, "POST": 0}
MODEL_AUTO_ENABLE_MAX_USD = float(STARTUP_CONFIG["models"]["auto_enable_max_usd"])
SERVERLESS_CATALOG_TTL_SECONDS = int(STARTUP_CONFIG["serverless"]["catalog_ttl_seconds"])
MODEL_TYPES = {"text", "image", "embedding", "rerank", "audio", "video", "router", "unknown"}
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
    return configured_path("model_config_file", "config/models.json", "MATTS_MODEL_CONFIG_FILE", PROJECT_DIR)


def serverless_catalog_cache_file():
    return configured_path("serverless_catalog_cache_file", "serverless-model-catalog.json", "MATTS_SERVERLESS_CATALOG_CACHE_FILE", app_dir())


def dedicated_config_file():
    return configured_path("dedicated_config_file", "dedicated-inference.json", "MATTS_DEDICATED_CONFIG_FILE", app_dir())


def legacy_dedicated_config_file():
    return PROJECT_DIR / "config" / "dedicated-inference.json"


def dedicated_events_file():
    return configured_path("dedicated_events_file", "dedicated-events.jsonl", "MATTS_DEDICATED_EVENTS_FILE", app_dir())


def tmux_session_registry_file():
    return configured_path("tmux_session_registry_file", "tmux-sessions.json", "MATTS_TMUX_SESSION_REGISTRY_FILE", app_dir())


def wallpaper_cache_dir():
    return configured_path("wallpaper_cache_dir", ".cache/matts-value-set/wallpapers", "MATTS_WALLPAPER_CACHE_DIR", home_dir())


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


def documented_serverless_pricing():
    pricing = {}
    for model in load_model_registry(include_disabled=True):
        model_pricing = model.get("pricing")
        if model.get("serverless") and model.get("id") and isinstance(model_pricing, dict) and model_pricing:
            pricing[model["id"]] = dict(model_pricing)
    return pricing


def serverless_catalog_service(
    read_model_access_token_func=None,
    fetch_serverless_catalog_func=None,
    serverless_catalog_payload_func=None,
    probe_serverless_text_model_func=None,
):
    return ServerlessCatalogService(
        env=os.environ,
        token_file=token_file,
        home_dir=home_dir,
        script_dir=script_dir,
        embedded_access_key=EMBEDDED_ACCESS_KEY,
        catalog_cache_file=serverless_catalog_cache_file,
        catalog_ttl_seconds=SERVERLESS_CATALOG_TTL_SECONDS,
        model_enabled_by_default=model_enabled_by_default,
        catalog_pricing_from_item=catalog_pricing_from_item,
        serverless_model_type=serverless_model_type,
        display_name_from_model_id=display_name_from_model_id,
        model_types=MODEL_TYPES,
        documented_pricing=documented_serverless_pricing,
        load_model_registry=load_model_registry,
        save_model_registry=save_model_registry,
        refresh_model_globals=refresh_model_globals,
        proxy_sync_payload=proxy_sync_payload,
        model_options=model_options,
        model_metadata_map=model_metadata_map,
        active_text_models=lambda: TEXT_MODELS,
        auto_enable_max_usd=MODEL_AUTO_ENABLE_MAX_USD,
        urlopen_func=urlopen,
        clock=time.time,
        read_model_access_token=read_model_access_token_func,
        fetch_serverless_catalog=fetch_serverless_catalog_func,
        serverless_catalog_payload=serverless_catalog_payload_func,
        probe_serverless_text_model=probe_serverless_text_model_func,
    )


def model_access_key_candidates():
    return serverless_catalog_service().model_access_key_candidates()


def active_model_access_key_info():
    return serverless_catalog_service().active_model_access_key_info()


def read_model_access_token():
    return serverless_catalog_service().read_model_access_token()


def fetch_serverless_catalog():
    return serverless_catalog_service(read_model_access_token_func=read_model_access_token).fetch_serverless_catalog()


def serverless_catalog_payload(force=False):
    return serverless_catalog_service(fetch_serverless_catalog_func=fetch_serverless_catalog).serverless_catalog_payload(force=force)


def serverless_registry_entry(item, existing=None):
    return serverless_catalog_service().serverless_registry_entry(item, existing=existing)


def probe_serverless_text_model(model_id):
    return serverless_catalog_service(read_model_access_token_func=read_model_access_token).probe_serverless_text_model(model_id)


def validate_serverless_access(models):
    return serverless_catalog_service(probe_serverless_text_model_func=probe_serverless_text_model).validate_serverless_access(models)


def audit_model_access_key():
    return serverless_catalog_service(
        probe_serverless_text_model_func=probe_serverless_text_model,
        serverless_catalog_payload_func=serverless_catalog_payload,
    ).audit_model_access_key()


def sync_serverless_model_catalog(force=False, validate_access=False):
    return serverless_catalog_service(
        serverless_catalog_payload_func=serverless_catalog_payload,
        probe_serverless_text_model_func=probe_serverless_text_model,
    ).sync_serverless_model_catalog(force=force, validate_access=validate_access)


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


def runtime_config_service():
    return RuntimeConfigService(
        env=os.environ,
        file_path=__file__,
        embedded_access_key=EMBEDDED_ACCESS_KEY,
        config=STARTUP_CONFIG,
        token_urlsafe=secrets.token_urlsafe,
        check_output_func=subprocess.check_output,
    )


def home_dir():
    return runtime_config_service().home_dir()


def script_dir():
    return runtime_config_service().script_dir()


def app_dir():
    return runtime_config_service().app_dir()


def auth_token_file():
    return runtime_config_service().auth_token_file()


def auth_token():
    return runtime_config_service().auth_token()


def auth_enabled():
    return runtime_config_service().auth_enabled()


def token_file():
    return runtime_config_service().token_file()


def access_key():
    return runtime_config_service().access_key()


def write_token():
    return runtime_config_service().write_token()


def proxy_host():
    return runtime_config_service().proxy_host()


def proxy_port():
    return runtime_config_service().proxy_port()


def proxy_url(path):
    return runtime_config_service().proxy_url(path)


def cost_file():
    return runtime_config_service().cost_file()


def budget_file():
    return runtime_config_service().budget_file()


def log_file():
    return runtime_config_service().log_file()


def digitalocean_token_file():
    return runtime_config_service().digitalocean_token_file()


def digitalocean_token_paths():
    return runtime_config_service().digitalocean_token_paths()


def digitalocean_token():
    return runtime_config_service().digitalocean_token()


def digitalocean_account_urn():
    return runtime_config_service().digitalocean_account_urn()


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
    return runtime_config_service().local_addresses()


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
        base_url=lambda: os.environ.get("MATTS_VALUE_SET_BASE_URL", STARTUP_CONFIG["proxy"]["base_url"]),
        write_token=write_token,
        default_text_model=default_text_model,
        token_file=token_file,
        model_config_file=model_config_file,
        cost_file=cost_file,
        budget_file=budget_file,
        log_file=log_file,
        proxy_script=lambda: Path(os.environ.get("MATTS_VALUE_SET_PROXY_SCRIPT", script_dir() / STARTUP_CONFIG["proxy"]["script"])),
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


def http_json_service():
    return JsonHttpService(urlopen_func=urlopen)


def request_json(url, payload=None, timeout=240, method="POST"):
    return http_json_service().request_json(url, payload=payload, timeout=timeout, method=method)


def do_get(path, token, query=None, timeout=30):
    return http_json_service().do_get(path, token, query=query, timeout=timeout)


def do_request(path, token, payload=None, timeout=60, method="GET"):
    return http_json_service().do_request(path, token, payload=payload, timeout=timeout, method=method)


def dedicated_service():
    return DedicatedInferenceService(
        default_config=DEFAULT_DEDICATED_CONFIG,
        steps=DEDICATED_STEPS,
        config_file=dedicated_config_file,
        legacy_config_file=legacy_dedicated_config_file,
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
    return http_json_service().public_json_url(url, timeout=timeout)


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
    return configured_path("template_dir", "templates", None, script_dir())


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


def tmux_websocket_handler(authorized):
    return TmuxWebSocketHandler(
        authorized=authorized,
        tmux_target=tmux_target,
        tmux_cmd=tmux_cmd,
        websocket_accept_key=websocket_accept_key,
        websocket_send=websocket_send,
        websocket_read_frame=websocket_read_frame,
        set_pty_size=set_pty_size,
    )


def api_handler():
    return ConsoleApiHandler(
        read_history=read_history,
        list_chats=list_chats,
        load_chat=load_chat,
        tmux_session_items=tmux_session_items,
        agentboard_payload=agentboard_payload,
        models_payload=models_payload,
        sync_serverless_model_catalog=sync_serverless_model_catalog,
        proxy_sync_payload=proxy_sync_payload,
        active_model_access_key_info=active_model_access_key_info,
        cost_summary_payload=cost_summary_payload,
        wallpaper_payload=wallpaper_payload,
        dedicated_status_payload=dedicated_status_payload,
        dedicated_events=dedicated_events,
        dedicated_discovery=dedicated_discovery,
        proxy_get=proxy_get,
        port_open=port_open,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        token_file=token_file,
        tail_jsonl=tail_jsonl,
        log_file=log_file,
        tmux_sessions=tmux_sessions,
        launcher_health=launcher_health,
        generate_images=generate_images,
        chat_completion=chat_completion,
        save_chat=save_chat,
        delete_chat=delete_chat,
        delete_history_item=delete_history_item,
        save_models_payload=save_models_payload,
        audit_model_access_key=audit_model_access_key,
        dedicated_preflight=dedicated_preflight,
        append_dedicated_event=append_dedicated_event,
        dedicated_build=dedicated_build,
        dedicated_teardown=dedicated_teardown,
        dedicated_policy=dedicated_policy,
        save_budget=save_budget,
        digitalocean_report=digitalocean_report,
        text_models=lambda: TEXT_MODELS,
        default_image_model=default_image_model,
        tmux_start=tmux_start,
        tmux_capture=tmux_capture,
        tmux_send_text=tmux_send_text,
        tmux_send_key=tmux_send_key,
        tmux_stop=tmux_stop,
        tmux_rename_session=tmux_rename_session,
        terminal_start=terminal_start,
        terminal_read=terminal_read,
        terminal_write=terminal_write,
        terminal_stop=terminal_stop,
    )




class StudioHandler(BaseHTTPRequestHandler):
    server_version = "matts-unified-console/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def send_json(self, status, payload):
        if int(status) >= 400:
            log_error_response(getattr(self, "command", ""), urlparse(self.path).path, status, payload)
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
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError as exc:
            raise ValueError("invalid JSON request body") from exc

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
        self.send_json(401, error_payload("console auth token required", 401, code="console_auth_required"))

    def do_websocket_tmux(self):
        return tmux_websocket_handler(self.authorized).handle(self)

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
        if path.startswith("/api/") and path != "/api/wallpaper/image":
            handled, status, payload = api_handler().get(path, parse_qs(urlparse(self.path).query))
            if handled:
                return self.send_json(status, payload)
            return self.send_json(404, error_payload("api endpoint not found", 404, code="api_endpoint_not_found", details={"path": path}))
        if path == "/api/wallpaper/image":
            query = parse_qs(urlparse(self.path).query)
            remote = (query.get("remote") or [""])[0]
            image_id = (query.get("id") or ["wallpaper"])[0]
            try:
                status, data, content_type = wallpaper_image_response(remote, image_id)
            except Exception as exc:
                return self.send_json(502, error_payload("wallpaper image fetch failed", 502, code="wallpaper_image_fetch_failed", details={"reason": str(exc)}))
            self.send_response(int(status))
            self.send_header("content-type", content_type)
            self.send_header("cache-control", "public, max-age=86400")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
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
        try:
            data = self.read_json()
        except ValueError as exc:
            return self.send_json(400, error_payload(str(exc), 400, code="invalid_json_body", details={"path": path}))
        handled, status, payload = api_handler().post(path, data)
        if handled:
            return self.send_json(status, payload)
        self.send_json(404, error_payload("api endpoint not found", 404, code="api_endpoint_not_found", details={"path": path}))


def main():
    configure_console_logging(STARTUP_CONFIG["logging"]["level"])
    parser = argparse.ArgumentParser(description="Run the Matts Value Set unified web console.")
    parser.add_argument("--host", default=str(STARTUP_CONFIG["server"]["host"]))
    parser.add_argument("--port", type=int, default=int(STARTUP_CONFIG["server"]["port"]))
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
