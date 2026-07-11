#!/usr/bin/env python3
"""Pure Python unified web console for MDE LLM-PROXY."""
import argparse
import datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

from backend.v2.services.run_store import RunStore
from src.console.app import ConsoleApp
from src.console.events.bus import EventBus
from src.console.events.sinks import JsonlEventSink
from src.console.handlers.api_handler import ConsoleApiHandler
from src.console.handlers.api_versioning import api_version_headers, api_version_info
from src.console.handlers.auth_handler import AuthHandler, ROLE_PERMISSIONS, SENSITIVE_GET_PERMISSIONS, SENSITIVE_POST_PERMISSIONS, SENSITIVE_WEBSOCKET_PERMISSIONS
from src.console.handlers.static_handler import StaticHandler
from src.console.handlers.template_handler import TemplateHandler
from src.console.handlers.websocket_handler import TmuxWebSocketHandler
from src.console.policy import PolicyService
from src.console.services.agentboard import AgentBoardService
from src.console.services.analytics import AnalyticsService
from src.console.services.app_config import ConsoleConfigService
from src.console.services.automation_rules import AutomationRulesService
from src.console.services.auth_session import AuthSessionService
from src.console.services.audit import AuditService
from src.console.services.audit_explorer import AuditExplorerService
from src.console.services.chat import ChatRoutingService
from src.console.services.ci_triage import CiTriageService
from src.console.services.command_palette import CommandPaletteService
from src.console.services.comparison_reports import ComparisonReportService
from src.console.services.context_window import ContextWindowService
from src.console.services.config_drift import ConfigDriftService
from src.console.services.cost_anomalies import CostAnomalyService
from src.console.services.cost_forecast import CostForecastService
from src.console.services.decision_explain import DecisionExplanationService
from src.console.services.eval_gates import EvalGateBlocked, EvalGateService
from src.console.services.evals import EvalService
from src.console.services.failure_taxonomy import FailureTaxonomyService
from src.console.services.health import ConsoleHealthService
from src.console.services.http_json import JsonHttpService
from src.console.services.dedicated import DedicatedInferenceService
from src.console.services.digitalocean import DigitalOceanHealthService
from src.console.services.image_generation import ImageGenerationService
from src.console.services.permission_simulator import PermissionSimulatorService
from src.console.services.session_resources import SessionResourceService
from src.console.services.session_snapshots import SessionSnapshotService
from src.console.services.local_rag import LocalRagService
from src.console.services.model_deprecation import ModelDeprecationService
from src.console.services.model_hero import ModelHeroService
from src.console.services.model_scorecards import ModelScorecardService
from src.console.services.opentelemetry import OpenTelemetryExporter
from src.console.services.model_registry import ModelRegistryService
from src.console.services.notifications import NotificationCenterService
from src.console.services.offline_mode import OfflineModeService
from src.console.services.onboarding import OnboardingChecklistService
from src.console.services.policy_as_code import PolicyAsCodeService
from src.console.services.patch_review import PatchReviewService
from src.console.services.persistence import LocalPersistenceService
from src.console.services.plugins import PluginRegistryService
from src.console.services.provider_health import ProviderHealthService
from src.console.services.quota_planner import QuotaPlannerService
from src.console.services.proxy_process import ProxyProcessService
from src.console.services.rate_limit import RateLimitService
from src.console.services.reporting_export import ReportingExportService
from src.console.services.reporting_integration import ReportingIntegrationService
from src.console.services.replay import ReplayService
from src.console.services.repository_context import GitHubContextConnector, RepositoryContextService
from src.console.services.release_candidate import ReleaseCandidateService
from src.console.services.review_queue import ReviewQueueService
from src.console.services.runtime_config import RuntimeConfigService
from src.console.services.rollback_wizard import RollbackWizardService
from src.console.services.serverless_catalog import ServerlessCatalogService
from src.console.services.session import SessionService
from src.console.services.synthetic_load import SyntheticLoadTesterService
from src.console.services.terminal import TerminalSessionService
from src.console.services.tmux_control import TmuxControlService
from src.console.services.traces import TraceService
from src.console.services.usage import UsageService
from src.console.services.wallpaper import WallpaperService
from src.console.services.websocket import WebSocketProtocolService
from src.console.services.workspace_bundles import WorkspaceBundleService
from src.console.store import RuntimeStateRepository
from src.console.utils.error_logging import configure_console_logging, log_error_response
from src.console.utils.errors import error_payload, route_not_found_details


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
CONSOLE_DISPLAY_NAME = "MDE LLM-PROXY Console"
CONSOLE_SERVICE_ID = "mde-llm-proxy-console"
CONSOLE_SERVER_VERSION = "MDE-LLM-PROXY-Console/1.0"
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
    "schema_version": 1,
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
    "unhealthy_teardown_seconds": 300,
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


def model_descriptions_dir():
    return configured_path("model_descriptions_dir", "config/model-descriptions", "MATTS_MODEL_DESCRIPTIONS_DIR", PROJECT_DIR)


def gateway_policy_file():
    return configured_path("gateway_policy_file", "config/gateway-policy.json", "MATTS_GATEWAY_POLICY_FILE", PROJECT_DIR)


def console_config_file():
    return ConsoleConfigService(file_path=PROJECT_DIR / "image-studio.py").config_path


def serverless_catalog_cache_file():
    return configured_path("serverless_catalog_cache_file", "serverless-model-catalog.json", "MATTS_SERVERLESS_CATALOG_CACHE_FILE", app_dir())


def model_access_drift_file():
    return configured_path("model_access_drift_file", "model-access-drift.json", "MATTS_MODEL_ACCESS_DRIFT_FILE", app_dir())


def model_deprecation_file():
    return configured_path("model_deprecation_file", "model-deprecations.json", "MATTS_MODEL_DEPRECATION_FILE", app_dir())


def dedicated_config_file():
    return configured_path("dedicated_config_file", "dedicated-inference.json", "MATTS_DEDICATED_CONFIG_FILE", app_dir())


def legacy_dedicated_config_file():
    return PROJECT_DIR / "config" / "dedicated-inference.json"


def dedicated_events_file():
    return configured_path("dedicated_events_file", "dedicated-events.jsonl", "MATTS_DEDICATED_EVENTS_FILE", app_dir())


def trace_file():
    return configured_path("trace_file", "traces.jsonl", "MATTS_TRACE_FILE", app_dir())


def event_file():
    return configured_path("event_file", "events.jsonl", "MATTS_EVENT_FILE", app_dir())


def tmux_session_registry_file():
    return configured_path("tmux_session_registry_file", "tmux-sessions.json", "MATTS_TMUX_SESSION_REGISTRY_FILE", app_dir())


def audit_file():
    return configured_path("audit_file", "audit.jsonl", "MATTS_AUDIT_FILE", app_dir())


def review_queue_file():
    return configured_path("review_queue_file", "reviews.jsonl", "MATTS_REVIEW_QUEUE_FILE", app_dir())


def replay_file():
    return configured_path("replay_file", "replays.jsonl", "MATTS_REPLAY_FILE", app_dir())


def rag_config_file():
    return configured_path("rag_config_file", "local-rag.json", "MATTS_RAG_CONFIG_FILE", app_dir())


def rag_index_file():
    return configured_path("rag_index_file", "local-rag-index.json", "MATTS_RAG_INDEX_FILE", app_dir())


def quota_file():
    return configured_path("quota_file", "quotas.jsonl", "MATTS_QUOTA_FILE", app_dir())


def auth_session_file():
    return configured_path("auth_session_file", "auth-sessions.json", "MATTS_AUTH_SESSION_FILE", app_dir())


def wallpaper_cache_dir():
    return configured_path("wallpaper_cache_dir", ".cache/matts-value-set/wallpapers", "MATTS_WALLPAPER_CACHE_DIR", home_dir())


def evals_dir():
    return configured_path("evals_dir", "evals", "MATTS_EVALS_DIR", PROJECT_DIR)


def eval_runs_dir():
    return configured_path("eval_runs_dir", "eval-runs", "MATTS_EVAL_RUNS_DIR", app_dir())


def comparison_reports_dir():
    return configured_path("comparison_reports_dir", "comparison-reports", "MATTS_COMPARISON_REPORTS_DIR", app_dir())


def session_snapshots_dir():
    return configured_path("session_snapshots_dir", "session-snapshots", "MATTS_SESSION_SNAPSHOTS_DIR", app_dir())


def config_drift_baseline_file():
    return configured_path("config_drift_baseline_file", "config-drift-baseline.json", "MATTS_CONFIG_DRIFT_BASELINE_FILE", app_dir())


