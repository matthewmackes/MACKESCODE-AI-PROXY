"""Provider-backed Research search adapters for the v2 interface."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.v2.services.model_showcase import DIGITALOCEAN_LLM_LINKS, ModelShowcaseService
from src.console.services.local_rag import LocalRagService


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_DIR = Path.home() / ".cache" / "matts-value-set" / "studio"

BING_KEY_ENV = ("BING_SEARCH_API_KEY", "BING_SEARCH_KEY", "AZURE_BING_SEARCH_KEY")
GOOGLE_KEY_ENV = ("GOOGLE_SEARCH_API_KEY", "GOOGLE_API_KEY", "GOOGLE_PROGRAMMABLE_SEARCH_API_KEY")
GOOGLE_CX_ENV = ("GOOGLE_SEARCH_CX", "GOOGLE_CSE_ID", "GOOGLE_PROGRAMMABLE_SEARCH_CX")
BRAVE_KEY_ENV = ("BRAVE_SEARCH_API_KEY", "BRAVE_SEARCH_TOKEN")
MAP_KEY_ENV = ("MAPBOX_ACCESS_TOKEN", "GOOGLE_MAPS_API_KEY")

ENGINE_ORDER = (
    "bing",
    "google",
    "brave",
    "images",
    "examples",
    "mapping",
    "wikipedia",
    "technical-docs",
    "digitalocean-docs",
    "local-rag",
)
WEB_SEARCH_ENGINES = ("bing", "google", "brave")
RESEARCH_SOURCE_ENGINE_LABELS = {
    "images": "images",
    "examples": "examples",
    "mapping": "mapping services",
    "wikipedia": "Wikipedia",
    "technical-docs": "technical documentation",
}
RESEARCH_SOURCE_ENGINE_IDS = tuple(RESEARCH_SOURCE_ENGINE_LABELS.keys())
MODE_LIMITS = {"Fast": 4, "Balanced": 6, "Deep": 10}
DEFAULT_RESEARCH_MODEL_PRICE_LIMIT = 0.50
DEFAULT_RESEARCH_FAST_MAX_LATENCY_MS = 2500
DEFAULT_RESEARCH_LLM_TIMEOUT_SECONDS = 12
FAST_RESPONSE_FAMILY_HINTS = (
    "flash",
    "mini",
    "nano",
    "oss-20b",
    "mimo-v2.5",
    "mistral-3-14b",
    "nemotron-3-super",
)
RESEARCH_ROLE_SPECS = (
    {
        "role": "analyst_us",
        "label": "US low-cost generalist",
        "focus": "Broad answer quality, product framing, and operator impact.",
        "nation": "United States",
        "preferred": ("openai-gpt-oss-20b", "nvidia-nemotron-3-super-120b", "gemma", "llama"),
    },
    {
        "role": "analyst_china",
        "label": "China low-cost independent analyst",
        "focus": "Independent reasoning path, model-market contrast, and overlooked alternatives.",
        "nation": "China",
        "preferred": ("mimo-v2.5", "deepseek-4-flash", "qwen", "alibaba", "minimax"),
    },
    {
        "role": "analyst_global",
        "label": "Global verifier",
        "focus": "Evidence checking, caveats, and concise decision support.",
        "nation": "",
        "preferred": ("mistral-3-14b", "mistral", "nvidia-nemotron-3-super-120b", "openai-gpt-oss-20b"),
    },
)
COORDINATOR_SPEC = {
    "role": "coordinator",
    "label": "Research coordinator",
    "focus": "Merge analyst outputs and search evidence into one direct answer.",
    "nation": "",
    "preferred": ("nvidia-nemotron-3-super-120b", "openai-gpt-oss-20b", "mistral-3-14b", "mimo-v2.5"),
}


def default_local_rag_service() -> LocalRagService:
    config_file = Path(os.environ.get("MATTS_V2_RAG_CONFIG_FILE", DEFAULT_RUNTIME_DIR / "v2-rag-config.json"))
    index_file = Path(os.environ.get("MATTS_V2_RAG_INDEX_FILE", DEFAULT_RUNTIME_DIR / "v2-rag-index.json"))
    return LocalRagService(
        project_dir=Path(os.environ.get("MATTS_V2_RAG_PROJECT_DIR", PROJECT_DIR)),
        config_file=lambda: config_file,
        index_file=lambda: index_file,
    )


def _terms(text: str) -> list[str]:
    return [term for term in re.findall(r"[a-zA-Z0-9_]{3,}", str(text or "").lower()) if term not in {"the", "and", "for", "with", "that", "this"}]


def _first_env(env: Mapping[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = str(env.get(name) or "").strip()
        if value:
            return value
    return ""


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class SearchProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


def http_get_json(url: str, headers: Optional[dict[str, str]] = None, timeout: float = 8.0) -> dict[str, Any]:
    request = Request(url, headers=headers or {})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
    except HTTPError as exc:
        raise SearchProviderError("provider returned HTTP %s" % exc.code, status_code=int(exc.code)) from exc
    except URLError as exc:
        raise SearchProviderError("provider request failed: %s" % exc.reason) from exc
    except OSError as exc:
        raise SearchProviderError("provider request failed") from exc
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise SearchProviderError("provider returned invalid JSON") from exc
    return data if isinstance(data, dict) else {}


class ResearchSearchService:
    """Search across external providers, DigitalOcean catalog/docs, and local RAG."""

    def __init__(
        self,
        env: Optional[Mapping[str, str]] = None,
        clock: Optional[Callable[[], float]] = None,
        http_get: Optional[Callable[[str, Optional[dict[str, str]], float], dict[str, Any]]] = None,
        rag_service_factory: Optional[Callable[[], LocalRagService]] = None,
        showcase_service: Optional[ModelShowcaseService] = None,
        chat_completion: Optional[Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]] = None,
        max_model_price_usd: Optional[float] = None,
    ) -> None:
        self.env = env or os.environ
        self.clock = clock or time.time
        self.http_get = http_get or http_get_json
        self.rag_service_factory = rag_service_factory or default_local_rag_service
        self.showcase_service = showcase_service or ModelShowcaseService()
        self.chat_completion = chat_completion
        self.max_model_price_usd = (
            float(max_model_price_usd)
            if max_model_price_usd is not None
            else _safe_float(self.env.get("MATTS_RESEARCH_MAX_MODEL_PRICE_USD"), DEFAULT_RESEARCH_MODEL_PRICE_LIMIT)
        )
        self.fast_max_latency_ms = _safe_int(self.env.get("MATTS_RESEARCH_FAST_MAX_LATENCY_MS"), DEFAULT_RESEARCH_FAST_MAX_LATENCY_MS, 250, 30000)
        self.llm_timeout_seconds = _safe_int(self.env.get("MATTS_RESEARCH_LLM_TIMEOUT_SECONDS"), DEFAULT_RESEARCH_LLM_TIMEOUT_SECONDS, 2, 120)
        self.llm_enabled = str(self.env.get("MATTS_RESEARCH_LLM_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}

    def engines(self) -> list[dict[str, Any]]:
        rag_status = self._local_rag_status()
        return [
            self._external_engine("bing", "Bing", "web", BING_KEY_ENV),
            self._external_engine("google", "Google", "web", GOOGLE_KEY_ENV, extra_required=GOOGLE_CX_ENV),
            self._external_engine("brave", "Brave Search", "web", BRAVE_KEY_ENV),
            {
                "id": "images",
                "name": "Image Sources",
                "status": "available",
                "kind": "image",
                "configured": True,
                "requires_credentials": False,
                "detail": "Uses Bing Images when configured, with Wikimedia thumbnail fallback.",
            },
            {
                "id": "examples",
                "name": "Examples",
                "status": "available",
                "kind": "examples",
                "configured": True,
                "requires_credentials": False,
                "detail": "Finds relevant examples from README, docs, and scripts.",
            },
            {
                "id": "mapping",
                "name": "Mapping Services",
                "status": "available",
                "kind": "mapping",
                "configured": True,
                "requires_credentials": False,
                "setup_env": list(MAP_KEY_ENV),
                "detail": "Uses OpenStreetMap/Nominatim by default; map API keys can be added for richer services.",
            },
            {
                "id": "wikipedia",
                "name": "Wikipedia",
                "status": "available",
                "kind": "knowledge",
                "configured": True,
                "requires_credentials": False,
                "detail": "Uses Wikipedia search summaries for encyclopedic context.",
            },
            {
                "id": "technical-docs",
                "name": "Technical Documentation",
                "status": "available",
                "kind": "technical_docs",
                "configured": True,
                "requires_credentials": False,
                "detail": "Searches local project documentation and curated technical references.",
            },
            {
                "id": "digitalocean-docs",
                "name": "DigitalOcean Docs + Catalog",
                "status": "available",
                "kind": "vendor_docs",
                "configured": True,
                "requires_credentials": False,
                "detail": "Uses DigitalOcean inference documentation links and the local model catalog.",
            },
            {
                "id": "local-rag",
                "name": "Local RAG",
                "status": rag_status["status"],
                "kind": "local",
                "configured": rag_status["configured"],
                "requires_credentials": False,
                "detail": rag_status["detail"],
                "collections": rag_status["collections"],
            },
        ]

    def source_classes(self, engines: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
        catalog = {
            str(engine.get("id") or ""): engine
            for engine in (engines if engines is not None else self.engines())
            if isinstance(engine, dict)
        }
        rows = []
        for engine_id in RESEARCH_SOURCE_ENGINE_IDS:
            engine = catalog.get(engine_id, {})
            rows.append({
                "id": engine_id,
                "engine_id": engine_id,
                "label": RESEARCH_SOURCE_ENGINE_LABELS[engine_id],
                "name": engine.get("name") or RESEARCH_SOURCE_ENGINE_LABELS[engine_id].title(),
                "kind": engine.get("kind") or engine_id.replace("-", "_"),
                "status": engine.get("status") or "available",
                "detail": engine.get("detail") or "",
                "configured": bool(engine.get("configured", True)),
                "requires_credentials": bool(engine.get("requires_credentials", False)),
            })
        return rows

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        mode = str(payload.get("mode") or "Balanced")
        limit = _safe_int(payload.get("limit"), MODE_LIMITS.get(mode, 6), 1, 20)
        raw_engines = payload.get("engines")
        explicit_engine_selection = isinstance(raw_engines, list)
        selected = raw_engines if explicit_engine_selection else list(ENGINE_ORDER)
        selected_ids = [str(engine_id) for engine_id in selected if str(engine_id) in ENGINE_ORDER]
        if explicit_engine_selection and not selected_ids:
            raise ValueError("at least one valid research engine is required")
        if not selected_ids:
            selected_ids = list(ENGINE_ORDER)

        engine_descriptors = {engine["id"]: dict(engine) for engine in self.engines()}
        selected_ids = self._ensure_minimum_search_engines(selected_ids, engine_descriptors)
        results: list[dict[str, Any]] = []
        engine_runs: list[dict[str, Any]] = []
        for engine_id in selected_ids:
            started = self.clock()
            try:
                rows = self._search_engine(engine_id, query, limit)
                status = self._engine_result_status(rows, engine_descriptors[engine_id])
            except SearchProviderError as exc:
                rows = [self._error_result(engine_id, query, exc)]
                status = "error"
            except Exception as exc:  # pragma: no cover - defensive boundary around provider adapters.
                rows = [self._error_result(engine_id, query, SearchProviderError("adapter failed"))]
                status = "error"
            for position, row in enumerate(rows, start=1):
                row["position"] = len(results) + 1
                row.setdefault("score", max(1, limit - position + 1))
                results.append(row)
            engine = dict(engine_descriptors[engine_id])
            engine["run_status"] = status
            engine["result_count"] = len(rows)
            engine["latency_ms"] = int(max(0, self.clock() - started) * 1000)
            engine_runs.append(engine)

        model_strategy = self.model_strategy()
        model_outputs = self._model_outputs(query, mode, results, engine_runs, model_strategy)
        legacy_payload = {
            "query": query,
            "mode": mode,
            "generated_at": self.clock(),
            "engines": engine_runs,
            "results": results,
            "model_strategy": model_strategy,
            "model_outputs": model_outputs,
            "synthesis": self._synthesis(query, mode, results, engine_runs, model_outputs),
        }
        return self._research_dossier(
            legacy_payload,
            selected_ids=selected_ids,
            source_selection_mode="custom" if explicit_engine_selection else "all",
        )

    def _research_dossier(self, payload: dict[str, Any], selected_ids: list[str], source_selection_mode: str) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        mode = str(payload.get("mode") or "Balanced")
        generated_at = float(payload.get("generated_at") or self.clock())
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        engines = payload.get("engines") if isinstance(payload.get("engines"), list) else []
        synthesis = payload.get("synthesis") if isinstance(payload.get("synthesis"), dict) else {}
        evidence = self._evidence_records(results)
        evidence_by_id = {row["evidence_id"]: row for row in evidence}
        claims = self._claim_rows(query, synthesis, evidence, engines)
        dossier_id = _stable_id("dossier", query, mode, generated_at, ",".join(selected_ids))
        report_packet = self._report_packet(dossier_id, query, mode, generated_at, evidence, claims, payload)
        model_outputs = payload.get("model_outputs") if isinstance(payload.get("model_outputs"), dict) else {}
        synthesis_answer = synthesis.get("coordinated_answer") or model_outputs.get("answer") or ""
        source_catalog = {
            "engines": self.engines(),
            "source_classes": self.source_classes(),
        }
        model_strategy = payload.get("model_strategy") if isinstance(payload.get("model_strategy"), dict) else {}
        return {
            "schema_version": 2,
            "dossier_id": dossier_id,
            "mode": mode,
            "generated_at": generated_at,
            "query_text": query,
            "query": {
                "text": query,
                "mode": mode,
                "selected_engines": selected_ids,
                "source_selection_mode": source_selection_mode,
                "submitted_at": generated_at,
            },
            "source_catalog": source_catalog,
            "engine_runs": engines,
            "engines": engines,
            "results": results,
            "source_classes": source_catalog["source_classes"],
            "model_strategy": model_strategy,
            "model_outputs": model_outputs,
            "evidence": evidence,
            "claims": claims,
            "synthesis": {
                **synthesis,
                "answer": synthesis_answer,
                "evidence_ids": list(evidence_by_id.keys()),
            },
            "model_audit": {
                "strategy": model_strategy,
                "outputs": model_outputs,
                "diagnostics": {
                    "degraded_engines": synthesis.get("degraded_engines") if isinstance(synthesis.get("degraded_engines"), list) else [],
                    "source_engine_counts": synthesis.get("source_engine_counts") if isinstance(synthesis.get("source_engine_counts"), dict) else {},
                    "source_kind_counts": synthesis.get("source_kind_counts") if isinstance(synthesis.get("source_kind_counts"), dict) else {},
                },
            },
            "report_packet": report_packet,
            "pinned_evidence_ids": [],
        }

    def _evidence_records(self, results: list[Any]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for index, row in enumerate(results, start=1):
            if not isinstance(row, dict):
                continue
            evidence_id = str(row.get("id") or _stable_id(row.get("engine"), row.get("title"), row.get("url"), row.get("snippet")))
            record = dict(row)
            record["id"] = evidence_id
            record["evidence_id"] = evidence_id
            record["position"] = int(record.get("position") or index)
            record["source_type"] = str(record.get("kind") or "web")
            record["relevance_score"] = _safe_float(record.get("score"), 0.0)
            record["source_label"] = str(record.get("source") or record.get("engine_name") or record.get("engine") or "Source")
            record["metadata"] = {
                key: record.get(key)
                for key in ("path", "chunk", "collection_id", "thumbnail_url", "content_url", "coordinates", "published_at")
                if record.get(key) not in (None, "")
            }
            evidence.append(record)
        evidence.sort(key=lambda row: (-_safe_float(row.get("relevance_score"), 0.0), int(row.get("position") or 9999)))
        return evidence

    def _claim_rows(self, query: str, synthesis: dict[str, Any], evidence: list[dict[str, Any]], engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        useful = [row for row in evidence if str(row.get("status") or "") not in {"needs_key", "error", "not_indexed", "no_matches"}]
        degraded = [str(engine.get("id") or "") for engine in engines if isinstance(engine, dict) and engine.get("run_status") in {"needs_key", "error", "degraded"}]
        top_ids = [str(row.get("evidence_id")) for row in useful[:4] if row.get("evidence_id")]
        claims: list[dict[str, Any]] = []
        summary = str(synthesis.get("summary") or "").strip()
        answer = str(synthesis.get("coordinated_answer") or synthesis.get("answer") or "").strip()
        if answer:
            claims.append({
                "claim_id": _stable_id("claim", query, "answer", answer),
                "text": answer[:900],
                "confidence": "medium" if top_ids else "low",
                "status": "supported" if top_ids else "needs_evidence",
                "supporting_evidence_ids": top_ids[:3],
                "caveat": "Review linked evidence before relying on this synthesized answer.",
            })
        if summary:
            claims.append({
                "claim_id": _stable_id("claim", query, "summary", summary),
                "text": summary[:900],
                "confidence": "medium" if top_ids else "low",
                "status": "supported" if top_ids else "needs_evidence",
                "supporting_evidence_ids": top_ids,
                "caveat": "Coverage reflects selected source classes and configured providers.",
            })
        if useful:
            claims.append({
                "claim_id": _stable_id("claim", query, "evidence", ",".join(top_ids[:4])),
                "text": "%s usable evidence record(s) support the current technical research result." % len(useful),
                "confidence": "medium",
                "status": "supported",
                "supporting_evidence_ids": top_ids[:5],
                "caveat": "Evidence relevance is score-sorted and should be inspected row by row.",
            })
        if degraded:
            claims.append({
                "claim_id": _stable_id("claim", query, "degraded", ",".join(degraded)),
                "text": "Some selected sources were degraded or need configuration: %s." % ", ".join(degraded),
                "confidence": "high",
                "status": "limited_coverage",
                "supporting_evidence_ids": [],
                "caveat": "Configure degraded engines or rerun with alternate sources for broader coverage.",
            })
        if not claims:
            claims.append({
                "claim_id": _stable_id("claim", query, "empty"),
                "text": "No supported technical research claim could be generated for this query.",
                "confidence": "low",
                "status": "needs_evidence",
                "supporting_evidence_ids": [],
                "caveat": "Broaden the query or enable additional sources.",
            })
        return claims

    def _report_packet(
        self,
        dossier_id: str,
        query: str,
        mode: str,
        generated_at: float,
        evidence: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        synthesis = payload.get("synthesis") if isinstance(payload.get("synthesis"), dict) else {}
        source_coverage = synthesis.get("source_coverage") if isinstance(synthesis.get("source_coverage"), list) else []
        model_outputs = payload.get("model_outputs") if isinstance(payload.get("model_outputs"), dict) else {}
        sections = [
            {
                "id": "request",
                "title": "Research Request",
                "kind": "metadata",
                "content": "Query: %s\nMode: %s\nDossier: %s" % (query, mode, dossier_id),
            },
            {
                "id": "answer",
                "title": "Synthesis Answer",
                "kind": "synthesis",
                "content": str(synthesis.get("coordinated_answer") or model_outputs.get("answer") or synthesis.get("summary") or "No synthesis answer available."),
            },
            {
                "id": "claims",
                "title": "Claim Evidence Map",
                "kind": "claims",
                "items": claims,
            },
            {
                "id": "pinned-evidence",
                "title": "Pinned Evidence",
                "kind": "pinned_evidence",
                "items": [],
            },
            {
                "id": "all-evidence",
                "title": "All Evidence Records",
                "kind": "evidence",
                "items": evidence,
            },
            {
                "id": "source-coverage",
                "title": "Source Coverage",
                "kind": "source_coverage",
                "items": source_coverage,
            },
            {
                "id": "model-audit",
                "title": "Model Audit",
                "kind": "model_audit",
                "content": json.dumps({
                    "strategy": payload.get("model_strategy") if isinstance(payload.get("model_strategy"), dict) else {},
                    "outputs": model_outputs,
                }, indent=2, sort_keys=True),
            },
        ]
        return {
            "dossier_id": dossier_id,
            "title": "%s Research Packet" % (mode or "Technical"),
            "generated_at": generated_at,
            "sections": sections,
            "pinned_evidence_ids": [],
        }

    def _ensure_minimum_search_engines(self, selected_ids: list[str], engine_descriptors: dict[str, dict[str, Any]]) -> list[str]:
        """Keep every Research run augmented by at least two web search engines."""

        selected = list(dict.fromkeys(selected_ids))
        web_selected = [engine_id for engine_id in selected if engine_descriptors.get(engine_id, {}).get("kind") == "web"]
        if len(web_selected) >= 2:
            return selected
        web_candidates = [
            engine_id for engine_id in ENGINE_ORDER
            if engine_descriptors.get(engine_id, {}).get("kind") == "web" and engine_id not in selected
        ]
        web_candidates.sort(key=lambda engine_id: (
            engine_descriptors.get(engine_id, {}).get("configured") is not True,
            ENGINE_ORDER.index(engine_id),
        ))
        for engine_id in web_candidates:
            selected.append(engine_id)
            web_selected.append(engine_id)
            if len(web_selected) >= 2:
                break
        return selected

    def model_strategy(self) -> dict[str, Any]:
        """Recommend a low-cost analyst team from the current model registry."""

        candidates = self._low_cost_text_models()
        used: set[str] = set()
        analysts = [self._select_role_model(spec, candidates, used) for spec in RESEARCH_ROLE_SPECS]
        coordinator = self._select_role_model(COORDINATOR_SPEC, candidates, used)
        return {
            "policy": {
                "max_model_price_usd": self.max_model_price_usd,
                "price_metric": "max(input, output) USD per 1M tokens",
                "comparison": "strictly_less_than",
                "fast_max_latency_ms": self.fast_max_latency_ms,
                "fast_response_required": True,
                "llm_timeout_seconds": self.llm_timeout_seconds,
                "llm_calls_enabled": bool(self.llm_enabled and self.chat_completion),
            },
            "candidate_count": len(candidates),
            "analysts": analysts,
            "coordinator": coordinator,
        }

    def _low_cost_text_models(self) -> list[dict[str, Any]]:
        try:
            cards = self.showcase_service.payload().get("models") or []
        except Exception:
            cards = []
        candidates: list[dict[str, Any]] = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            if str(card.get("type") or "") != "text" or not card.get("route_enabled"):
                continue
            max_price = self._max_text_price(card)
            if max_price <= 0 or max_price >= self.max_model_price_usd:
                continue
            fast_profile = self._fast_response_profile(card)
            if not fast_profile["eligible"]:
                continue
            row = dict(card)
            row["max_text_price_usd"] = max_price
            row["fast_response"] = fast_profile
            candidates.append(row)
        candidates.sort(key=lambda row: (float(row.get("max_text_price_usd") or 99), -int(row.get("context_window") or 0), str(row.get("display_name") or "")))
        return candidates

    def _max_text_price(self, model: dict[str, Any]) -> float:
        pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
        prices = [_safe_float(pricing.get(key), 0.0) for key in ("input", "output")]
        return max([price for price in prices if price > 0] or [0.0])

    def _fast_response_profile(self, model: dict[str, Any]) -> dict[str, Any]:
        latency = 0
        for key in ("p95_latency_ms", "median_latency_ms", "avg_latency_ms", "latency_ms"):
            value = _safe_int(model.get(key), 0, 0, 120000)
            if value:
                latency = value
                break
        if latency:
            return {
                "eligible": latency <= self.fast_max_latency_ms,
                "basis": "measured_latency",
                "latency_ms": latency,
                "detail": "Measured latency %sms with ceiling %sms." % (latency, self.fast_max_latency_ms),
            }
        haystack = " ".join(str(model.get(key) or "").lower() for key in ("id", "display_name", "company", "family"))
        matched = next((hint for hint in FAST_RESPONSE_FAMILY_HINTS if hint in haystack), "")
        return {
            "eligible": bool(matched),
            "basis": "fast_family_history" if matched else "missing_latency_history",
            "latency_ms": 0,
            "detail": "Selected by fast-response family history: %s." % matched if matched else "No measured latency or fast-response family history found.",
        }

    def _select_role_model(self, spec: dict[str, Any], candidates: list[dict[str, Any]], used: set[str]) -> dict[str, Any]:
        available = [model for model in candidates if str(model.get("id") or "") not in used]
        nation = str(spec.get("nation") or "")
        if nation:
            nation_matches = [model for model in available if str(model.get("training_nation") or "") == nation]
            if nation_matches:
                available = nation_matches
        if not available:
            return {
                "role": spec["role"],
                "label": spec["label"],
                "focus": spec["focus"],
                "status": "unavailable",
                "recommendation": "No route-enabled text model is below the configured research cost ceiling.",
            }
        preferred = [str(item).lower() for item in spec.get("preferred", ())]

        def rank(model: dict[str, Any]) -> tuple[int, float, int, str]:
            haystack = " ".join(str(model.get(key) or "").lower() for key in ("id", "display_name", "company", "family"))
            preferred_index = next((index for index, needle in enumerate(preferred) if needle and needle in haystack), len(preferred))
            return (
                preferred_index,
                float(model.get("max_text_price_usd") or 99),
                -int(model.get("context_window") or 0),
                str(model.get("display_name") or ""),
            )

        selected = sorted(available, key=rank)[0]
        model_id = str(selected.get("id") or "")
        if model_id:
            used.add(model_id)
        return {
            "role": spec["role"],
            "label": spec["label"],
            "focus": spec["focus"],
            "status": "selected",
            "model_id": model_id,
            "display_name": selected.get("display_name") or model_id,
            "company": selected.get("company") or "",
            "family": selected.get("family") or "",
            "training_nation": selected.get("training_nation") or "",
            "cost_label": selected.get("cost_label") or "",
            "max_text_price_usd": selected.get("max_text_price_usd") or 0,
            "fast_response": selected.get("fast_response") if isinstance(selected.get("fast_response"), dict) else {},
            "context_window": selected.get("context_window") or 0,
            "recommendation": "%s is below the $%.2f ceiling and fits the %s role." % (
                selected.get("display_name") or model_id,
                self.max_model_price_usd,
                spec["label"],
            ),
        }

    def _external_engine(
        self,
        engine_id: str,
        name: str,
        kind: str,
        key_env: tuple[str, ...],
        extra_required: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        missing = [names[0] for names in (key_env, extra_required) if names and not _first_env(self.env, names)]
        configured = not missing
        return {
            "id": engine_id,
            "name": name,
            "status": "ready" if configured else "needs_key",
            "kind": kind,
            "configured": configured,
            "requires_credentials": True,
            "setup_env": list(key_env + extra_required),
            "detail": "Ready for live search." if configured else "Set %s to enable live search." % ", ".join(missing),
        }

    def _local_rag_status(self) -> dict[str, Any]:
        try:
            payload = self.rag_service_factory().payload()
        except Exception:
            return {"status": "unavailable", "configured": False, "detail": "Local RAG is unavailable.", "collections": []}
        collections = payload.get("index") if isinstance(payload.get("index"), list) else []
        documents = sum(int(item.get("documents") or 0) for item in collections if isinstance(item, dict))
        return {
            "status": "indexed" if documents else "not_indexed",
            "configured": bool(documents),
            "detail": "%s indexed chunks available." % documents if documents else "Index local documents from Advanced > run > Local RAG.",
            "collections": collections,
        }

    def _search_engine(self, engine_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        if engine_id == "bing":
            return self._search_bing(query, limit)
        if engine_id == "google":
            return self._search_google(query, limit)
        if engine_id == "brave":
            return self._search_brave(query, limit)
        if engine_id == "images":
            return self._search_images(query, limit)
        if engine_id == "examples":
            return self._search_examples(query, limit)
        if engine_id == "mapping":
            return self._search_mapping(query, limit)
        if engine_id == "wikipedia":
            return self._search_wikipedia(query, limit)
        if engine_id == "technical-docs":
            return self._search_technical_docs(query, limit)
        if engine_id == "digitalocean-docs":
            return self._search_digitalocean(query, limit)
        if engine_id == "local-rag":
            return self._search_local_rag(query, limit)
        return []

    def _search_bing(self, query: str, limit: int) -> list[dict[str, Any]]:
        key = _first_env(self.env, BING_KEY_ENV)
        if not key:
            return [self._setup_result("bing", "Bing", query, BING_KEY_ENV)]
        endpoint = str(self.env.get("BING_SEARCH_ENDPOINT") or "https://api.bing.microsoft.com/v7.0/search")
        url = endpoint + "?" + urlencode({"q": query, "count": min(limit, 10), "responseFilter": "Webpages", "safeSearch": "Moderate", "textDecorations": "false"})
        data = self.http_get(url, {"Ocp-Apim-Subscription-Key": key, "accept": "application/json"}, float(self.env.get("MATTS_RESEARCH_SEARCH_TIMEOUT", "8")))
        values = ((data.get("webPages") or {}).get("value") or []) if isinstance(data, dict) else []
        return [
            self._result("bing", "Bing", item.get("name"), item.get("url"), item.get("snippet"), "Bing Web Search", "live", item.get("dateLastCrawled"))
            for item in values[:limit]
            if isinstance(item, dict)
        ]

    def _search_google(self, query: str, limit: int) -> list[dict[str, Any]]:
        key = _first_env(self.env, GOOGLE_KEY_ENV)
        cx = _first_env(self.env, GOOGLE_CX_ENV)
        if not key or not cx:
            return [self._setup_result("google", "Google", query, GOOGLE_KEY_ENV + GOOGLE_CX_ENV)]
        endpoint = str(self.env.get("GOOGLE_SEARCH_ENDPOINT") or "https://www.googleapis.com/customsearch/v1")
        url = endpoint + "?" + urlencode({"q": query, "num": min(limit, 10), "key": key, "cx": cx})
        data = self.http_get(url, {"accept": "application/json"}, float(self.env.get("MATTS_RESEARCH_SEARCH_TIMEOUT", "8")))
        values = data.get("items") if isinstance(data.get("items"), list) else []
        return [
            self._result("google", "Google", item.get("title"), item.get("link"), item.get("snippet"), "Google Programmable Search", "live", "")
            for item in values[:limit]
            if isinstance(item, dict)
        ]

    def _search_brave(self, query: str, limit: int) -> list[dict[str, Any]]:
        key = _first_env(self.env, BRAVE_KEY_ENV)
        if not key:
            return [self._setup_result("brave", "Brave Search", query, BRAVE_KEY_ENV)]
        endpoint = str(self.env.get("BRAVE_SEARCH_ENDPOINT") or "https://api.search.brave.com/res/v1/web/search")
        url = endpoint + "?" + urlencode({"q": query, "count": min(limit, 10), "safesearch": "moderate"})
        data = self.http_get(url, {"X-Subscription-Token": key, "accept": "application/json"}, float(self.env.get("MATTS_RESEARCH_SEARCH_TIMEOUT", "8")))
        web = data.get("web") if isinstance(data.get("web"), dict) else {}
        values = web.get("results") if isinstance(web.get("results"), list) else []
        return [
            self._result("brave", "Brave Search", item.get("title"), item.get("url"), item.get("description"), "Brave Search", "live", item.get("age"))
            for item in values[:limit]
            if isinstance(item, dict)
        ]

    def _search_images(self, query: str, limit: int) -> list[dict[str, Any]]:
        key = _first_env(self.env, BING_KEY_ENV)
        if key:
            endpoint = str(self.env.get("BING_IMAGE_SEARCH_ENDPOINT") or "https://api.bing.microsoft.com/v7.0/images/search")
            url = endpoint + "?" + urlencode({"q": query, "count": min(limit, 10), "safeSearch": "Moderate"})
            data = self.http_get(url, {"Ocp-Apim-Subscription-Key": key, "accept": "application/json"}, float(self.env.get("MATTS_RESEARCH_IMAGE_TIMEOUT", "4")))
            values = data.get("value") if isinstance(data.get("value"), list) else []
            rows = [
                self._result(
                    "images",
                    "Image Sources",
                    item.get("name"),
                    item.get("contentUrl") or item.get("hostPageUrl"),
                    "Image result from %s. Thumbnail: %s" % (item.get("hostPageDisplayUrl") or "Bing Images", item.get("thumbnailUrl") or "n/a"),
                    item.get("hostPageDisplayUrl") or "Bing Images",
                    "live",
                    item.get("datePublished") or "",
                    kind="image",
                    extra={"thumbnail_url": item.get("thumbnailUrl") or "", "content_url": item.get("contentUrl") or ""},
                )
                for item in values[:limit]
                if isinstance(item, dict)
            ]
            if rows:
                return rows
        return self._search_wikimedia_images(query, limit)

    def _search_wikimedia_images(self, query: str, limit: int) -> list[dict[str, Any]]:
        url = "https://en.wikipedia.org/w/api.php?" + urlencode({
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": min(limit, 8),
            "prop": "pageimages|info",
            "piprop": "thumbnail|original",
            "pithumbsize": 640,
            "inprop": "url",
            "format": "json",
            "origin": "*",
        })
        data = self.http_get(url, {"accept": "application/json", "User-Agent": "MDE-LLM-PROXY-Research/1.0"}, float(self.env.get("MATTS_RESEARCH_WIKI_TIMEOUT", "4")))
        pages = ((data.get("query") or {}).get("pages") or {}) if isinstance(data, dict) else {}
        rows = []
        for page in pages.values() if isinstance(pages, dict) else []:
            if not isinstance(page, dict):
                continue
            thumb = page.get("thumbnail") if isinstance(page.get("thumbnail"), dict) else {}
            original = page.get("original") if isinstance(page.get("original"), dict) else {}
            image_url = thumb.get("source") or original.get("source") or ""
            if not image_url:
                continue
            rows.append(self._result(
                "images",
                "Image Sources",
                page.get("title"),
                page.get("fullurl") or image_url,
                "Wikimedia image context for %s. Thumbnail: %s" % (query, image_url),
                "Wikimedia",
                "live",
                "",
                kind="image",
                extra={"thumbnail_url": image_url, "content_url": image_url},
            ))
        if rows:
            return rows[:limit]
        return [self._result("images", "Image Sources", "No image results found", "", "No Bing or Wikimedia image results were available for this query.", "Image Sources", "no_matches", "", kind="image")]

    def _search_mapping(self, query: str, limit: int) -> list[dict[str, Any]]:
        url = "https://nominatim.openstreetmap.org/search?" + urlencode({
            "q": query,
            "format": "geocodejson",
            "limit": min(limit, 5),
            "addressdetails": 1,
        })
        data = self.http_get(url, {"accept": "application/json", "User-Agent": "MDE-LLM-PROXY-Research/1.0"}, float(self.env.get("MATTS_RESEARCH_MAP_TIMEOUT", "4")))
        features = data.get("features") if isinstance(data.get("features"), list) else []
        rows = []
        for item in features[:limit]:
            if not isinstance(item, dict):
                continue
            properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}
            coords = geometry.get("coordinates") if isinstance(geometry.get("coordinates"), list) else []
            latlon = ""
            if len(coords) >= 2:
                latlon = "%.5f, %.5f" % (_safe_float(coords[1]), _safe_float(coords[0]))
            label = properties.get("geocoding", {}) if isinstance(properties.get("geocoding"), dict) else {}
            title = label.get("label") or properties.get("label") or query
            rows.append(self._result(
                "mapping",
                "Mapping Services",
                title,
                "https://www.openstreetmap.org/search?query=" + urlencode({"q": str(title)})[2:],
                "Map/geographic context%s for %s." % ((" at " + latlon) if latlon else "", query),
                "OpenStreetMap Nominatim",
                "live",
                "",
                kind="mapping",
                extra={"coordinates": latlon},
            ))
        if rows:
            return rows
        return [self._result("mapping", "Mapping Services", "No map context found", "", "Mapping services did not find a geographic match for this query.", "OpenStreetMap Nominatim", "no_matches", "", kind="mapping")]

    def _search_wikipedia(self, query: str, limit: int) -> list[dict[str, Any]]:
        url = "https://en.wikipedia.org/w/api.php?" + urlencode({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": min(limit, 8),
            "format": "json",
            "origin": "*",
        })
        data = self.http_get(url, {"accept": "application/json", "User-Agent": "MDE-LLM-PROXY-Research/1.0"}, float(self.env.get("MATTS_RESEARCH_WIKI_TIMEOUT", "4")))
        values = ((data.get("query") or {}).get("search") or []) if isinstance(data, dict) else []
        rows = []
        for item in values[:limit]:
            if not isinstance(item, dict):
                continue
            page_id = str(item.get("pageid") or "")
            rows.append(self._result(
                "wikipedia",
                "Wikipedia",
                item.get("title"),
                "https://en.wikipedia.org/?curid=%s" % page_id if page_id else "",
                re.sub(r"<[^>]+>", "", str(item.get("snippet") or "")),
                "Wikipedia",
                "live",
                item.get("timestamp") or "",
                kind="knowledge",
            ))
        if rows:
            return rows
        return [self._result("wikipedia", "Wikipedia", "No Wikipedia matches", "", "Wikipedia did not return an article match for this query.", "Wikipedia", "no_matches", "", kind="knowledge")]

    def _search_examples(self, query: str, limit: int) -> list[dict[str, Any]]:
        return self._search_project_text(
            query,
            limit,
            engine="examples",
            engine_name="Examples",
            kind="examples",
            source="Project Examples",
            roots=("README.md", "docs", "scripts"),
            title_prefix="Example",
            prefer_examples=True,
        )

    def _search_technical_docs(self, query: str, limit: int) -> list[dict[str, Any]]:
        rows = self._search_project_text(
            query,
            limit,
            engine="technical-docs",
            engine_name="Technical Documentation",
            kind="technical_docs",
            source="Project Docs",
            roots=("README.md", "docs", "backend", "frontend/src/api"),
            title_prefix="Technical doc",
            prefer_examples=False,
        )
        if rows:
            return rows
        return [self._result(
            "technical-docs",
            "Technical Documentation",
            "Technical documentation index",
            "",
            "No local technical documentation matched this query. Add docs or index Local RAG for deeper repository evidence.",
            "Project Docs",
            "no_matches",
            "",
            kind="technical_docs",
        )]

    def _search_project_text(
        self,
        query: str,
        limit: int,
        engine: str,
        engine_name: str,
        kind: str,
        source: str,
        roots: tuple[str, ...],
        title_prefix: str,
        prefer_examples: bool,
    ) -> list[dict[str, Any]]:
        terms = set(_terms(query))
        rows: list[dict[str, Any]] = []
        paths: list[Path] = []
        for root in roots:
            path = PROJECT_DIR / root
            if path.is_file():
                paths.append(path)
            elif path.is_dir():
                paths.extend(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {".md", ".txt", ".py", ".ts", ".tsx", ".json", ".sh"})
        for path in sorted(paths)[:250]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lower = text.lower()
            if terms and not any(term in lower for term in terms):
                continue
            if prefer_examples and not re.search(r"(```|curl |python3? |npm |example|usage|sample)", text, re.I):
                continue
            snippet = self._snippet_for_terms(text, terms)
            rel = str(path.relative_to(PROJECT_DIR))
            rows.append(self._result(
                engine,
                engine_name,
                "%s: %s" % (title_prefix, rel),
                "",
                snippet,
                source,
                "local",
                "",
                kind=kind,
                score=10 if terms else 1,
                extra={"path": rel},
            ))
            if len(rows) >= limit:
                break
        if rows:
            return rows
        status = "no_matches"
        return [self._result(engine, engine_name, "No %s found" % engine_name.lower(), "", "%s did not match local repository content for this query." % engine_name, source, status, "", kind=kind)]

    def _snippet_for_terms(self, text: str, terms: set[str], size: int = 360) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if not compact:
            return ""
        index = 0
        for term in terms:
            found = compact.lower().find(term)
            if found >= 0:
                index = max(0, found - size // 3)
                break
        return compact[index:index + size]

    def _search_digitalocean(self, query: str, limit: int) -> list[dict[str, Any]]:
        terms = set(_terms(query))
        catalog_query = bool(terms & {"model", "models", "llm", "catalog", "inference", "serverless"})
        model_results: list[dict[str, Any]] = []
        link_results: list[dict[str, Any]] = []
        link_keywords = {
            "Serverless Inference": {"serverless", "inference", "llm", "model", "api"},
            "Available Inference Models": {"model", "models", "llm", "catalog", "deepseek", "llama", "qwen", "mistral"},
            "Dedicated Inference": {"dedicated", "gpu", "capacity", "endpoint", "inference"},
            "Serverless Inference API": {"api", "sdk", "curl", "openai", "serverless", "inference"},
            "DigitalOcean Status": {"status", "outage", "incident", "availability", "health"},
        }
        try:
            models = self.showcase_service.payload().get("models") or []
        except Exception:
            models = []
        for model in models:
            if not isinstance(model, dict):
                continue
            haystack = " ".join(str(model.get(key) or "") for key in ("id", "display_name", "company", "family", "training_nation", "type", "use_case")).lower()
            if terms and not catalog_query and not any(term in haystack for term in terms):
                continue
            route = "routable" if model.get("route_enabled") else "visible but disabled"
            snippet = "%s %s model by %s (%s). Access: %s; context: %s; best for: %s." % (
                model.get("training_nation") or "Unknown",
                model.get("type") or "unknown",
                model.get("company") or "DigitalOcean",
                model.get("family") or "General",
                route,
                model.get("context_window") or "unknown",
                model.get("use_case") or "general LLM work",
            )
            model_results.append(self._result(
                "digitalocean-docs",
                "DigitalOcean Docs + Catalog",
                "DigitalOcean model: %s" % (model.get("display_name") or model.get("id")),
                "https://docs.digitalocean.com/products/inference/details/models/",
                snippet,
                "DigitalOcean Model Catalog",
                "catalog",
                "",
                kind="model_catalog",
                score=15 if model.get("route_enabled") else 8,
            ))
            if len(model_results) >= limit:
                break
        for link in DIGITALOCEAN_LLM_LINKS:
            label = str(link.get("label") or "")
            keywords = link_keywords.get(label, {"digitalocean", "inference", "llm"})
            if not terms or terms & keywords or "digitalocean" in terms:
                link_results.append(self._result(
                    "digitalocean-docs",
                    "DigitalOcean Docs + Catalog",
                    label,
                    link.get("url"),
                    "DigitalOcean %s reference for LLM and inference platform research." % link.get("category", "docs"),
                    "DigitalOcean Docs",
                    "catalog",
                    "",
                    kind="vendor_docs",
                ))
        if terms & {"model", "models", "llm", "catalog"}:
            link_results.sort(key=lambda row: 0 if row.get("title") == "Available Inference Models" else 1)
        if model_results and link_results:
            link_slots = min(2, max(1, limit // 3))
            model_slots = max(1, limit - link_slots)
            results = model_results[:model_slots] + link_results[:link_slots]
        else:
            results = model_results + link_results
        if not results:
            results.append(self._result(
                "digitalocean-docs",
                "DigitalOcean Docs + Catalog",
                "DigitalOcean inference documentation",
                "https://docs.digitalocean.com/products/inference/",
                "No exact catalog hit was found; start from the DigitalOcean Inference documentation.",
                "DigitalOcean Docs",
                "catalog",
                "",
                kind="vendor_docs",
            ))
        return results[:limit]

    def _search_local_rag(self, query: str, limit: int) -> list[dict[str, Any]]:
        rag = self.rag_service_factory()
        result = rag.search({"query": query, "limit": min(limit, 12)})
        matches = result.get("matches") if isinstance(result.get("matches"), list) else []
        if not matches:
            collections = result.get("collections") if isinstance(result.get("collections"), list) else []
            title = "No Local RAG matches" if collections else "Local RAG index not built"
            snippet = "No indexed local documents matched this query." if collections else "Index local docs from Advanced > run > Local RAG to add repository evidence."
            return [self._result("local-rag", "Local RAG", title, "", snippet, "Local RAG", "not_indexed" if not collections else "no_matches", "", kind="local")]
        rows = []
        for match in matches[:limit]:
            title = "%s#%s" % (match.get("path") or "local document", match.get("chunk") or "")
            rows.append(self._result(
                "local-rag",
                "Local RAG",
                title,
                "",
                match.get("text"),
                match.get("collection_name") or "Local RAG",
                "local",
                "",
                kind="local",
                score=int(match.get("score") or 1),
                extra={"path": match.get("path"), "chunk": match.get("chunk"), "collection_id": match.get("collection_id")},
            ))
        return rows

    def _result(
        self,
        engine: str,
        engine_name: str,
        title: Any,
        url: Any,
        snippet: Any,
        source: Any,
        status: str,
        published_at: Any,
        kind: str = "web",
        score: int = 1,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        title_text = str(title or "Untitled result").strip()
        url_text = str(url or "").strip()
        snippet_text = str(snippet or "").strip()
        row = {
            "id": _stable_id(engine, title_text, url_text, snippet_text),
            "engine": engine,
            "engine_name": engine_name,
            "title": title_text,
            "url": url_text,
            "snippet": snippet_text[:1200],
            "published_at": str(published_at or ""),
            "source": str(source or engine_name),
            "status": status,
            "kind": kind,
            "score": score,
            "citation": "[%s:%s]" % (engine, _stable_id(title_text, url_text)[:8]),
        }
        if extra:
            row.update(extra)
        return row

    def _setup_result(self, engine: str, engine_name: str, query: str, env_names: tuple[str, ...]) -> dict[str, Any]:
        return self._result(
            engine,
            engine_name,
            "%s setup required for %s" % (engine_name, query),
            "",
            "Live %s results are disabled until the operator configures %s. The Research UI will keep working with DigitalOcean catalog and Local RAG evidence." % (engine_name, " / ".join(env_names)),
            engine_name,
            "needs_key",
            "",
            kind="setup",
        )

    def _error_result(self, engine: str, query: str, error: SearchProviderError) -> dict[str, Any]:
        names = {item["id"]: item["name"] for item in self.engines()}
        status = "HTTP %s" % error.status_code if error.status_code else "request failed"
        return self._result(
            engine,
            names.get(engine, engine),
            "%s search unavailable for %s" % (names.get(engine, engine), query),
            "",
            "The provider adapter returned %s. Credentials and query details were not logged in the result payload." % status,
            names.get(engine, engine),
            "error",
            "",
            kind="error",
        )

    def _engine_result_status(self, rows: list[dict[str, Any]], engine: dict[str, Any]) -> str:
        if not rows:
            return "empty"
        statuses = {str(row.get("status") or "") for row in rows}
        if "error" in statuses:
            return "error"
        if "needs_key" in statuses:
            return "needs_key"
        if statuses <= {"not_indexed", "no_matches"}:
            return "degraded"
        if engine.get("configured") is False:
            return "degraded"
        return "ok"

    def _source_counts(self, results: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in results:
            value = str(row.get(key) or "").strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
        return dict(sorted(counts.items()))

    def _source_coverage(self, results: list[dict[str, Any]], engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Report required Research source classes even when a custom run omits them."""

        engine_runs = {str(engine.get("id") or ""): engine for engine in engines if isinstance(engine, dict)}
        rows_by_engine: dict[str, list[dict[str, Any]]] = {}
        unusable_statuses = {"needs_key", "error", "not_indexed", "no_matches"}
        for row in results:
            engine_id = str(row.get("engine") or "")
            if engine_id:
                rows_by_engine.setdefault(engine_id, []).append(row)

        coverage: list[dict[str, Any]] = []
        catalog = {engine["id"]: dict(engine) for engine in self.engines()}
        for engine_id, label in RESEARCH_SOURCE_ENGINE_LABELS.items():
            run = engine_runs.get(engine_id)
            engine = run or catalog.get(engine_id, {})
            rows = rows_by_engine.get(engine_id, [])
            usable_count = len([row for row in rows if str(row.get("status") or "") not in unusable_statuses])
            if not run:
                status = "not_selected"
                detail = "%s was not selected for this Research run." % label
            elif usable_count:
                status = "covered"
                detail = "%s contributed usable evidence." % label
            elif rows:
                row_statuses = {str(row.get("status") or "") for row in rows}
                if row_statuses <= {"no_matches"}:
                    status = "no_matches"
                    detail = "%s was queried but did not return a match." % label
                else:
                    status = "degraded"
                    detail = "%s was queried but returned only setup, degraded, or unavailable evidence." % label
            else:
                run_status = str(run.get("run_status") or run.get("status") or "empty")
                status = "degraded" if run_status in {"needs_key", "error", "degraded", "not_indexed"} else run_status
                detail = "%s was selected but did not return evidence cards." % label
            coverage.append({
                "id": engine_id,
                "engine_id": engine_id,
                "label": label,
                "name": engine.get("name") or label.title(),
                "kind": engine.get("kind") or engine_id.replace("-", "_"),
                "required": True,
                "status": status,
                "result_count": len(rows),
                "usable_count": usable_count,
                "detail": detail,
            })
        return coverage

    def _model_outputs(
        self,
        query: str,
        mode: str,
        results: list[dict[str, Any]],
        engines: list[dict[str, Any]],
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = self._evidence_digest(results)
        analysts = [
            self._run_model_role(role, query, mode, evidence, results, max_tokens=320)
            for role in strategy.get("analysts", [])
            if isinstance(role, dict)
        ]
        coordinator_role = strategy.get("coordinator") if isinstance(strategy.get("coordinator"), dict) else {}
        coordinator = self._run_coordinator_role(coordinator_role, query, mode, evidence, results, engines, analysts)
        return {
            "analysts": analysts,
            "coordinator": coordinator,
            "answer": coordinator.get("text") or self._coordinator_fallback(query, results, engines, analysts),
            "generated_at": self.clock(),
        }

    def _evidence_digest(self, results: list[dict[str, Any]], limit: int = 8) -> str:
        useful = [row for row in results if row.get("status") not in {"needs_key", "error", "not_indexed", "no_matches"}]
        rows = useful[:limit] or results[:limit]
        lines = []
        for index, row in enumerate(rows, start=1):
            lines.append("%s. %s [%s] %s" % (
                index,
                row.get("title") or "Untitled evidence",
                row.get("citation") or row.get("engine_name") or "source",
                row.get("snippet") or "",
            ))
        return "\n".join(lines) if lines else "No evidence cards are available yet."

    def _run_model_role(
        self,
        role: dict[str, Any],
        query: str,
        mode: str,
        evidence: str,
        results: list[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        base = self._answer_base(role)
        model_id = str(role.get("model_id") or "")
        if not model_id:
            return {**base, "status": "unavailable", "text": self._role_fallback(role, query, results, "No low-cost model is available for this role.")}
        if not self.llm_enabled or not self.chat_completion:
            return {**base, "status": "fallback", "text": self._role_fallback(role, query, results, "Live LLM calls are disabled or unavailable.")}
        prompt = (
            "Research query: %s\n"
            "Mode: %s\n"
            "Your role: %s\n"
            "Focus: %s\n\n"
            "Evidence cards:\n%s\n\n"
            "Return a concise analyst answer with 3 bullets: conclusion, evidence, caveat. Cite evidence labels when useful."
        ) % (query, mode, role.get("label") or role.get("role"), role.get("focus") or "Research analysis", evidence)
        status, payload = self._call_llm(model_id, prompt, max_tokens=max_tokens)
        if status == "ok":
            return {**base, "status": "ok", "text": payload}
        return {**base, "status": "fallback", "text": self._role_fallback(role, query, results, payload)}

    def _run_coordinator_role(
        self,
        role: dict[str, Any],
        query: str,
        mode: str,
        evidence: str,
        results: list[dict[str, Any]],
        engines: list[dict[str, Any]],
        analysts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        base = self._answer_base(role)
        model_id = str(role.get("model_id") or "")
        analyst_text = "\n\n".join("%s (%s): %s" % (
            analyst.get("label") or analyst.get("role"),
            analyst.get("model_id") or "fallback",
            analyst.get("text") or "",
        ) for analyst in analysts)
        if not model_id:
            return {**base, "status": "unavailable", "text": self._coordinator_fallback(query, results, engines, analysts)}
        if not self.llm_enabled or not self.chat_completion:
            return {**base, "status": "fallback", "text": self._coordinator_fallback(query, results, engines, analysts)}
        prompt = (
            "Coordinate one final research answer.\n"
            "Query: %s\n"
            "Mode: %s\n\n"
            "Search evidence:\n%s\n\n"
            "Analyst outputs:\n%s\n\n"
            "Write one direct answer. Include: answer, why, caveats, and 3 source citations. Avoid saying you used unavailable sources."
        ) % (query, mode, evidence, analyst_text or "No analyst outputs.")
        status, payload = self._call_llm(model_id, prompt, max_tokens=520)
        if status == "ok":
            return {**base, "status": "ok", "text": payload}
        return {**base, "status": "fallback", "text": self._coordinator_fallback(query, results, engines, analysts)}

    def _answer_base(self, role: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": role.get("role") or "",
            "label": role.get("label") or "",
            "focus": role.get("focus") or "",
            "model_id": role.get("model_id") or "",
            "display_name": role.get("display_name") or role.get("model_id") or "",
            "company": role.get("company") or "",
            "training_nation": role.get("training_nation") or "",
            "cost_label": role.get("cost_label") or "",
            "max_text_price_usd": role.get("max_text_price_usd") or 0,
        }

    def _call_llm(self, model_id: str, prompt: str, max_tokens: int) -> tuple[str, str]:
        try:
            status, payload = self.chat_completion({  # type: ignore[misc]
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1,
                "request_timeout_seconds": self.llm_timeout_seconds,
                "trace_status_on_error": "fallback",
                "trace_origin": "research_llm",
            })
        except Exception as exc:
            return "error", "LLM call failed: %s" % exc
        if int(status) >= 400:
            message = payload.get("message") or payload.get("error") or "LLM call returned HTTP %s" % int(status)
            return "error", str(message)
        text = self._text_from_payload(payload)
        return ("ok", text) if text else ("error", "LLM returned an empty response")

    def _text_from_payload(self, payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        if payload.get("text"):
            return str(payload.get("text") or "").strip()
        response = payload.get("response") if isinstance(payload.get("response"), dict) else {}
        if response.get("text"):
            return str(response.get("text") or "").strip()
        content = payload.get("content") if isinstance(payload.get("content"), list) else response.get("content") if isinstance(response.get("content"), list) else []
        parts = [str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("text")]
        return "\n".join(parts).strip()

    def _role_fallback(self, role: dict[str, Any], query: str, results: list[dict[str, Any]], reason: str) -> str:
        useful = [row for row in results if row.get("status") not in {"needs_key", "error", "not_indexed", "no_matches"}]
        top = useful[:2] or results[:2]
        evidence = "; ".join("%s (%s)" % (row.get("title"), row.get("citation")) for row in top if row.get("title"))
        return "%s fallback for '%s': %s Evidence reviewed: %s" % (
            role.get("label") or role.get("role") or "Research analyst",
            query,
            reason,
            evidence or "no usable evidence cards yet",
        )

    def _coordinator_fallback(
        self,
        query: str,
        results: list[dict[str, Any]],
        engines: list[dict[str, Any]],
        analysts: list[dict[str, Any]],
    ) -> str:
        useful = [row for row in results if row.get("status") not in {"needs_key", "error", "not_indexed", "no_matches"}]
        degraded = [engine["id"] for engine in engines if engine.get("run_status") in {"needs_key", "error", "degraded"}]
        citations = ", ".join(row.get("citation") or row.get("id") for row in useful[:3] if row.get("citation") or row.get("id"))
        analyst_count = len([row for row in analysts if row.get("text")])
        if useful:
            answer = "Coordinated answer for '%s': use the %s available evidence card(s) plus %s analyst perspective(s) as the basis for the decision." % (
                query,
                len(useful),
                analyst_count,
            )
        else:
            answer = "Coordinated answer for '%s': no usable live evidence is available yet, so configure search keys or index Local RAG before relying on this result." % query
        if citations:
            answer += " Leading citations: %s." % citations
        if degraded:
            answer += " Degraded engines: %s." % ", ".join(degraded)
        return answer

    def _synthesis(
        self,
        query: str,
        mode: str,
        results: list[dict[str, Any]],
        engines: list[dict[str, Any]],
        model_outputs: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        useful = [row for row in results if row.get("status") not in {"needs_key", "error", "not_indexed", "no_matches"}]
        degraded = [engine for engine in engines if engine.get("run_status") in {"needs_key", "error", "degraded"}]
        live = [row for row in useful if row.get("status") == "live"]
        local = [row for row in useful if row.get("engine") == "local-rag"]
        catalog = [row for row in useful if row.get("engine") == "digitalocean-docs"]
        source_engine_counts = self._source_counts(results, "engine")
        source_kind_counts = self._source_counts(results, "kind")
        source_coverage = self._source_coverage(results, engines)
        model_outputs = model_outputs if isinstance(model_outputs, dict) else {}
        coordinator = model_outputs.get("coordinator") if isinstance(model_outputs.get("coordinator"), dict) else {}
        analysts = model_outputs.get("analysts") if isinstance(model_outputs.get("analysts"), list) else []
        if useful:
            summary = "Found %s evidence cards for '%s': %s live web, %s DigitalOcean catalog/docs, and %s local RAG." % (
                len(useful),
                query,
                len(live),
                len(catalog),
                len(local),
            )
        else:
            summary = "No live evidence cards are available yet for '%s'. Configure external search keys or build the Local RAG index." % query
        source_parts = [
            "%s %s" % (count, label)
            for engine_id, label in RESEARCH_SOURCE_ENGINE_LABELS.items()
            for count in [source_engine_counts.get(engine_id, 0)]
            if count
        ]
        if source_parts:
            summary += " Source classes include %s." % ", ".join(source_parts)
        covered_required = len([row for row in source_coverage if row.get("status") == "covered"])
        if covered_required:
            summary += " Required source coverage: %s/%s classes covered." % (covered_required, len(source_coverage))
        if degraded:
            summary += " %s engine(s) are degraded or need configuration." % len(degraded)
        return {
            "title": "%s Research synthesis" % mode,
            "summary": summary,
            "citations": [row["id"] for row in useful[:8]],
            "degraded_engines": [engine["id"] for engine in degraded],
            "live_result_count": len(live),
            "evidence_count": len(useful),
            "analyst_count": len([row for row in analysts if isinstance(row, dict)]),
            "coordinator_model": coordinator.get("display_name") or coordinator.get("model_id") or "",
            "coordinated_answer": model_outputs.get("answer") or coordinator.get("text") or "",
            "source_engine_counts": source_engine_counts,
            "source_kind_counts": source_kind_counts,
            "source_coverage": source_coverage,
        }
