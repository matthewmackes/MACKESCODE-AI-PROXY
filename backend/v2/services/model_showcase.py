"""Model showcase and Whats New payloads for the v2 React interface."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from backend.v2.services.legacy_console import LegacyConsoleAdapter
from src.console.services.model_registry import ModelRegistryService
from src.console.services.model_scorecards import health_grade, median_latency_ms


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_CONFIG = PROJECT_DIR / "config" / "models.json"
DEFAULT_MODEL_ACCESS_STATE = Path.home() / ".cache" / "matts-value-set" / "studio" / "model-access-state.json"
MODEL_TYPES = {"text", "image", "embedding", "rerank", "audio", "video", "router", "unknown"}

COUNTRY_PALETTES: dict[str, dict[str, str]] = {
    "United States": {"name": "USA", "accent": "#0f62fe", "secondary": "#da1e28", "surface": "#edf5ff", "text": "#001d6c"},
    "China": {"name": "China", "accent": "#da1e28", "secondary": "#f1c21b", "surface": "#fff1f1", "text": "#750e13"},
    "France": {"name": "France", "accent": "#0f62fe", "secondary": "#fa4d56", "surface": "#edf5ff", "text": "#001d6c"},
    "Germany": {"name": "Germany", "accent": "#525252", "secondary": "#f1c21b", "surface": "#f4f4f4", "text": "#161616"},
    "United Kingdom": {"name": "United Kingdom", "accent": "#0f62fe", "secondary": "#da1e28", "surface": "#edf5ff", "text": "#001d6c"},
    "Unknown": {"name": "Unknown", "accent": "#6f6f6f", "secondary": "#8d8d8d", "surface": "#f4f4f4", "text": "#262626"},
}

BRAND_ARTWORK: dict[str, dict[str, str]] = {
    "Anthropic": {"logo": "https://cdn.simpleicons.org/anthropic/000000", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=anthropic", "brand_url": "https://www.anthropic.com/", "background": "brand_nation_panel"},
    "OpenAI": {"logo": "https://cdn.simpleicons.org/openai/000000", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=openai", "brand_url": "https://openai.com/", "background": "brand_nation_panel"},
    "DeepSeek": {"logo": "https://cdn.simpleicons.org/deepseek/4D6BFE", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=deepseek", "brand_url": "https://www.deepseek.com/", "background": "brand_nation_panel"},
    "Mistral AI": {"logo": "https://cdn.simpleicons.org/mistralai/FA520F", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=mistral", "brand_url": "https://mistral.ai/", "background": "brand_nation_panel"},
    "Alibaba Qwen": {"logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=alibabacloud", "brand_url": "https://qwenlm.github.io/", "background": "brand_nation_panel"},
    "Alibaba": {"logo": "https://cdn.simpleicons.org/alibabacloud/FF6A00", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=alibabacloud", "brand_url": "https://www.alibabacloud.com/", "background": "brand_nation_panel"},
    "Meta": {"logo": "https://cdn.simpleicons.org/meta/0467DF", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=meta", "brand_url": "https://ai.meta.com/", "background": "brand_nation_panel"},
    "Google": {"logo": "https://cdn.simpleicons.org/google/4285F4", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=google", "brand_url": "https://ai.google/", "background": "brand_nation_panel"},
    "NVIDIA": {"logo": "https://cdn.simpleicons.org/nvidia/76B900", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=nvidia", "brand_url": "https://www.nvidia.com/en-us/ai/", "background": "brand_nation_panel"},
    "Microsoft": {"logo": "https://cdn.simpleicons.org/microsoft/5E5E5E", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=microsoft", "brand_url": "https://www.microsoft.com/ai", "background": "brand_nation_panel"},
    "Xiaomi": {"logo": "https://cdn.simpleicons.org/xiaomi/FF6900", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=xiaomi", "brand_url": "https://www.mi.com/global/", "background": "brand_nation_panel"},
    "Stability AI": {"logo": "https://cdn.simpleicons.org/stabilityai/000000", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=stability", "brand_url": "https://stability.ai/", "background": "brand_nation_panel"},
    "DigitalOcean": {"logo": "https://cdn.simpleicons.org/digitalocean/0080FF", "source": "Simple Icons public CDN", "source_url": "https://simpleicons.org/?q=digitalocean", "brand_url": "https://www.digitalocean.com/products/gradientai", "background": "brand_nation_panel"},
}

BUNDLED_ARTWORK_KEYS: dict[str, str] = {
    "Alibaba": "alibaba",
    "Alibaba Qwen": "alibaba",
    "Anthropic": "anthropic",
    "Arcee AI": "arcee",
    "BAAI": "baai",
    "Black Forest Labs": "blackforest",
    "DeepSeek": "deepseek",
    "DigitalOcean": "digitalocean",
    "Google": "google",
    "Meta": "meta",
    "Microsoft": "microsoft",
    "MiniMax": "minimax",
    "Mistral AI": "mistral",
    "Moonshot AI": "moonshot",
    "NVIDIA": "nvidia",
    "OpenAI": "openai",
    "Stability AI": "stability",
    "Xiaomi": "xiaomi",
    "Zhipu AI": "zhipu",
}

DIGITALOCEAN_LLM_LINKS = [
    {
        "label": "Serverless Inference",
        "url": "https://docs.digitalocean.com/products/inference/how-to/use-serverless-inference/",
        "category": "docs",
    },
    {
        "label": "Available Inference Models",
        "url": "https://docs.digitalocean.com/products/inference/details/models/",
        "category": "models",
    },
    {
        "label": "Dedicated Inference",
        "url": "https://docs.digitalocean.com/products/inference/how-to/use-dedicated-inference/",
        "category": "dedicated",
    },
    {
        "label": "Serverless Inference API",
        "url": "https://docs.digitalocean.com/reference/api/reference/serverless-inference/",
        "category": "api",
    },
    {
        "label": "DigitalOcean Status",
        "url": "https://status.digitalocean.com/",
        "category": "status",
    },
]


HEALTH_TRACE_LIMIT = 2000
HEALTH_CACHE_TTL_SECONDS = 15.0
UNMEASURED_HEALTH: dict[str, Any] = {"grade": None, "success_rate": None, "p50_latency_ms": None, "requests": 0, "measured": False}

# Single shared adapter so the default health path reuses one lazily loaded
# legacy console module instead of adding another image-studio exec per
# ModelShowcaseService instance (chat, models, code, and create each build one).
_HEALTH_LEGACY_ADAPTER = LegacyConsoleAdapter()


class _HealthIndex:
    """Aggregate recent trace telemetry into per-model health grades.

    Mirrors the ``usage.py`` TTL cache pattern: the cached index is keyed on
    the trace file's ``(path, st_mtime_ns, st_size, limit)`` signature so a
    trace append invalidates it immediately, while the TTL only bounds how
    long a stale-but-identical read is retained. A lock keeps the shared
    module-level instance safe across request threads, and missing or
    unreadable trace data never raises; it just yields an empty index so
    every model reports as unmeasured.
    """

    def __init__(
        self,
        read_traces: Callable[..., Any] | None = None,
        trace_file: Callable[[], Any] | None = None,
        clock: Callable[[], float] | None = None,
        ttl_seconds: float = HEALTH_CACHE_TTL_SECONDS,
        limit: int = HEALTH_TRACE_LIMIT,
    ) -> None:
        self.read_traces = read_traces
        self.trace_file = trace_file
        self.clock = clock or time.time
        self.ttl_seconds = ttl_seconds
        self.limit = limit
        self._lock = threading.Lock()
        self._cached_signature: Any = None
        self._cached_index: dict[str, dict[str, Any]] | None = None
        self._expires_at = 0.0

    def health_for(self, model_id: str) -> dict[str, Any]:
        entry = self.index().get(str(model_id or ""))
        return dict(entry) if entry else dict(UNMEASURED_HEALTH)

    def index(self) -> dict[str, dict[str, Any]]:
        now = self.clock()
        signature = self._signature()
        with self._lock:
            if self._cached_index is not None and self._cached_signature == signature and now < self._expires_at:
                return self._cached_index
        index = self._build_index()
        with self._lock:
            self._cached_signature = signature
            self._cached_index = index
            self._expires_at = now + self.ttl_seconds
        return index

    def _resolve_trace_file(self) -> Path | None:
        try:
            if self.trace_file is not None:
                return Path(self.trace_file())
            if self.read_traces is not None:
                return None
            trace_file = getattr(_HEALTH_LEGACY_ADAPTER.module(), "trace_file", None)
            return Path(trace_file()) if callable(trace_file) else None
        except Exception:
            return None

    def _signature(self) -> tuple[Any, ...]:
        path = self._resolve_trace_file()
        if path is None:
            return ("unresolved", None, None, self.limit)
        try:
            stat = path.stat()
        except OSError:
            return (str(path), None, None, self.limit)
        return (str(path), stat.st_mtime_ns, stat.st_size, self.limit)

    def _read_rows(self) -> list[dict[str, Any]]:
        try:
            read_traces = self.read_traces or getattr(_HEALTH_LEGACY_ADAPTER.module(), "read_traces", None)
            rows = read_traces(limit=self.limit) if callable(read_traces) else []
        except Exception:
            return []
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def _build_index(self) -> dict[str, dict[str, Any]]:
        aggregates: dict[str, dict[str, Any]] = {}
        for row in self._read_rows():
            is_error = str(row.get("status") or "") == "error"
            try:
                latency = int(row.get("latency_ms"))
            except (TypeError, ValueError):
                latency = 0
            for model_id in {str(key) for key in (row.get("routed_model"), row.get("requested_model")) if key}:
                item = aggregates.setdefault(model_id, {"requests": 0, "errors": 0, "latencies": []})
                item["requests"] += 1
                item["errors"] += 1 if is_error else 0
                if latency:
                    item["latencies"].append(latency)
        index: dict[str, dict[str, Any]] = {}
        for model_id, item in aggregates.items():
            success_rate = round((item["requests"] - item["errors"]) / item["requests"], 4) if item["requests"] else None
            p50 = median_latency_ms(sorted(item["latencies"]))
            index[model_id] = {
                "grade": health_grade(success_rate, p50),
                "success_rate": success_rate,
                "p50_latency_ms": p50,
                "requests": item["requests"],
                "measured": True,
            }
        return index


# Shared index so every default-constructed showcase service (one per v2 api
# module) reuses one cached aggregation of the same trace file.
_HEALTH_INDEX = _HealthIndex()


class ModelShowcaseService:
    """Build Carbon-friendly model and startup discovery payloads."""

    def __init__(
        self,
        model_config: Path | None = None,
        model_access_state: Path | None = None,
        clock: Any | None = None,
        read_traces: Callable[..., Any] | None = None,
        trace_file: Callable[[], Any] | None = None,
    ) -> None:
        self.model_config = model_config or Path(os.environ.get("MATTS_MODEL_CONFIG_FILE", DEFAULT_MODEL_CONFIG))
        self.model_access_state = model_access_state or Path(os.environ.get("MATTS_MODEL_ACCESS_STATE_FILE", DEFAULT_MODEL_ACCESS_STATE))
        self.clock = clock or time.time
        self.registry = ModelRegistryService([], MODEL_TYPES, float(os.environ.get("MATTS_AUTO_ENABLE_MAX_USD", "0.45")))
        if read_traces is None and trace_file is None:
            self.health_index = _HEALTH_INDEX
        else:
            self.health_index = _HealthIndex(read_traces=read_traces, trace_file=trace_file, clock=self.clock)

    def registry_status(self) -> dict[str, Any]:
        return self.registry.load_with_status(self.model_config, include_disabled=True, access_state=self.access_state())

    def access_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.model_access_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "models": {}}
        return data if isinstance(data, dict) else {"schema_version": 1, "models": {}}

    def country_palette(self, origin: str) -> dict[str, str]:
        return dict(COUNTRY_PALETTES.get(origin or "Unknown") or COUNTRY_PALETTES["Unknown"])

    def artwork_for(self, profile: dict[str, Any]) -> dict[str, Any]:
        brand = str(profile.get("brand") or "DigitalOcean")
        configured = BRAND_ARTWORK.get(brand, {})
        logo = str(profile.get("logo") or configured.get("logo") or "")
        brand_url = str(configured.get("brand_url") or "")
        background = str(configured.get("background") or "generated_brand_panel")
        render_key = BUNDLED_ARTWORK_KEYS.get(brand, "")
        render_mode = "bundled_svg" if render_key else "generated_initials"
        sources = []
        if logo:
            sources.append({
                "kind": "logo",
                "url": logo,
                "source": configured.get("source") or "model registry",
                "source_url": configured.get("source_url") or logo,
                "usage_notes": "Publicly reachable brand artwork; operator should replace if stricter trademark guidance is required.",
            })
        else:
            sources.append({
                "kind": "fallback",
                "url": "",
                "source": "Local bundled brand art" if render_key else "Generated model initials",
                "source_url": "",
                "usage_notes": "No public logo URL is configured for this brand; the UI renders local bundled brand art over the training-nation palette." if render_key else "No public logo URL is configured for this brand; the UI renders a generated family initial over the training-nation palette.",
            })
        if brand_url:
            sources.append({
                "kind": "brand",
                "url": brand_url,
                "source": "Company or model family public site",
                "source_url": brand_url,
                "usage_notes": "Use this public brand/model page for manual artwork review and attribution checks.",
            })
        sources.append({
            "kind": "background",
            "url": "",
            "source": "Training-nation palette",
            "source_url": "",
            "usage_notes": "Background treatment is generated from the model family and training-nation palette when no approved product background is configured.",
        })
        return {
            "logo": logo,
            "brand_url": brand_url,
            "background": background,
            "render": {
                "mode": render_mode,
                "key": render_key,
                "label": brand,
            },
            "sources": sources,
            "policy_notes": "Public artwork URLs are display references only; local operators can replace them with approved vendor assets in the model registry.",
        }

    def model_card(self, model: dict[str, Any]) -> dict[str, Any]:
        profile = self.registry.brand_profile(model)
        origin = str(profile.get("origin") or "Unknown")
        palette = self.country_palette(origin)
        style = self.registry.generated_style(model, profile)
        new_until = self.registry.model_new_until(model)
        artwork = self.artwork_for(profile)
        access_status = str(model.get("access_status") or ("ok" if self.registry.route_enabled(model) else "not_checked"))
        return {
            "id": model.get("id"),
            "display_name": model.get("display_name") or model.get("id"),
            "type": model.get("type") or "unknown",
            "provider": model.get("provider") or "DigitalOcean",
            "owned_by": model.get("owned_by") or "",
            "enabled": bool(model.get("enabled")),
            "route_enabled": self.registry.route_enabled(model),
            "access_status": access_status,
            "pricing": model.get("pricing") if isinstance(model.get("pricing"), dict) else {},
            "cost_label": self.registry.readable_cost(model),
            "context_window": int(model.get("context_window") or 0),
            "max_output_tokens": int(model.get("max_output_tokens") or 0),
            "created": model.get("created") or 0,
            "new_until": new_until,
            "is_new": bool(new_until),
            "family": profile.get("family") or "General",
            "company": profile.get("brand") or model.get("owned_by") or "DigitalOcean",
            "training_nation": origin,
            "nation_palette": palette,
            "style": {
                **style,
                "accent": palette["accent"],
                "secondary": palette["secondary"],
                "surface": palette["surface"],
                "text": palette["text"],
            },
            "artwork": artwork,
            "use_case": self.registry.use_case(model, profile),
            "serverless": bool(model.get("serverless")),
            "pricing_source": model.get("pricing_source") or "",
            "last_error": model.get("last_error") or "",
            "health": self.health_index.health_for(str(model.get("id") or "")),
        }

    def payload(self) -> dict[str, Any]:
        status = self.registry_status()
        cards = [self.model_card(model) for model in status.get("models", []) if isinstance(model, dict)]
        cards.sort(key=lambda item: (not item.get("route_enabled"), str(item.get("training_nation")), str(item.get("company")), str(item.get("display_name"))))
        summary: dict[str, Any] = {
            "total": len(cards),
            "route_enabled": len([card for card in cards if card.get("route_enabled")]),
            "new": len([card for card in cards if card.get("is_new")]),
            "serverless": len([card for card in cards if card.get("serverless")]),
            "by_nation": {},
            "by_company": {},
            "by_type": {},
        }
        for key, field in (("by_nation", "training_nation"), ("by_company", "company"), ("by_type", "type")):
            counts: dict[str, int] = {}
            for card in cards:
                value = str(card.get(field) or "Unknown")
                counts[value] = counts.get(value, 0) + 1
            summary[key] = counts
        return {
            "generated_at": self.clock(),
            "registry": {key: status.get(key) for key in ("config_file", "exists", "schema_version", "valid", "source", "issues", "total_models", "route_enabled_models")},
            "summary": summary,
            "models": cards,
            "palettes": COUNTRY_PALETTES,
            "artwork_policy": {
                "mode": "public_reachable_with_source_tracking",
                "notes": "Use public company/model artwork with source, attribution, and usage notes; prefer official sources when available.",
            },
        }

    def whats_new(self) -> dict[str, Any]:
        payload = self.payload()
        models = payload["models"]
        new_models = [model for model in models if model.get("is_new")]
        attention = [
            model for model in models
            if model.get("access_status") in {"not_checked", "forbidden", "rate_limited", "probe_failed", "removed"}
        ]
        return {
            "generated_at": self.clock(),
            "title": "Whats New",
            "summary": {
                "new_models": len(new_models),
                "attention": len(attention),
                "route_enabled": payload["summary"]["route_enabled"],
                "total_models": payload["summary"]["total"],
            },
            "new_models": new_models[:24],
            "attention": attention[:24],
            "digitalocean": {
                "catalog": payload["registry"],
                "links": DIGITALOCEAN_LLM_LINKS,
                "raw": {
                    "model_count": payload["summary"]["total"],
                    "route_enabled": payload["summary"]["route_enabled"],
                    "by_type": payload["summary"]["by_type"],
                },
            },
        }

    def discover(self, legacy_adapter: Any) -> dict[str, Any]:
        result = legacy_adapter._safe_call("sync_serverless_model_catalog", {}, True, True)
        if not isinstance(result, dict):
            result = {"result": result}
        return {
            "discovery": result,
            "whats_new": self.whats_new(),
            "showcase": self.payload(),
        }