def onboarding_state_file():
    return configured_path("onboarding_state_file", "onboarding.json", "MATTS_ONBOARDING_STATE_FILE", app_dir())


def rollback_backup_dir():
    return configured_path("rollback_backup_dir", "rollback-backups", "MATTS_ROLLBACK_BACKUP_DIR", app_dir())


def release_candidate_reports_dir():
    return configured_path("release_candidate_reports_dir", "release-candidates", "MATTS_RELEASE_CANDIDATE_REPORTS_DIR", app_dir())


def automation_rules_file():
    return configured_path("automation_rules_file", "automation-rules.json", "MATTS_AUTOMATION_RULES_FILE", app_dir())


def automation_execution_log_file():
    return configured_path("automation_execution_log_file", "automation-executions.jsonl", "MATTS_AUTOMATION_EXECUTION_LOG_FILE", app_dir())


def policy_bundle_file():
    return configured_path("policy_bundle_file", "policies.json", "MATTS_POLICY_BUNDLE_FILE", app_dir())


def policy_history_file():
    return configured_path("policy_history_file", "policy-history.jsonl", "MATTS_POLICY_HISTORY_FILE", app_dir())


def synthetic_load_runs_file():
    return configured_path("synthetic_load_runs_file", "synthetic-load-runs.jsonl", "MATTS_SYNTHETIC_LOAD_RUNS_FILE", app_dir())


def notification_state_file():
    return configured_path("notification_state_file", "notifications.json", "MATTS_NOTIFICATION_STATE_FILE", app_dir())


def cost_anomaly_file():
    return configured_path("cost_anomaly_file", "cost-anomalies.json", "MATTS_COST_ANOMALY_FILE", app_dir())


def workspace_bundles_dir():
    return configured_path("workspace_bundles_dir", "workspace-bundles", "MATTS_WORKSPACE_BUNDLES_DIR", app_dir())


def reporting_export_dir():
    return configured_path("reporting_export_dir", "build/reporting", "MATTS_REPORTING_EXPORT_DIR", PROJECT_DIR)


def model_registry_service():
    return ModelRegistryService(DEFAULT_MODEL_REGISTRY, MODEL_TYPES, MODEL_AUTO_ENABLE_MAX_USD)


def model_hero_service():
    return ModelHeroService(model_descriptions_dir())


def model_enabled_by_default(pricing):
    return model_registry_service().enabled_by_default(pricing)


def model_route_enabled(model):
    return model_registry_service().route_enabled(model)


def model_policy_for_model(model_id):
    rows = load_model_registry(include_disabled=True)
    record = next((row for row in rows if row.get("id") == model_id), None)
    if not record:
        return {"decision": "unknown_model_rejection", "model": model_id, "reason": "unknown_model"}
    dedicated = record.get("dedicated") if isinstance(record.get("dedicated"), dict) else {}
    access = record.get("access_status") or "not_checked"
    if record.get("serverless") and access in {"forbidden", "unauthorized"}:
        return {"decision": "access_forbidden_rejection", "model": model_id, "reason": "access_forbidden", "access_status": access}
    if dedicated.get("managed") and not model_route_enabled(record):
        return {"decision": "build_server_prompt", "model": model_id, "reason": "dedicated_not_online", "state": dedicated.get("state") or record.get("state") or "not_configured"}
    if dedicated.get("managed") and model_route_enabled(record):
        return {"decision": "dedicated_online_preference", "model": model_id, "reason": "dedicated_online", "state": dedicated.get("state") or record.get("state") or "active"}
    if not model_route_enabled(record):
        return {"decision": "model_unavailable_rejection", "model": model_id, "reason": "model_disabled", "access_status": access}
    return {}


def _normalized_model(item):
    return model_registry_service().normalize(item)


def load_model_registry(include_disabled=True):
    return model_registry_service().load(model_config_file(), include_disabled=include_disabled)


def model_registry_status(include_disabled=True):
    return model_registry_service().load_with_status(model_config_file(), include_disabled=include_disabled)


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


def model_info_payload(model_id=None):
    options = model_options(include_disabled=True)
    payload = model_hero_service().hero_cards(options)
    if model_id:
        card = payload["model_info"].get(model_id)
        if not card:
            return HTTPStatus.NOT_FOUND, {"error": "model info not found", "id": model_id}
        return HTTPStatus.OK, {"model": card}
    return HTTPStatus.OK, payload


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
        model_access_drift_file=model_access_drift_file,
        append_audit=append_audit,
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


def acknowledge_model_access_drift(data):
    data = data if isinstance(data, dict) else {}
    return serverless_catalog_service().acknowledge_access_drift(data, actor=data.get("actor") if isinstance(data.get("actor"), dict) else {})


def model_access_drift_payload():
    return serverless_catalog_service().access_drift_payload()


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
        service=CONSOLE_SERVICE_ID,
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
        otel_exporter=opentelemetry_exporter(),
        read_traces=read_traces,
        dedicated_events=dedicated_events,
        list_eval_runs=list_eval_runs,
        cost_summary_payload=cost_summary_payload,
    )


def console_status():
    return health_service().status()


def console_metrics_text():
    return health_service().metrics_text(status=console_status())


def reporting_integration_service():
    return ReportingIntegrationService(
        project_root=PROJECT_DIR,
        console_status=console_status,
        metrics_text=console_metrics_text,
        otel_exporter=opentelemetry_exporter(),
    )


def reporting_integration_payload():
    return reporting_integration_service().payload()


def reporting_export_service():
    return ReportingExportService(
        output_dir=reporting_export_dir(),
        read_traces=read_traces,
        dedicated_events=dedicated_events,
        list_eval_runs=list_eval_runs,
        list_comparison_reports=list_comparison_reports,
        audit_rows=lambda limit=5000: tail_jsonl(audit_file(), limit=limit),
        review_queue_payload=review_queue_payload,
        release_candidate_payload=release_candidate_payload,
        cost_summary_payload=cost_summary_payload,
        source_files={
            "traces": trace_file,
            "audit": audit_file,
            "dedicated_events": dedicated_events_file,
            "review_queue": review_queue_file,
            "eval_runs": eval_runs_dir,
            "comparison_reports": comparison_reports_dir,
            "release_reports": release_candidate_reports_dir,
        },
        clock=time.time,
    )


def reporting_export_status():
    return reporting_export_service().status()


def export_reporting_database(data):
    return reporting_export_service().export(data)


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
        trace_file=trace_file,
        gateway_policy_file=gateway_policy_file,
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


def opentelemetry_exporter():
    config = STARTUP_CONFIG.get("observability", {}).get("opentelemetry", {})
    return OpenTelemetryExporter(config=config, urlopen_func=urlopen, clock=time.time)


def event_bus():
    return EventBus(sinks=[JsonlEventSink(event_file)], clock=time.time)


def trace_service():
    return TraceService(trace_file=trace_file, clock=time.time, otel_exporter=opentelemetry_exporter(), event_bus=event_bus())


def append_trace(record):
    return trace_service().append(record)


def read_traces(limit=200, model=None, status=None, session=None, min_cost=None):
    return trace_service().read(limit=limit, model=model, status=status, session=session, min_cost=min_cost)


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
        local_usage_report=lambda start_date, end_date: local_usage_report(start_date, end_date),
        clock=time.time,
        event_bus=event_bus(),
        policy_service=policy_service(),
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


def dedicated_capacity_plan(data=None):
    return dedicated_service().capacity_plan(data)


def dedicated_update_from_resource(cfg, resource):
    return dedicated_service().update_from_resource(cfg, resource)


def dedicated_resource_issue(resource):
    return dedicated_service().resource_issue(resource)


def dedicated_status_payload(poll=True):
    return dedicated_service().status_payload(poll=poll)


def enforce_dedicated_policy():
    return dedicated_service().enforce_policy()


def dedicated_policy_worker(interval=30):
    while True:
        try:
            enforce_dedicated_policy()
        except Exception as exc:
            append_dedicated_event("policy_worker", "Dedicated policy worker failed", "error", {"error": str(exc)})
        time.sleep(interval)


def start_dedicated_policy_worker(interval=30):
    thread = threading.Thread(target=dedicated_policy_worker, kwargs={"interval": interval}, name="dedicated-policy-worker", daemon=True)
    thread.start()
    return thread


def dedicated_create_token(cfg):
    return dedicated_service().create_token(cfg)


def dedicated_build(data):
    return dedicated_service().build(data)


def dedicated_teardown(data=None):
    return dedicated_service().teardown(data)


def dedicated_policy(data):
    return dedicated_service().policy(data)


def dedicated_keep_alive(data):
    return dedicated_service().keep_alive(data)


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
        model_policy_for_model=model_policy_for_model,
        trace_service=trace_service(),
    )


def serverless_chat_completion(data, model, allow_unregistered=False):
    return chat_routing_service().serverless_completion(data, model, allow_unregistered=allow_unregistered)


def chat_completion(data):
    return chat_routing_service().completion(data)


def eval_service():
    return EvalService(
        evals_dir=evals_dir,
        runs_dir=eval_runs_dir,
        chat_completion=chat_completion,
        active_text_models=lambda: TEXT_MODELS,
        default_text_model=default_text_model,
        retrieval_augment=augment_with_retrieval,
        clock=time.time,
        uuid_factory=uuid.uuid4,
    )


def list_eval_datasets():
    return eval_service().list_datasets()


def list_eval_runs(limit=20):
    return eval_service().list_runs(limit=limit)


def run_eval(data):
    return eval_service().run(data)


def save_eval_dataset(data):
    return eval_service().save_dataset(data)


def build_eval_dataset(data):
    return eval_service().build_dataset(data)


def comparison_report_service():
    return ComparisonReportService(
        reports_dir=comparison_reports_dir,
        clock=time.time,
        uuid_factory=uuid.uuid4,
    )


def save_comparison_report(data):
    return comparison_report_service().save_report(data)


def list_comparison_reports():
    return comparison_report_service().list_reports()


def load_comparison_report(report_id):
    return comparison_report_service().load_report(report_id)


def export_comparison_report(report_id, fmt):
    return comparison_report_service().export_report(report_id, fmt)


def local_rag_service():
    return LocalRagService(
        project_dir=PROJECT_DIR,
        config_file=rag_config_file,
        index_file=rag_index_file,
        clock=time.time,
    )


def rag_payload():
    return local_rag_service().payload()


def save_rag_config(data):
    return local_rag_service().save_config(data)


def index_rag(data):
    return local_rag_service().index(data)


def search_rag(data):
    return local_rag_service().search(data)


def augment_with_retrieval(data, action="chat"):
    return local_rag_service().augment(data, action=action)


def proxy_get(path):
    return chat_routing_service().proxy_get(path)


def tail_jsonl(path, limit=80):
    return RuntimeStateRepository(path, "jsonl").read_jsonl(limit=limit, malformed="raw")


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
    registry_status = model_registry_status(include_disabled=True)
    return {
        "config_file": str(model_config_file()),
        "models": registry_status["models"],
        "registry_status": {key: value for key, value in registry_status.items() if key != "models"},
        "active_text_models": TEXT_MODELS,
        "selectable_text_models": selectable_text_models(),
        "text_model_options": model_options("text", include_disabled=True),
        "image_model_options": model_options("image", include_disabled=True),
        "model_metadata": model_metadata_map(),
        "model_scorecards": model_scorecards_payload(days=30)["by_model"],
        "active_image_models": IMAGE_MODELS,
        "proxy_sync": proxy_sync_payload(force=False),
        "serverless_catalog": catalog_sync,
        "model_access_drift": model_access_drift_payload(),
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
    before = load_model_registry(include_disabled=True)
    try:
        gate = eval_gate_service().enforce(
            "model_registry",
            before={"models": before},
            after={"models": normalized},
            eval_gate=data.get("eval_gate") if isinstance(data, dict) else None,
            actor=data.get("actor") if isinstance(data, dict) else None,
        )
    except EvalGateBlocked as exc:
        review_queue_service().auto_from_eval_gate(exc.gate, actor=data.get("actor") if isinstance(data, dict) else None)
        return HTTPStatus.CONFLICT, {"error": str(exc), "code": "eval_gate_blocked", "eval_gate": exc.gate}
    saved = save_model_registry(normalized)
    refresh_model_globals()
    sync = proxy_sync_payload(force=True)
    return HTTPStatus.OK, {"models": saved, "registry_status": {key: value for key, value in model_registry_status(include_disabled=True).items() if key != "models"}, "active_text_models": TEXT_MODELS, "selectable_text_models": selectable_text_models(), "text_model_options": model_options("text", include_disabled=True), "image_model_options": model_options("image", include_disabled=True), "model_metadata": model_metadata_map(), "active_image_models": IMAGE_MODELS, "config_file": str(model_config_file()), "proxy_sync": sync, "auto_enable_threshold_usd": MODEL_AUTO_ENABLE_MAX_USD, "eval_gate": gate}


def save_budget(data):
    return usage_service().save_budget(data)


def cost_forecast_service():
    return CostForecastService(
        model_registry=lambda: load_model_registry(include_disabled=True),
        default_text_model=default_text_model,
        default_image_model=default_image_model,
        load_eval_dataset=lambda dataset_id: eval_service().load_dataset(dataset_id),
        cost_summary_payload=cost_summary_payload,
        budget_file=budget_file,
        load_dedicated_config=load_dedicated_config,
        dedicated_runtime_cost_summary=dedicated_runtime_cost_summary,
        clock=time.time,
    )


def quota_planner_service():
    return QuotaPlannerService(
        config=(STARTUP_CONFIG.get("rate_limits", {}) or {}).get("quotas", {}),
        quota_file=quota_file,
        append_audit=append_audit,
        append_trace=append_trace,
        clock=time.time,
        policy_service=policy_service(),
    )


def quota_planner_payload(actor=None, actor_key=""):
    return quota_planner_service().payload(actor=actor, actor_key=actor_key)


def quota_planner_preview(path, data, actor=None, actor_key=""):
    data = data if isinstance(data, dict) else {}
    if actor is None and isinstance(data.get("actor"), dict):
        actor = data.get("actor")
    actor_key = actor_key or data.get("_quota_actor_key") or data.get("actor_key") or ""
    return quota_planner_service().preview(path, data=data, actor=actor, actor_key=actor_key)


def synthetic_load_service():
    return SyntheticLoadTesterService(
        runs_file=synthetic_load_runs_file,
        chat_completion=chat_completion,
        text_models=lambda: TEXT_MODELS,
        default_text_model=default_text_model,
        cost_forecast_payload=cost_forecast_payload,
        quota_planner_preview=quota_planner_preview,
        append_audit=append_audit,
        append_trace=append_trace,
        clock=time.time,
        uuid_factory=uuid.uuid4,
    )


def synthetic_load_payload():
    return synthetic_load_service().payload()


def preview_synthetic_load(data):
    return synthetic_load_service().preview(data)


def run_synthetic_load(data):
    return synthetic_load_service().run(data)


def quota_planner_consume(path, data, actor=None, actor_key=""):
    data = data if isinstance(data, dict) else {}
    if actor is None and isinstance(data.get("actor"), dict):
        actor = data.get("actor")
    actor_key = actor_key or data.get("_quota_actor_key") or data.get("actor_key") or ""
    return quota_planner_service().consume(path, data=data, actor=actor, actor_key=actor_key)


def context_window_service():
    return ContextWindowService(
        model_registry=lambda: load_model_registry(include_disabled=True),
        default_text_model=default_text_model,
        load_eval_dataset=lambda dataset_id: eval_service().load_dataset(dataset_id),
        clock=time.time,
    )


def context_window_payload(data):
    return context_window_service().inspect(data)


def eval_gate_service():
    return EvalGateService(
        list_datasets=list_eval_datasets,
        list_runs=list_eval_runs,
        append_audit=append_audit,
        clock=time.time,
    )


def eval_gate_payload(data):
    data = data if isinstance(data, dict) else {}
    return eval_gate_service().preview(
        data.get("surface") or "gateway_policy",
        before=data.get("before"),
        after=data.get("after"),
        policy=data.get("policy"),
        eval_gate=data.get("eval_gate"),
    )


def review_queue_service():
    return ReviewQueueService(
        review_file=review_queue_file,
        save_eval_dataset=save_eval_dataset,
        worklist_file=lambda: PROJECT_DIR / "MAIN-WORKLIST.md",
        append_audit=append_audit,
        failure_taxonomy=failure_taxonomy_service(),
        clock=time.time,
    )


def review_queue_payload(status="", severity="", reason=""):
    return {"reviews": review_queue_service().list_items(status=status, severity=severity, reason=reason)}


def create_review_item(data):
    data = data if isinstance(data, dict) else {}
    return {"review": review_queue_service().create(data, actor=data.get("actor"))}


def update_review_item(data):
    data = data if isinstance(data, dict) else {}
    item_id = data.get("id") or data.get("review_id")
    if not item_id:
        raise ValueError("review id is required")
    return {"review": review_queue_service().update(str(item_id), data, actor=data.get("actor"))}


def promote_review_item(data):
    data = data if isinstance(data, dict) else {}
    item_id = data.get("id") or data.get("review_id")
    if not item_id:
        raise ValueError("review id is required")
    target = str(data.get("target") or data.get("type") or "eval").strip().lower()
    if target in {"worklist", "worklist_followup"}:
        return review_queue_service().promote_to_worklist(str(item_id), data, actor=data.get("actor"))
    return review_queue_service().promote_to_eval(str(item_id), data, actor=data.get("actor"))


def replay_service():
    return ReplayService(
        read_traces=read_traces,
        load_chat=load_chat,
        chat_completion=chat_completion,
        default_text_model=default_text_model,
        text_models=lambda: TEXT_MODELS,
        replay_file=replay_file,
        append_trace=append_trace,
        clock=time.time,
    )


def replay_snapshot_payload(data):
    return {"snapshot": replay_service().snapshot(data.get("source") if isinstance(data, dict) and isinstance(data.get("source"), dict) else data)}


def replay_payload(data):
    return replay_service().replay(data)


def replay_records_payload(limit=50):
    return {"replays": replay_service().list_records(limit=limit)}


def repository_context_service():
    return RepositoryContextService(
        connector=GitHubContextConnector(token_provider=lambda: os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "", urlopen_func=urlopen, clock=time.time),
        project_dir=script_dir,
        worklist_text=lambda: (PROJECT_DIR / "MAIN-WORKLIST.md").read_text(encoding="utf-8") if (PROJECT_DIR / "MAIN-WORKLIST.md").exists() else "",
        clock=time.time,
    )


def repository_context_payload():
    return repository_context_service().payload()


def preview_repository_context(data):
    return repository_context_service().preview(data)


def import_repository_context(data):
    return repository_context_service().import_payload(data)


def ci_triage_service():
    return CiTriageService(repository_context=repository_context_service(), failure_taxonomy=failure_taxonomy_service(), clock=time.time)


def ci_triage_payload():
    return ci_triage_service().payload()


def preview_ci_triage(data):
    return ci_triage_service().preview(data)


def launch_ci_triage(data):
    return ci_triage_service().preview(data)


def patch_review_service():
    return PatchReviewService(
        default_project_dir=script_dir,
        tmux_session_items=tmux_session_items,
        read_traces=read_traces,
        create_session_snapshot=create_session_snapshot,
        clock=time.time,
    )


def patch_review_payload(data):
    return patch_review_service().payload(data)


def onboarding_service():
    return OnboardingChecklistService(
        state_file=onboarding_state_file,
        project_dir=lambda: PROJECT_DIR,
        token_file=token_file,
        digitalocean_token=digitalocean_token,
        digitalocean_token_paths=digitalocean_token_paths,
        active_model_access_key_info=active_model_access_key_info,
        port_open=port_open,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        proxy_sync_payload=proxy_sync_payload,
        models_payload=models_payload,
        budget_file=budget_file,
        auth_enabled=auth_enabled,
        role_token_summary=role_token_summary,
        rollback_targets_payload=rollback_targets_payload,
        dedicated_status_payload=dedicated_status_payload,
        serverless_catalog_payload=serverless_catalog_payload,
        clock=time.time,
    )


def onboarding_payload():
    return onboarding_service().payload()


def complete_onboarding_item(data):
    return onboarding_service().complete(data)


def decision_explain_service():
    return DecisionExplanationService(
        read_traces=read_traces,
        policy_files=lambda: {
            "gateway_policy": gateway_policy_file(),
            "console_config": console_config_file(),
            "model_registry": model_config_file(),
        },
        clock=time.time,
    )


def explain_decision_payload(data):
    return decision_explain_service().payload(data)


def command_palette_service():
    return CommandPaletteService(append_audit=append_audit, clock=time.time)


def command_palette_payload(query="", actor=None, context=None):
    return command_palette_service().payload(query=query, actor=actor, context=context)


def dispatch_command(data):
    return command_palette_service().dispatch(data)


def failure_taxonomy_service():
    return FailureTaxonomyService()


def failure_taxonomy_payload(payload=None, status=None, trace_id=None):
    return failure_taxonomy_service().decorate(payload, status=status, trace_id=trace_id)


def provider_health_service():
    return ProviderHealthService(
        digitalocean_health_snapshot=digitalocean_health_snapshot,
        read_traces=read_traces,
        dedicated_status_payload=dedicated_status_payload,
        models_payload=models_payload,
        proxy_sync_payload=proxy_sync_payload,
        active_model_access_key_info=active_model_access_key_info,
        failure_taxonomy=failure_taxonomy_service(),
        clock=time.time,
    )


def provider_health_payload():
    return provider_health_service().payload()


def cost_forecast_payload(data):
    return cost_forecast_service().forecast(data)


def compare_forecast_actual(forecast, actual_usd):
    return cost_forecast_service().compare_actual(forecast, actual_usd)


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


def fork_chat(data):
    return persistence_service().fork_chat(data)


def branch_comparison(chat_id):
    return persistence_service().branch_comparison(chat_id)


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
        resource_monitor=session_resource_service,
    )


def session_resource_service():
    return SessionResourceService(tmux_cmd=tmux_cmd, clock=time.time)


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


def permission_simulation(data):
    return PermissionSimulatorService(project_dir=PROJECT_DIR).simulate(data)


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
        read_traces=read_traces,
        audit_file=audit_file,
        resource_monitor=session_resource_service,
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


def session_snapshot_service():
    return SessionSnapshotService(
        snapshots_dir=session_snapshots_dir,
        tmux_session_items=tmux_session_items,
        agentboard_payload=agentboard_payload,
        read_traces=read_traces,
        tail_jsonl=tail_jsonl,
        audit_file=audit_file,
        tmux_capture=tmux_capture,
        cost_summary_payload=cost_summary_payload,
        console_status=console_status,
        model_config_file=model_config_file,
        gateway_policy_file=gateway_policy_file,
        clock=time.time,
    )


def create_session_snapshot(data):
    return session_snapshot_service().create(data)


def role_token_summary():
    raw = auth_role_tokens()
    source = "config"
    if os.environ.get("MATTS_CONSOLE_ROLE_TOKENS_JSON", "").strip():
        source = "env-json"
    elif os.environ.get("MATTS_CONSOLE_ROLE_TOKENS_FILE", "").strip():
        source = "file"
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    rows = []
    for profile in (raw if isinstance(raw, dict) else {}).values():
        if not isinstance(profile, dict):
            continue
        rows.append({
            "id": str(profile.get("id") or profile.get("name") or "role-token-user"),
            "roles": sorted(str(role) for role in (profile.get("roles") or []) if role),
            "permission_count": len(profile.get("permissions") or []),
        })
    return {"source": source, "count": len(rows), "profiles": sorted(rows, key=lambda row: row["id"])}


def config_drift_items():
    return [
        {"name": "model_registry", "label": "Active model registry", "path": model_config_file, "risk": "high", "backup_item": "model_registry"},
        {"name": "gateway_policy", "label": "Gateway policy", "path": gateway_policy_file, "risk": "high", "backup_item": "gateway_policy"},
        {"name": "console_config", "label": "Console config", "path": console_config_file, "risk": "high"},
        {"name": "dedicated_state", "label": "Dedicated state", "path": dedicated_config_file, "risk": "medium", "backup_item": "dedicated_state"},
        {"name": "budget_limits", "label": "Budget limits", "path": budget_file, "risk": "medium", "backup_item": "budgets"},
        {"name": "quota_ledger", "label": "Quota ledger", "path": quota_file, "risk": "medium"},
        {"name": "auth_sessions", "label": "Auth sessions", "path": auth_session_file, "risk": "high", "backup_item": "auth_sessions"},
        {"name": "tmux_registry", "label": "tmux session registry", "path": tmux_session_registry_file, "risk": "low", "backup_item": "tmux_registry"},
        {"name": "role_tokens", "label": "Role-token policy summary", "kind": "summary", "risk": "high", "value_provider": role_token_summary},
    ]


def config_drift_service():
    return ConfigDriftService(
        baseline_file=config_drift_baseline_file,
        items=config_drift_items(),
        append_audit=append_audit,
        clock=time.time,
    )


def config_drift_payload():
    return config_drift_service().payload()


def mark_config_drift_baseline(data):
    return config_drift_service().mark_baseline(data)


def acknowledge_config_drift(data):
    return config_drift_service().acknowledge(data)


def rollback_archive_dirs():
    return [PROJECT_DIR / "build", app_dir(), rollback_backup_dir()]


def rollback_health_check():
    return {
        "console": console_status(),
        "proxy_sync": proxy_sync_payload(force=False),
        "config_drift": config_drift_payload().get("summary"),
        "health_validate_command": "python3 scripts/health-validate.py",
    }


def rollback_wizard_service():
    return RollbackWizardService(
        archive_dirs=rollback_archive_dirs,
        backup_output_dir=rollback_backup_dir,
        item_paths={item.get("backup_item"): item.get("path") for item in config_drift_items() if item.get("backup_item")},
        append_audit=append_audit,
        health_check=rollback_health_check,
        v2_run_db=lambda: Path(os.environ.get("MATTS_V2_RUN_DB", home_dir() / ".cache/matts-value-set/studio/v2-run.sqlite3")),
        clock=time.time,
    )


def rollback_targets_payload():
    return rollback_wizard_service().targets()


def rollback_preview_payload(data):
    return rollback_wizard_service().preview(data)


def rollback_apply_payload(data):
    return rollback_wizard_service().apply(data)


def release_candidate_service():
    return ReleaseCandidateService(
        reports_dir=release_candidate_reports_dir,
        coverage_file=lambda: PROJECT_DIR / "build" / "coverage" / "coverage.json",
        worklist_file=lambda: PROJECT_DIR / "MAIN-WORKLIST.md",
        needs_operator_file=lambda: PROJECT_DIR / "docs" / "NEEDS-OPERATOR.md",
        config_drift_payload=config_drift_payload,
        review_queue_payload=review_queue_payload,
        read_traces=read_traces,
        list_eval_runs=list_eval_runs,
        clock=time.time,
    )


def release_candidate_payload():
    return release_candidate_service().payload()


def write_release_candidate_report(data):
    return release_candidate_service().write_report(data)


def automation_rules_service():
    return AutomationRulesService(
        rules_file=automation_rules_file,
        execution_log_file=automation_execution_log_file,
        create_review_item=create_review_item,
        create_session_snapshot=create_session_snapshot,
        append_audit=append_audit,
        append_dedicated_event=append_dedicated_event,
        run_eval=run_eval,
        clock=time.time,
    )


def automation_payload():
    return automation_rules_service().payload()


def save_automation_rules(data):
    data = data if isinstance(data, dict) else {}
    return {"config": automation_rules_service().save_config(data, actor=data.get("actor"))}


def test_automation_event(data):
    return automation_rules_service().run_event(data, actor=data.get("actor") if isinstance(data, dict) else {}, dry_run=True)


def run_automation_event(data):
    return automation_rules_service().run_event(data, actor=data.get("actor") if isinstance(data, dict) else {}, dry_run=False)


def run_due_automation_schedules(data):
    data = data if isinstance(data, dict) else {}
    return automation_rules_service().run_due_schedules(data, actor=data.get("actor") if isinstance(data.get("actor"), dict) else {}, dry_run=bool(data.get("dry_run")))


def cost_anomaly_service():
    return CostAnomalyService(
        state_file=cost_anomaly_file,
        read_traces=read_traces,
        list_eval_runs=list_eval_runs,
        load_dedicated_config=load_dedicated_config,
        dedicated_runtime_cost_summary=dedicated_runtime_cost_summary,
        create_review_item=create_review_item,
        append_audit=append_audit,
        clock=time.time,
    )


def cost_anomaly_payload(data=None):
    return cost_anomaly_service().payload(data)


def update_cost_anomaly(data):
    return cost_anomaly_service().update(data)


def notification_center_service():
    return NotificationCenterService(
        state_file=notification_state_file,
        review_queue_payload=review_queue_payload,
        provider_health_payload=provider_health_payload,
        release_candidate_payload=release_candidate_payload,
        automation_payload=automation_payload,
        list_eval_runs=list_eval_runs,
        dedicated_events=dedicated_events,
        cost_summary_payload=cost_summary_payload,
        cost_anomaly_payload=cost_anomaly_payload,
        quota_planner_payload=quota_planner_payload,
        audit_rows=lambda limit=200: tail_jsonl(audit_file(), limit=limit),
        failure_taxonomy=failure_taxonomy_service(),
        append_audit=append_audit,
        clock=time.time,
    )


def notification_payload(status="", severity="", category=""):
    return notification_center_service().payload({"status": status, "severity": severity, "category": category})


def update_notification(data):
    data = data if isinstance(data, dict) else {}
    return notification_center_service().update(data, actor=data.get("actor"))


def offline_mode_service():
    return OfflineModeService(
        provider_health_payload=provider_health_payload,
        serverless_catalog_payload=serverless_catalog_payload,
        models_payload=models_payload,
        list_eval_datasets=list_eval_datasets,
        list_eval_runs=list_eval_runs,
        clock=time.time,
    )


def offline_mode_payload():
    return offline_mode_service().payload()


def v2_run_store():
    return RunStore(Path(os.environ.get("MATTS_V2_RUN_DB", home_dir() / ".cache/matts-value-set/studio/v2-run.sqlite3")), clock=time.time)


def model_deprecation_service():
    return ModelDeprecationService(
        load_model_registry=load_model_registry,
        save_model_registry=save_model_registry,
        refresh_model_globals=refresh_model_globals,
        proxy_sync_payload=proxy_sync_payload,
        model_scorecards_payload=model_scorecards_payload,
        list_chats=list_chats,
        load_chat=load_chat,
        save_chat=save_chat,
        list_eval_datasets=list_eval_datasets,
        load_eval_dataset=lambda dataset_id: eval_service().load_dataset(dataset_id),
        save_eval_dataset=save_eval_dataset,
        list_eval_runs=list_eval_runs,
        list_comparison_reports=list_comparison_reports,
        load_comparison_report=load_comparison_report,
        save_comparison_report=save_comparison_report,
        gateway_policy_file=gateway_policy_file,
        state_file=model_deprecation_file,
        run_store=v2_run_store(),
        append_audit=append_audit,
        clock=time.time,
    )


def model_deprecation_payload(data=None):
    return model_deprecation_service().payload(data)


def preview_model_deprecation(data):
    return model_deprecation_service().preview(data)


def apply_model_deprecation(data):
    return model_deprecation_service().apply(data)


def rollback_model_deprecation(data):
    return model_deprecation_service().rollback(data)


def workspace_bundle_service():
    return WorkspaceBundleService(
        bundles_dir=workspace_bundles_dir,
        model_registry_file=model_config_file,
        gateway_policy_file=gateway_policy_file,
        evals_dir=evals_dir,
        comparison_reports_dir=comparison_reports_dir,
        release_reports_dir=release_candidate_reports_dir,
        run_store=v2_run_store(),
        append_audit=append_audit,
        clock=time.time,
        uuid_factory=uuid.uuid4,
        app_version=APP_VERSION,
    )


def workspace_bundle_payload():
    return workspace_bundle_service().list_bundles()


def export_workspace_bundle(data):
    data = data if isinstance(data, dict) else {}
    return workspace_bundle_service().export_bundle(data, actor=data.get("actor") if isinstance(data.get("actor"), dict) else {})


def preview_workspace_bundle_import(data):
    return workspace_bundle_service().preview_import(data if isinstance(data, dict) else {})


def import_workspace_bundle(data):
    data = data if isinstance(data, dict) else {}
    return workspace_bundle_service().import_bundle(data, actor=data.get("actor") if isinstance(data.get("actor"), dict) else {})


def plugin_registry_service():
    return PluginRegistryService(config=STARTUP_CONFIG.get("plugins", {}), root_dir=script_dir())


def plugins_payload():
    return plugin_registry_service().payload()


def analytics_payload(days=7):
    return AnalyticsService(
        read_traces=read_traces,
        local_usage_report=usage_service().local_usage_report,
        cost_summary_payload=cost_summary_payload,
        failure_taxonomy=failure_taxonomy_service(),
        clock=time.time,
    ).payload(days=days)


def model_scorecard_service():
    return ModelScorecardService(
        load_model_registry=load_model_registry,
        read_traces=read_traces,
        list_eval_runs=list_eval_runs,
        local_usage_report=usage_service().local_usage_report,
        clock=time.time,
    )


def model_scorecards_payload(days=30):
    return model_scorecard_service().payload(days=days)


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


def websocket_send_pong(conn, payload=b""):
    return websocket_protocol_service().send_control(conn, 10, payload)


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
    return AuthHandler(
        auth_enabled=auth_enabled,
        auth_token=auth_token,
        role_tokens=auth_role_tokens,
        session_verifier=lambda token: auth_session_service().verify_access(token),
        policy_service=policy_service(),
    )


def policy_service():
    return PolicyService(
        get_permissions=SENSITIVE_GET_PERMISSIONS,
        post_permissions=SENSITIVE_POST_PERMISSIONS,
        websocket_permissions=SENSITIVE_WEBSOCKET_PERMISSIONS,
    )


def auth_role_tokens():
    raw = os.environ.get("MATTS_CONSOLE_ROLE_TOKENS_JSON", "").strip()
    if raw:
        return raw
    path = os.environ.get("MATTS_CONSOLE_ROLE_TOKENS_FILE", "").strip()
    if path:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            return {}
    return STARTUP_CONFIG.get("auth", {}).get("role_tokens", {})


def audit_service():
    return AuditService(audit_file=audit_file, clock=time.time, event_bus=event_bus())


def append_audit(action, actor=None, outcome="allowed", permission="", request=None, status=None):
    return audit_service().append(action, actor=actor, outcome=outcome, permission=permission, request=request, status=status)


def audit_explorer_service():
    return AuditExplorerService(audit_file=audit_file, clock=time.time)


def audit_explorer_payload(data=None):
    return audit_explorer_service().payload(data)


def audit_explorer_export(data=None):
    data = data if isinstance(data, dict) else {}
    return audit_explorer_service().export(data, fmt=data.get("format") or "json")


def policy_as_code_service():
    return PolicyAsCodeService(
        policy_file=policy_bundle_file,
        history_file=policy_history_file,
        gateway_policy_file=gateway_policy_file,
        budget_file=budget_file,
        automation_rules_file=automation_rules_file,
        role_permissions=lambda: ROLE_PERMISSIONS,
        quota_config=lambda: (STARTUP_CONFIG.get("rate_limits", {}) or {}).get("quotas", {}),
        eval_gate_policy=lambda: {"schema_version": 1, "default_policy": STARTUP_CONFIG.get("eval_gates", {}) if isinstance(STARTUP_CONFIG.get("eval_gates"), dict) else {"require_pass": False}},
        append_audit=append_audit,
        clock=time.time,
    )


def policy_payload():
    return policy_as_code_service().payload()


def preview_policy(data):
    return policy_as_code_service().preview(data)


def apply_policy(data):
    return policy_as_code_service().apply(data)


def rollback_policy(data):
    return policy_as_code_service().rollback(data)


def auth_session_service():
    auth_config = STARTUP_CONFIG.get("auth", {}) if isinstance(STARTUP_CONFIG.get("auth"), dict) else {}
    return AuthSessionService(
        session_file=auth_session_file,
        secret=auth_token,
        clock=time.time,
        access_ttl=int(auth_config.get("session_ttl_seconds", 3600)),
        refresh_ttl=int(auth_config.get("refresh_ttl_seconds", 604800)),
    )


def create_auth_session(actor):
    payload = auth_session_service().create_session(actor)
    append_audit("auth.session.create", actor=actor, outcome="completed", permission="view_console", request={"session_id": payload.get("session_id")}, status=200)
    return 200, payload


def refresh_auth_session(data):
    token = data.get("refresh_token") if isinstance(data, dict) else ""
    status, payload = auth_session_service().refresh(token)
    append_audit("auth.session.refresh", actor={"id": payload.get("identity", {}).get("id") if isinstance(payload, dict) else "unknown", "roles": [], "source": "refresh"}, outcome="completed" if int(status) < 400 else "failed", permission="view_console", request={"session_id": payload.get("session_id") if isinstance(payload, dict) else ""}, status=status)
    return status, payload


def revoke_auth_session(data, actor):
    session_id = (data.get("session_id") if isinstance(data, dict) else "") or actor.get("session_id") or ""
    revoked = auth_session_service().revoke(session_id)
    append_audit("auth.session.revoke", actor=actor, outcome="completed" if revoked else "failed", permission="view_console", request={"session_id": session_id}, status=200 if revoked else 404)
    return (200, {"revoked": True, "session_id": session_id}) if revoked else (404, error_payload("session not found", 404, code="session_not_found", details={"session_id": session_id}))


def active_auth_sessions():
    return {"sessions": auth_session_service().active_sessions()}


_RATE_LIMITER = None


def rate_limiter():
    global _RATE_LIMITER
    config = STARTUP_CONFIG.get("rate_limits", {})
    if _RATE_LIMITER is None or _RATE_LIMITER.config != config:
        _RATE_LIMITER = RateLimitService(config=config, clock=time.time)
    return _RATE_LIMITER


def tmux_websocket_handler(authorized, identity=None):
    auth = auth_handler()
    return TmuxWebSocketHandler(
        authorized=authorized,
        identity=identity,
        permission_for=auth.permission_for,
        has_permission=auth.has_permission,
        audit=append_audit,
        tmux_target=tmux_target,
        tmux_cmd=tmux_cmd,
        websocket_accept_key=websocket_accept_key,
        websocket_send=websocket_send,
        websocket_send_pong=websocket_send_pong,
        websocket_read_frame=websocket_read_frame,
        set_pty_size=set_pty_size,
    )


def api_handler():
    return ConsoleApiHandler(
        read_history=read_history,
        list_chats=list_chats,
        load_chat=load_chat,
        branch_comparison=branch_comparison,
        list_comparison_reports=list_comparison_reports,
        load_comparison_report=load_comparison_report,
        export_comparison_report=export_comparison_report,
        tmux_session_items=tmux_session_items,
        agentboard_payload=agentboard_payload,
        plugins_payload=plugins_payload,
        analytics_payload=analytics_payload,
        model_scorecards_payload=model_scorecards_payload,
        provider_health_payload=provider_health_payload,
        model_deprecation_payload=model_deprecation_payload,
        quota_planner_payload=quota_planner_payload,
        quota_planner_preview=quota_planner_preview,
        synthetic_load_payload=synthetic_load_payload,
        preview_synthetic_load=preview_synthetic_load,
        run_synthetic_load=run_synthetic_load,
        config_drift_payload=config_drift_payload,
        mark_config_drift_baseline=mark_config_drift_baseline,
        acknowledge_config_drift=acknowledge_config_drift,
        rollback_targets_payload=rollback_targets_payload,
        rollback_preview_payload=rollback_preview_payload,
        rollback_apply_payload=rollback_apply_payload,
        release_candidate_payload=release_candidate_payload,
        write_release_candidate_report=write_release_candidate_report,
        automation_payload=automation_payload,
        save_automation_rules=save_automation_rules,
        test_automation_event=test_automation_event,
        run_automation_event=run_automation_event,
        cost_anomaly_payload=cost_anomaly_payload,
        update_cost_anomaly=update_cost_anomaly,
        notification_payload=notification_payload,
        update_notification=update_notification,
        offline_mode_payload=offline_mode_payload,
        workspace_bundle_payload=workspace_bundle_payload,
        export_workspace_bundle=export_workspace_bundle,
        preview_workspace_bundle_import=preview_workspace_bundle_import,
        import_workspace_bundle=import_workspace_bundle,
        rag_payload=rag_payload,
        save_rag_config=save_rag_config,
        index_rag=index_rag,
        search_rag=search_rag,
        augment_with_retrieval=augment_with_retrieval,
        models_payload=models_payload,
        active_auth_sessions=active_auth_sessions,
        audit_explorer_payload=audit_explorer_payload,
        audit_explorer_export=audit_explorer_export,
        policy_payload=policy_payload,
        preview_policy=preview_policy,
        apply_policy=apply_policy,
        rollback_policy=rollback_policy,
        model_info_payload=model_info_payload,
        sync_serverless_model_catalog=sync_serverless_model_catalog,
        proxy_sync_payload=proxy_sync_payload,
        active_model_access_key_info=active_model_access_key_info,
        cost_summary_payload=cost_summary_payload,
        reporting_integration_payload=reporting_integration_payload,
        reporting_export_status=reporting_export_status,
        export_reporting_database=export_reporting_database,
        cost_forecast_payload=cost_forecast_payload,
        compare_forecast_actual=compare_forecast_actual,
        context_window_payload=context_window_payload,
        eval_gate_payload=eval_gate_payload,
        review_queue_payload=review_queue_payload,
        create_review_item=create_review_item,
        update_review_item=update_review_item,
        promote_review_item=promote_review_item,
        replay_snapshot_payload=replay_snapshot_payload,
        replay_payload=replay_payload,
        replay_records_payload=replay_records_payload,
        repository_context_payload=repository_context_payload,
        preview_repository_context=preview_repository_context,
        import_repository_context=import_repository_context,
        ci_triage_payload=ci_triage_payload,
        preview_ci_triage=preview_ci_triage,
        launch_ci_triage=launch_ci_triage,
        patch_review_payload=patch_review_payload,
        onboarding_payload=onboarding_payload,
        complete_onboarding_item=complete_onboarding_item,
        explain_decision_payload=explain_decision_payload,
        command_palette_payload=command_palette_payload,
        dispatch_command=dispatch_command,
        create_session_snapshot=create_session_snapshot,
        read_traces=read_traces,
        append_trace=append_trace,
        failure_taxonomy_payload=failure_taxonomy_payload,
        wallpaper_payload=wallpaper_payload,
        dedicated_status_payload=dedicated_status_payload,
        dedicated_events=dedicated_events,
        dedicated_discovery=dedicated_discovery,
        dedicated_capacity_plan=dedicated_capacity_plan,
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
        list_eval_datasets=list_eval_datasets,
        list_eval_runs=list_eval_runs,
        run_eval=run_eval,
        save_eval_dataset=save_eval_dataset,
        build_eval_dataset=build_eval_dataset,
        save_chat=save_chat,
        fork_chat=fork_chat,
        save_comparison_report=save_comparison_report,
        delete_chat=delete_chat,
        delete_history_item=delete_history_item,
        save_models_payload=save_models_payload,
        audit_model_access_key=audit_model_access_key,
        acknowledge_model_access_drift=acknowledge_model_access_drift,
        preview_model_deprecation=preview_model_deprecation,
        apply_model_deprecation=apply_model_deprecation,
        rollback_model_deprecation=rollback_model_deprecation,
        dedicated_preflight=dedicated_preflight,
        append_dedicated_event=append_dedicated_event,
        dedicated_build=dedicated_build,
        dedicated_teardown=dedicated_teardown,
        dedicated_policy=dedicated_policy,
        dedicated_keep_alive=dedicated_keep_alive,
        save_budget=save_budget,
        digitalocean_report=digitalocean_report,
        text_models=lambda: TEXT_MODELS,
        default_image_model=default_image_model,
        permission_simulation=permission_simulation,
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


def render_main_html():
    return render_template("main.html", {
        "TEXT_MODELS": selectable_text_models(),
        "ACTIVE_TEXT_MODELS": TEXT_MODELS,
        "TEXT_MODEL_OPTIONS": model_options("text", include_disabled=True),
        "IMAGE_MODELS": IMAGE_MODELS,
        "IMAGE_MODEL_OPTIONS": model_options("image", include_disabled=True),
        "MODEL_META": model_metadata_map(),
        "THEME_CONFIG": STARTUP_CONFIG.get("theme", {}),
        "SIZES": SIZES,
        "STYLES": STYLES,
        "SCRIPT_DIR": str(script_dir()),
    })


def build_console_app():
    return ConsoleApp(
        service_name=CONSOLE_SERVICE_ID,
        version=APP_VERSION,
        config=STARTUP_CONFIG,
        request_counts=REQUEST_COUNTS,
        dependencies={
            "write_token": write_token,
            "auth_token": auth_token,
            "auth_enabled": auth_enabled,
            "auth_token_file": auth_token_file,
            "local_addresses": local_addresses,
            "start_proxy_if_needed": start_proxy_if_needed,
            "start_dedicated_policy_worker": start_dedicated_policy_worker,
            "terminal_stop_all": terminal_stop_all,
            "auth_handler": auth_handler,
            "rate_limiter": rate_limiter,
            "append_audit": append_audit,
            "console_status": console_status,
            "console_metrics_text": console_metrics_text,
            "load_template": load_template,
            "render_main_html": render_main_html,
            "quota_planner_payload": quota_planner_payload,
            "quota_planner_preview": quota_planner_preview,
            "quota_planner_consume": quota_planner_consume,
            "api_handler": api_handler,
            "wallpaper_image_response": wallpaper_image_response,
            "static_images_handler": static_images_handler,
            "refresh_auth_session": refresh_auth_session,
            "create_auth_session": create_auth_session,
            "revoke_auth_session": revoke_auth_session,
            "permission_simulation": permission_simulation,
        },
    )




class StudioHandler(BaseHTTPRequestHandler):
    server_version = CONSOLE_SERVER_VERSION

    def console_app(self):
        return getattr(getattr(self, "server", None), "app", None)

    def app_call(self, name, *args, **kwargs):
        app = self.console_app()
        if app is not None and name in app.dependencies:
            return app.call(name, *args, **kwargs)
        return globals()[name](*args, **kwargs)

    def app_increment_request(self, method):
        app = self.console_app()
        if app is not None:
            return app.increment_request(method)
        REQUEST_COUNTS[method] += 1
        return REQUEST_COUNTS[method]

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def client_disconnected(self, exc):
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return True
        return isinstance(exc, OSError) and getattr(exc, "errno", None) in {
            errno.EPIPE,
            errno.ECONNRESET,
            errno.ECONNABORTED,
        }

    def finish_headers(self):
        try:
            self.end_headers()
            return True
        except OSError as exc:
            if self.client_disconnected(exc):
                return False
            raise

    def write_response_body(self, data):
        try:
            self.wfile.write(data)
            return True
        except OSError as exc:
            if self.client_disconnected(exc):
                return False
            raise

    def send_json(self, status, payload, headers=None):
        if int(status) >= 400:
            log_error_response(getattr(self, "command", ""), urlparse(self.path).path, status, payload)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(int(status))
        self.send_header("content-type", "application/json")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("content-length", str(len(data)))
        if self.finish_headers():
            self.write_response_body(data)

    def api_not_found(self, method, path):
        api = self.app_call("api_handler")
        try:
            routes = api.known_paths(method)
        except Exception:
            routes = []
        return error_payload(
            "api endpoint not found",
            404,
            code="api_endpoint_not_found",
            details=route_not_found_details(path, method, routes),
        )

    def send_text(self, status, text, content_type="text/plain; charset=utf-8"):
        data = text.encode("utf-8")
        self.send_response(int(status))
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        if self.finish_headers():
            self.write_response_body(data)

    def read_json(self):
        length = int(self.headers.get("content-length", "0"))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError as exc:
            raise ValueError("invalid JSON request body") from exc

    def request_token(self):
        return self.app_call("auth_handler").request_token(self.path, self.headers)

    def authorized(self):
        return self.app_call("auth_handler").authorized(self.path, self.headers)

    def tmux_websocket_authorized(self):
        if not self.authorized():
            return False
        return self.app_call("auth_handler").has_permission(self.identity(), "tmux_control")

    def identity(self):
        return self.app_call("auth_handler").identity(self.path, self.headers)

    def rate_limit_key(self, actor):
        token = self.request_token()
        if token:
            return "token:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:20]
        client = self.client_address[0] if getattr(self, "client_address", None) else "local"
        return "actor:%s:%s:%s" % (actor.get("source") or "none", actor.get("id") or "anonymous", client)

    def check_rate_limit(self, method, path, actor):
        if not path.startswith("/api/"):
            return {"allowed": True, "headers": {}}
        return self.app_call("rate_limiter").check(self.rate_limit_key(actor), method, path)

    def quota_headers(self, decision):
        if not isinstance(decision, dict) or not decision.get("managed"):
            return {}
        headers = {"x-quota-status": str(decision.get("status") or "allowed")}
        remaining = [
            float(check.get("remaining"))
            for check in decision.get("checks", [])
            if check.get("window") == "daily" and check.get("metric") == "requests"
        ]
        if remaining:
            headers["x-quota-remaining-today"] = str(int(min(remaining)))
        return headers

    def quota_block_payload(self, decision):
        return error_payload(
            "quota exceeded",
            429,
            code="quota_exceeded",
            details={
                "action": decision.get("action"),
                "route": decision.get("route"),
                "warnings": decision.get("warnings", []),
                "blocks": decision.get("blocks", []),
                "checks": decision.get("checks", []),
            },
        )

    def send_html(self, html):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        if self.finish_headers():
            self.write_response_body(data)

    def send_login(self):
        self.send_html(self.app_call("load_template", "login.html"))

    def send_unauthorized(self):
        if self.path == "/" or self.path.startswith("/?"):
            self.send_login()
            return
        self.send_json(401, error_payload("console auth token required", 401, code="console_auth_required"))

    def do_websocket_tmux(self):
        return tmux_websocket_handler(self.authorized, identity=self.identity).handle(self)

    def do_GET(self):
        self.app_increment_request("GET")
        raw_path = urlparse(self.path).path
        version_info = api_version_info(raw_path, self.headers)
        path = version_info["path"]
        if path == "/ws/tmux":
            return self.do_websocket_tmux()
        if path == "/health":
            return self.send_json(200, {"status": "ok", "service": CONSOLE_SERVICE_ID, "version": APP_VERSION})
        if path == "/ready":
            status = self.app_call("console_status")
            code = 200 if status["status"] == "ok" else 503
            return self.send_json(code, status)
        if path == "/version":
            return self.send_json(200, {"service": CONSOLE_SERVICE_ID, "version": APP_VERSION, "server": self.server_version})
        if path == "/metrics":
            return self.send_text(200, self.app_call("console_metrics_text"), "text/plain; version=0.0.4; charset=utf-8")
        if not self.authorized():
            return self.send_unauthorized()
        version_headers = api_version_headers(version_info)
        if version_info.get("unsupported"):
            return self.send_json(400, error_payload("unsupported API version", 400, code="unsupported_api_version", details={"requested_version": version_info.get("requested_version"), "supported_versions": ["v1"]}), headers=version_headers)
        actor = self.identity()
        rate = self.check_rate_limit("GET", path, actor)
        response_headers = {**version_headers, **rate.get("headers", {})}
        if not rate.get("allowed", True):
            return self.send_json(429, error_payload("rate limit exceeded", 429, code="rate_limit_exceeded", details={"limit": rate.get("limit"), "reset": rate.get("reset"), "retry_after": rate.get("retry_after")}), headers=response_headers)
        auth = self.app_call("auth_handler")
        auth_decision = auth.policy_decision("GET", path, actor)
        permission_action = auth.permission_for("GET", path)
        if not auth_decision.allowed:
            effects = auth_decision.effects
            self.app_call("append_audit", effects.get("audit_action") or auth_decision.action, actor=actor, outcome="denied", permission=effects.get("permission") or "", request={"path": path, "policy_decision": auth_decision.to_dict()}, status=403)
            return self.send_json(403, error_payload("permission denied", 403, code="permission_denied", details={"permission": effects.get("permission") or "", "actor": actor.get("id"), "policy_decision": auth_decision.to_dict()}), headers=response_headers)
        if path == "/":
            self.send_html(self.app_call("render_main_html"))
            return
        if path == "/terminal":
            self.send_html(self.app_call("load_template", "terminal.html"))
            return
        if path == "/api/quotas":
            return self.send_json(200, self.app_call("quota_planner_payload", actor=actor, actor_key=self.rate_limit_key(actor)), headers=response_headers)
        if path.startswith("/api/") and path != "/api/wallpaper/image":
            handled, status, payload = self.app_call("api_handler").get(path, parse_qs(urlparse(self.path).query))
            if handled:
                return self.send_json(status, payload, headers=response_headers)
            return self.send_json(404, self.api_not_found("GET", path), headers=response_headers)
        if path == "/api/wallpaper/image":
            query = parse_qs(urlparse(self.path).query)
            remote = (query.get("remote") or [""])[0]
            image_id = (query.get("id") or ["wallpaper"])[0]
            try:
                status, data, content_type = self.app_call("wallpaper_image_response", remote, image_id)
            except Exception as exc:
                return self.send_json(502, error_payload("wallpaper image fetch failed", 502, code="wallpaper_image_fetch_failed", details={"reason": str(exc)}), headers=response_headers)
            self.send_response(int(status))
            self.send_header("content-type", content_type)
            for key, value in response_headers.items():
                self.send_header(key, value)
            self.send_header("cache-control", "public, max-age=86400")
            self.send_header("content-length", str(len(data)))
            if self.finish_headers():
                self.write_response_body(data)
            return
        if path.startswith("/images/"):
            response = self.app_call("static_images_handler").file_response(path, default_content_type="image/png")
            if response is None:
                self.send_error(404)
                return
            self.send_response(response["status"])
            self.send_header("content-type", response["content_type"])
            for key, value in response["headers"].items():
                self.send_header(key, value)
            if self.finish_headers():
                self.write_response_body(response["data"])
            return
        self.send_error(404)

    def do_POST(self):
        self.app_increment_request("POST")
        raw_path = urlparse(self.path).path
        version_info = api_version_info(raw_path, self.headers)
        path = version_info["path"]
        version_headers = api_version_headers(version_info)
        if path == "/api/auth/refresh":
            if version_info.get("unsupported"):
                return self.send_json(400, error_payload("unsupported API version", 400, code="unsupported_api_version", details={"requested_version": version_info.get("requested_version"), "supported_versions": ["v1"]}), headers=version_headers)
            try:
                data = self.read_json()
            except ValueError as exc:
                return self.send_json(400, error_payload(str(exc), 400, code="invalid_json_body", details={"path": path}), headers=version_headers)
            status, payload = self.app_call("refresh_auth_session", data)
            return self.send_json(status, payload, headers=version_headers)
        if not self.authorized():
            return self.send_unauthorized()
        if version_info.get("unsupported"):
            return self.send_json(400, error_payload("unsupported API version", 400, code="unsupported_api_version", details={"requested_version": version_info.get("requested_version"), "supported_versions": ["v1"]}), headers=version_headers)
        actor = self.identity()
        rate = self.check_rate_limit("POST", path, actor)
        response_headers = {**version_headers, **rate.get("headers", {})}
        if not rate.get("allowed", True):
            return self.send_json(429, error_payload("rate limit exceeded", 429, code="rate_limit_exceeded", details={"limit": rate.get("limit"), "reset": rate.get("reset"), "retry_after": rate.get("retry_after")}), headers=response_headers)
        auth = self.app_call("auth_handler")
        auth_decision = auth.policy_decision("POST", path, actor)
        permission_action = auth.permission_for("POST", path)
        if not auth_decision.allowed:
            effects = auth_decision.effects
            self.app_call("append_audit", effects.get("audit_action") or auth_decision.action, actor=actor, outcome="denied", permission=effects.get("permission") or "", request={"path": path, "policy_decision": auth_decision.to_dict()}, status=403)
            return self.send_json(403, error_payload("permission denied", 403, code="permission_denied", details={"permission": effects.get("permission") or "", "actor": actor.get("id"), "policy_decision": auth_decision.to_dict()}), headers=response_headers)
        try:
            data = self.read_json()
        except ValueError as exc:
            return self.send_json(400, error_payload(str(exc), 400, code="invalid_json_body", details={"path": path}), headers=response_headers)
        if isinstance(data, dict):
            data.setdefault("actor", actor)
            data.setdefault("session_id", actor.get("id"))
            if permission_action and not data.get("operator"):
                data["operator"] = actor.get("id")
            if path == "/api/tmux/start":
                data["permission_summary"] = self.app_call("permission_simulation", data)
        if path == "/api/auth/session":
            status, payload = self.app_call("create_auth_session", actor)
            return self.send_json(status, payload, headers=response_headers)
        if path == "/api/auth/revoke":
            status, payload = self.app_call("revoke_auth_session", data, actor)
            return self.send_json(status, payload, headers=response_headers)
        if path == "/api/quota-planner":
            target_path = data.get("path") or ""
            decision = self.app_call("quota_planner_preview", target_path, data, actor=actor, actor_key=self.rate_limit_key(actor))
            return self.send_json(200, decision, headers={**response_headers, **self.quota_headers(decision)})
        if permission_action:
            permission, action = permission_action
            self.app_call("append_audit", action, actor=actor, outcome="allowed", permission=permission, request={"path": path, "body": data}, status=0)
        quota_decision = self.app_call("quota_planner_consume", path, data, actor=actor, actor_key=self.rate_limit_key(actor))
        response_headers = {**response_headers, **self.quota_headers(quota_decision)}
        if not quota_decision.get("allowed", True):
            return self.send_json(429, self.quota_block_payload(quota_decision), headers=response_headers)
        handled, status, payload = self.app_call("api_handler").post(path, data)
        if handled and isinstance(payload, dict) and quota_decision.get("managed"):
            payload.setdefault("quota", quota_decision)
        if permission_action:
            permission, action = permission_action
            self.app_call("append_audit", action, actor=actor, outcome="completed" if int(status) < 400 else "failed", permission=permission, request={"path": path}, status=status)
        if handled:
            return self.send_json(status, payload, headers=response_headers)
        self.send_json(404, self.api_not_found("POST", path), headers=response_headers)


def main():
    configure_console_logging(STARTUP_CONFIG["logging"]["level"])
    parser = argparse.ArgumentParser(description="Run the MDE LLM-PROXY unified web console.")
    parser.add_argument("--host", default=str(STARTUP_CONFIG["server"]["host"]))
    parser.add_argument("--port", type=int, default=int(STARTUP_CONFIG["server"]["port"]))
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    app = build_console_app()
    console_token = app.startup()
    server = app.make_server(args.host, args.port, StudioHandler)
    url = "http://%s:%d/" % (args.host, args.port)
    print("%s: %s" % (CONSOLE_DISPLAY_NAME, url), flush=True)
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
        app.shutdown()


if __name__ == "__main__":
    main()
