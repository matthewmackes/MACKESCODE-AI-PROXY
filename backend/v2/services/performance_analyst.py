"""AI performance analyst service for proxy and monitored model telemetry."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Callable

from backend.v2.services.legacy_console import LegacyConsoleAdapter
from backend.v2.services.model_showcase import ModelShowcaseService
from backend.v2.services.research_search import ResearchSearchService
from src.console.services.decision_explain import DecisionExplanationService
from src.console.services.operational_store import OperationalStore


GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class PerformanceAnalystService:
    """Summarize operational telemetry and persist analyst assessments."""

    def __init__(
        self,
        *,
        legacy_adapter: LegacyConsoleAdapter | None = None,
        showcase_service: ModelShowcaseService | None = None,
        research_service_factory: Callable[[], ResearchSearchService] | None = None,
        store: OperationalStore | None = None,
        clock: Callable[[], float] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.legacy_adapter = legacy_adapter or LegacyConsoleAdapter()
        self.showcase_service = showcase_service or ModelShowcaseService()
        self.research_service_factory = research_service_factory or (
            lambda: ResearchSearchService(
                env={**os.environ, "MATTS_RESEARCH_LLM_ENABLED": "0"},
                chat_completion=self.legacy_adapter.chat_completion,
            )
        )
        self.store = store or OperationalStore()
        self.clock = clock or time.time
        self.env = env if env is not None else os.environ
        self.redactor = DecisionExplanationService(clock=self.clock)

    def payload(self, *, force: bool = False, actor: dict[str, Any] | None = None, allow_preview: bool = True) -> dict[str, Any]:
        latest = self.store.latest_analyst_run()
        telemetry = self.telemetry_payload()
        fingerprint = self.telemetry_fingerprint(telemetry)
        if latest and not force and latest.get("fingerprint") == fingerprint:
            return {**latest, "cache": {"status": "hit", "reason": "telemetry_fingerprint_unchanged"}}
        if latest and not force:
            next_due = float(latest.get("next_run_at") or 0)
            if next_due and self.clock() < next_due:
                return {**latest, "cache": {"status": "fresh", "next_run_at": next_due}}
        if not latest and not force and allow_preview:
            model = self.select_analyst_model(telemetry.get("models", []))
            payload = self.deterministic_assessment(
                telemetry,
                model,
                public_context={"status": "pending", "evidence": [], "sources": []},
                status="pending_full_analysis",
            )
            cadence = self.cadence(payload)
            payload.update({
                "fingerprint": fingerprint,
                "cap": self.analyst_cap_state(),
                "cadence": cadence,
                "next_run_at": self.clock() + cadence["next_interval_seconds"],
                "cache": {"status": "preview", "reason": "no_persisted_run"},
                "actor": {"id": (actor or {}).get("id") or "system", "source": (actor or {}).get("source") or "analyst"},
            })
            return payload
        result = self.run(telemetry=telemetry, fingerprint=fingerprint, actor=actor or {})
        return result

    def run(self, *, telemetry: dict[str, Any] | None = None, fingerprint: str | None = None, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        telemetry = telemetry or self.telemetry_payload()
        fingerprint = fingerprint or self.telemetry_fingerprint(telemetry)
        model = self.select_analyst_model(telemetry.get("models", []))
        cap = self.analyst_cap_state()
        if cap.get("status") == "exceeded":
            payload = self.deterministic_assessment(telemetry, model, public_context={}, status="paused_by_analyst_cap")
            payload.update({"fingerprint": fingerprint, "cap": cap, "next_run_at": self.clock() + 900})
            return self.store.save_analyst_run(payload)
        public_context = self.public_sweep()
        llm_payload = self.llm_assessment(telemetry, public_context, model)
        if llm_payload:
            payload = self.normalize_llm_payload(llm_payload, telemetry, model, public_context)
        else:
            payload = self.deterministic_assessment(telemetry, model, public_context)
        payload.update({
            "fingerprint": fingerprint,
            "cap": cap,
            "cadence": self.cadence(payload),
            "next_run_at": self.clock() + self.cadence(payload)["next_interval_seconds"],
            "actor": {"id": (actor or {}).get("id") or "system", "source": (actor or {}).get("source") or "analyst"},
        })
        stored = self.store.save_analyst_run(payload)
        self.push_high_findings(stored)
        return stored

    def telemetry_payload(self) -> dict[str, Any]:
        short_analytics = self.safe_call(lambda: self.legacy_adapter._safe_call("analytics_payload", {}, days=1), {})
        baseline_analytics = self.safe_call(lambda: self.legacy_adapter._safe_call("analytics_payload", {}, days=7), {})
        observe = self.safe_call(lambda: self.legacy_adapter.observe_payload(days=7, trace_limit=200, audit_limit=80), {})
        operate = self.safe_call(self.legacy_adapter.operate_payload, {})
        models = self.safe_call(lambda: self.showcase_service.payload().get("models") or [], [])
        scorecards = self.safe_call(lambda: self.legacy_adapter._safe_call("model_scorecards_payload", {}, days=30), {})
        cost = _record(observe.get("cost"))
        provider = _record(observe.get("provider_health"))
        return self.redactor.redact({
            "generated_at": self.clock(),
            "analytics": {"recent": short_analytics, "baseline": baseline_analytics},
            "cost": cost,
            "provider_health": provider,
            "telemetry": observe.get("telemetry") if isinstance(observe, dict) else {},
            "evals": observe.get("evals") if isinstance(observe, dict) else {},
            "operate": {
                "release_candidate": _record(operate.get("release_candidate")),
                "config_drift": _record(operate.get("config_drift")),
                "cost_control": _record(operate.get("cost_control")),
            },
            "models": models,
            "scorecards": scorecards,
            "history": self.history_digest(),
        })

    def telemetry_fingerprint(self, telemetry: dict[str, Any]) -> str:
        scrubbed = self._fingerprint_scrub(telemetry)
        return hashlib.sha256(_compact_json(scrubbed).encode("utf-8")).hexdigest()

    def _fingerprint_scrub(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._fingerprint_scrub(item)
                for key, item in value.items()
                if key not in {"generated_at", "checked_at", "updated_at", "created_at", "export_csv", "raw", "history"}
            }
        if isinstance(value, list):
            return [self._fingerprint_scrub(item) for item in value[:120]]
        return value

    def history_digest(self) -> dict[str, Any]:
        history = self.store.analyst_history(limit=12)
        grades = [(_record(row.get("proxy")).get("grade") or "") for row in history]
        high_counts = [_int(_record(_record(row.get("summary")).get("severity_counts")).get("high")) for row in history]
        return {
            "runs": len(history),
            "latest_grades": [grade for grade in grades if grade][:8],
            "high_findings_recent": high_counts[:8],
        }

    def analyst_cap_state(self) -> dict[str, Any]:
        cap_usd = _number(self.env.get("MATTS_ANALYST_DAILY_CAP_USD"), 0.25)
        history = [row for row in self.store.analyst_history(limit=100) if self.clock() - _number(row.get("generated_at")) <= 86400]
        spent = round(sum(_number(row.get("estimated_cost_usd")) for row in history), 8)
        return {
            "daily_cap_usd": cap_usd,
            "estimated_24h_usd": spent,
            "status": "exceeded" if cap_usd > 0 and spent >= cap_usd else "ok",
            "runs_24h": len(history),
        }

    def select_analyst_model(self, models: Any) -> dict[str, Any]:
        candidates = []
        for card in _records(models):
            if card.get("type") != "text" or not card.get("route_enabled"):
                continue
            price = self.max_text_price(card)
            if price <= 0:
                continue
            health = _record(card.get("health"))
            grade = str(health.get("grade") or "")
            rank = GRADE_ORDER.get(grade, 9)
            row = dict(card)
            row["max_text_price_usd"] = price
            row["selection_grade"] = grade or "unmeasured"
            row["selection_rank"] = rank
            candidates.append(row)
        candidates.sort(key=lambda row: (row["selection_rank"], row["max_text_price_usd"], -_int(row.get("context_window")), str(row.get("display_name") or "")))
        selected = candidates[0] if candidates else {}
        fallback = bool(selected and selected.get("selection_grade") != "A")
        return {
            "id": selected.get("id") or "",
            "display_name": selected.get("display_name") or selected.get("id") or "",
            "grade": selected.get("selection_grade") or "",
            "max_text_price_usd": selected.get("max_text_price_usd") or 0,
            "fallback": fallback,
            "candidate_count": len(candidates),
            "policy": "cheapest route_enabled measured grade-A text model; fallback to B/C/unmeasured when no A exists",
        }

    def max_text_price(self, card: dict[str, Any]) -> float:
        pricing = _record(card.get("pricing"))
        return max([_number(pricing.get("input")), _number(pricing.get("output")), 0.0])

    def public_sweep(self) -> dict[str, Any]:
        if str(self.env.get("MATTS_ANALYST_PUBLIC_SWEEP", "1")).lower() in {"0", "false", "no", "off"}:
            return {"status": "disabled", "evidence": [], "sources": []}
        try:
            dossier = self.research_service_factory().search({
                "query": "DigitalOcean inference status LLM provider outage model performance latency",
                "mode": "Fast",
                "engines": ["digitalocean-docs", "technical-docs", "wikipedia"],
                "limit": 4,
            })
        except Exception as exc:
            return {"status": "degraded", "error": str(exc), "evidence": [], "sources": []}
        evidence = _records(dossier.get("evidence"))[:8]
        return {
            "status": "ok",
            "dossier_id": dossier.get("dossier_id"),
            "answer": _record(dossier.get("synthesis")).get("answer") or _record(dossier.get("synthesis")).get("coordinated_answer") or "",
            "evidence": [{
                "title": row.get("title"),
                "url": row.get("url"),
                "source": row.get("source") or row.get("engine_name"),
                "citation": row.get("citation"),
                "status": row.get("status"),
            } for row in evidence],
            "sources": sorted({str(row.get("source") or row.get("engine_name") or "") for row in evidence if row.get("source") or row.get("engine_name")}),
        }

    def llm_assessment(self, telemetry: dict[str, Any], public_context: dict[str, Any], model: dict[str, Any]) -> dict[str, Any] | None:
        model_id = str(model.get("id") or "")
        if not model_id:
            return None
        if str(self.env.get("MATTS_ANALYST_LLM_ENABLED", "1")).lower() in {"0", "false", "no", "off"}:
            return None
        prompt = self.analyst_prompt(telemetry, public_context)
        try:
            status, payload = self.legacy_adapter.chat_completion({
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": _int(self.env.get("MATTS_ANALYST_MAX_TOKENS"), 900),
                "temperature": 0.1,
                "request_timeout_seconds": _int(self.env.get("MATTS_ANALYST_TIMEOUT_SECONDS"), 20),
                "trace_status_on_error": "fallback",
                "trace_origin": "performance_analyst",
            })
        except Exception:
            return None
        if int(status) >= 400:
            return None
        text = self.text_from_payload(payload)
        parsed = self.parse_json(text)
        return parsed if isinstance(parsed, dict) else None

    def analyst_prompt(self, telemetry: dict[str, Any], public_context: dict[str, Any]) -> str:
        summary = {
            "recent_analytics": _record(_record(telemetry.get("analytics")).get("recent")).get("summary"),
            "baseline_analytics": _record(_record(telemetry.get("analytics")).get("baseline")).get("summary"),
            "cost": telemetry.get("cost"),
            "provider_findings": _record(telemetry.get("provider_health")).get("findings"),
            "operate": telemetry.get("operate"),
            "model_count": len(_records(telemetry.get("models"))),
            "models": [{
                "id": row.get("id"),
                "name": row.get("display_name"),
                "health": row.get("health"),
                "route_enabled": row.get("route_enabled"),
                "cost": row.get("cost_label"),
            } for row in _records(telemetry.get("models"))[:80]],
            "history": telemetry.get("history"),
            "public_context": public_context,
        }
        return (
            "You are an SRE performance analyst for MDE LLM-PROXY. "
            "Return STRICT JSON only with keys: proxy, models, findings, summary, trend. "
            "Grades are A/B/C/D. Findings use severity high/medium/low and cite metric, value, source, and suggested_action. "
            "Never include prompts, responses, secrets, or raw user content.\n\nTelemetry:\n%s"
        ) % json.dumps(summary, sort_keys=True)

    def normalize_llm_payload(self, payload: dict[str, Any], telemetry: dict[str, Any], model: dict[str, Any], public_context: dict[str, Any]) -> dict[str, Any]:
        fallback = self.deterministic_assessment(telemetry, model, public_context)
        proxy = _record(payload.get("proxy")) or fallback["proxy"]
        findings = _records(payload.get("findings")) or fallback["findings"]
        model_rows = _records(payload.get("models")) or fallback["models"]
        normalized_findings = [self.normalize_finding(row, index) for index, row in enumerate(findings[:24])]
        summary = self.summary_for(normalized_findings, proxy)
        return {
            **fallback,
            "status": "ok",
            "mode": "llm",
            "model_id": model.get("id") or "",
            "model_label": model.get("display_name") or model.get("id") or "",
            "proxy": {
                "grade": str(proxy.get("grade") or fallback["proxy"]["grade"]),
                "score": _int(proxy.get("score"), fallback["proxy"]["score"]),
                "narrative": str(proxy.get("narrative") or proxy.get("summary") or fallback["proxy"]["narrative"]),
                "hard_cap_reason": str(proxy.get("hard_cap_reason") or fallback["proxy"].get("hard_cap_reason") or ""),
            },
            "models": [self.normalize_model_assessment(row) for row in model_rows[:80]],
            "findings": normalized_findings,
            "summary": summary,
            "estimated_cost_usd": self.estimate_llm_cost(model),
        }

    def deterministic_assessment(self, telemetry: dict[str, Any], model: dict[str, Any], public_context: dict[str, Any], status: str = "ok") -> dict[str, Any]:
        findings = self.deterministic_findings(telemetry, public_context)
        proxy = self.proxy_grade(telemetry, findings)
        model_rows = self.model_assessments(telemetry)
        summary = self.summary_for(findings, proxy)
        now = float(self.clock())
        return {
            "schema_version": 1,
            "run_id": hashlib.sha256(("%s|%s" % (now, _compact_json(summary))).encode("utf-8")).hexdigest()[:24],
            "generated_at": now,
            "status": status,
            "mode": "deterministic" if status == "ok" else status,
            "model_id": model.get("id") or "",
            "model_label": model.get("display_name") or model.get("id") or "",
            "model_policy": model.get("policy") or "",
            "proxy": proxy,
            "models": model_rows,
            "findings": findings,
            "summary": summary,
            "trend": self.trend(telemetry),
            "public_context": public_context,
            "sources": self.sources(telemetry, public_context),
            "estimated_cost_usd": 0.0,
        }

    def deterministic_findings(self, telemetry: dict[str, Any], public_context: dict[str, Any]) -> list[dict[str, Any]]:
        findings = []
        recent = _record(_record(telemetry.get("analytics")).get("recent")).get("summary") or {}
        baseline = _record(_record(telemetry.get("analytics")).get("baseline")).get("summary") or {}
        success = _number(_record(recent).get("success_rate"), 1.0)
        baseline_success = _number(_record(baseline).get("success_rate"), success)
        latency = _number(_record(recent).get("avg_latency_ms"))
        baseline_latency = _number(_record(baseline).get("avg_latency_ms"), latency)
        if success < 0.95:
            findings.append(self.finding("high", "Proxy success rate is degraded", "success_rate", success, "observe.analytics.recent", "Inspect failure categories and replay recent failed traces."))
        elif baseline_success - success >= 0.03:
            findings.append(self.finding("medium", "Proxy success rate is worse than baseline", "success_rate_delta", round(success - baseline_success, 4), "observe.analytics", "Compare recent failure categories with the 7 day baseline."))
        if latency > 0 and (latency >= 5000 or (baseline_latency > 0 and latency > baseline_latency * 1.8)):
            findings.append(self.finding("medium", "Proxy latency is above normal", "avg_latency_ms", int(latency), "observe.analytics.recent", "Check provider health and the slowest model routes."))
        provider = _record(telemetry.get("provider_health"))
        for row in _records(provider.get("findings"))[:8]:
            severity = str(row.get("severity") or "medium").lower()
            findings.append(self.finding(severity, str(row.get("title") or "Provider health finding"), str(row.get("type") or "provider"), row.get("detail") or "", "observe.provider_health", "Treat provider incidents as root-cause context before blaming a model."))
        cost = _record(telemetry.get("cost"))
        cross = _record(_record(cost.get("digitalocean")).get("local_estimate_cross_check"))
        if cross.get("status") == "diverged":
            findings.append(self.finding("medium", "DigitalOcean billed spend diverges from local estimate", "billing_delta_usd", cross.get("delta_usd"), "observe.cost.digitalocean", "Review provider billing insights and local usage logs."))
        operate = _record(telemetry.get("operate"))
        drift = _record(_record(operate.get("config_drift")).get("summary"))
        if _int(drift.get("active_drift_count")) > 0:
            findings.append(self.finding("medium", "Active config drift can affect release confidence", "active_drift_count", _int(drift.get("active_drift_count")), "operate.config_drift", "Open Operate and resolve or acknowledge active drift."))
        for model in _records(telemetry.get("models")):
            health = _record(model.get("health"))
            if health.get("grade") in {"D"}:
                findings.append(self.finding("medium", "%s health grade is D" % (model.get("display_name") or model.get("id")), "model_health_grade", "D", "models.health", "Move traffic to a healthier model or run an eval to confirm."))
        if public_context.get("status") == "degraded":
            findings.append(self.finding("low", "Public context sweep is degraded", "public_sweep_status", "degraded", "research.public_sweep", "Analyst can still use internal telemetry; public outage context is incomplete."))
        return sorted(findings, key=lambda row: (SEVERITY_ORDER.get(row["severity"], 9), row["title"]))[:24]

    def finding(self, severity: str, title: str, metric: str, value: Any, source: str, action: str) -> dict[str, Any]:
        fingerprint = hashlib.sha256(("%s|%s|%s|%s" % (severity, title, metric, value)).encode("utf-8")).hexdigest()[:24]
        return {
            "id": fingerprint,
            "fingerprint": fingerprint,
            "severity": severity if severity in SEVERITY_ORDER else "low",
            "title": title,
            "metric": metric,
            "value": value,
            "source": source,
            "source_link": self.source_link(source),
            "suggested_action": action,
            "lifecycle_status": "new",
        }

    def source_link(self, source: str) -> str:
        if source.startswith("observe"):
            return "#advanced"
        if source.startswith("operate"):
            return "#advanced"
        if source.startswith("models"):
            return "#models"
        if source.startswith("research"):
            return "#research"
        return "#advanced"

    def proxy_grade(self, telemetry: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        recent = _record(_record(telemetry.get("analytics")).get("recent")).get("summary") or {}
        success = _number(_record(recent).get("success_rate"), 1.0)
        latency = _number(_record(recent).get("avg_latency_ms"))
        score = 100
        score -= max(0, int((1.0 - success) * 160))
        if latency > 1000:
            score -= min(30, int(latency / 500))
        score -= len([row for row in findings if row["severity"] == "high"]) * 25
        score -= len([row for row in findings if row["severity"] == "medium"]) * 8
        score = max(0, min(100, score))
        if any(row["severity"] == "high" for row in findings):
            grade = "C" if score >= 70 else "D"
            hard_cap_reason = "high severity finding"
        elif score >= 90:
            grade = "A"
            hard_cap_reason = ""
        elif score >= 75:
            grade = "B"
            hard_cap_reason = ""
        elif score >= 55:
            grade = "C"
            hard_cap_reason = ""
        else:
            grade = "D"
            hard_cap_reason = ""
        return {
            "grade": grade,
            "score": score,
            "narrative": "Proxy success %.1f%% with average latency %sms and %s active finding(s)." % (success * 100, int(latency), len(findings)),
            "hard_cap_reason": hard_cap_reason,
        }

    def model_assessments(self, telemetry: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for model in _records(telemetry.get("models")):
            health = _record(model.get("health"))
            grade = str(health.get("grade") or "C")
            measured = bool(health.get("measured"))
            rows.append({
                "model": model.get("id"),
                "display_name": model.get("display_name") or model.get("id"),
                "grade": grade if measured else "C",
                "measured": measured,
                "score": {"A": 95, "B": 82, "C": 65, "D": 35}.get(grade, 60) if measured else 50,
                "narrative": "Measured %s requests; p50 %sms; success %s." % (
                    _int(health.get("requests")),
                    health.get("p50_latency_ms") if health.get("p50_latency_ms") is not None else "n/a",
                    "%.1f%%" % (_number(health.get("success_rate")) * 100) if health.get("success_rate") is not None else "unmeasured",
                ),
                "metrics": {
                    "success_rate": health.get("success_rate"),
                    "p50_latency_ms": health.get("p50_latency_ms"),
                    "requests": health.get("requests"),
                    "route_enabled": model.get("route_enabled"),
                    "cost_label": model.get("cost_label"),
                },
            })
        return sorted(rows, key=lambda row: (GRADE_ORDER.get(row["grade"], 9), row["display_name"]))[:80]

    def normalize_finding(self, row: dict[str, Any], index: int) -> dict[str, Any]:
        return self.finding(
            str(row.get("severity") or "low").lower(),
            str(row.get("title") or row.get("summary") or "Analyst finding %s" % (index + 1)),
            str(row.get("metric") or row.get("type") or "analyst"),
            row.get("value") if row.get("value") is not None else row.get("detail") or "",
            str(row.get("source") or "analyst.llm"),
            str(row.get("suggested_action") or row.get("action") or "Review the cited source data."),
        )

    def normalize_model_assessment(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": row.get("model") or row.get("id") or row.get("model_id") or "",
            "display_name": row.get("display_name") or row.get("name") or row.get("model") or "",
            "grade": str(row.get("grade") or "C"),
            "score": _int(row.get("score"), 60),
            "narrative": str(row.get("narrative") or row.get("summary") or ""),
            "metrics": _record(row.get("metrics")),
            "measured": row.get("measured") is not False,
        }

    def summary_for(self, findings: list[dict[str, Any]], proxy: dict[str, Any]) -> dict[str, Any]:
        counts = {"high": 0, "medium": 0, "low": 0}
        for finding in findings:
            severity = finding.get("severity") if finding.get("severity") in counts else "low"
            counts[severity] += 1
        top = findings[0] if findings else {}
        return {
            "proxy_grade": proxy.get("grade") or "C",
            "top_finding": top.get("title") or "No active findings",
            "severity_counts": counts,
            "finding_count": len(findings),
        }

    def trend(self, telemetry: dict[str, Any]) -> dict[str, Any]:
        recent = _record(_record(telemetry.get("analytics")).get("recent")).get("summary") or {}
        baseline = _record(_record(telemetry.get("analytics")).get("baseline")).get("summary") or {}
        return {
            "success_rate_delta": round(_number(_record(recent).get("success_rate"), 1.0) - _number(_record(baseline).get("success_rate"), 1.0), 4),
            "avg_latency_delta_ms": int(_number(_record(recent).get("avg_latency_ms")) - _number(_record(baseline).get("avg_latency_ms"))),
            "history": telemetry.get("history") or {},
        }

    def sources(self, telemetry: dict[str, Any], public_context: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"id": "observe.analytics", "label": "Observe analytics", "href": "#advanced"},
            {"id": "observe.provider_health", "label": "Provider health", "href": "#advanced"},
            {"id": "operate.release", "label": "Operate readiness", "href": "#advanced"},
            {"id": "models.health", "label": "Model health cards", "href": "#models"},
            {"id": "public_context", "label": "Public context sweep", "href": "#research", "status": public_context.get("status")},
        ]

    def cadence(self, payload: dict[str, Any]) -> dict[str, Any]:
        counts = _record(_record(payload.get("summary")).get("severity_counts"))
        high = _int(counts.get("high"))
        medium = _int(counts.get("medium"))
        if high:
            interval = _int(self.env.get("MATTS_ANALYST_HIGH_INTERVAL_SECONDS"), 180)
        elif medium:
            interval = _int(self.env.get("MATTS_ANALYST_MEDIUM_INTERVAL_SECONDS"), 300)
        else:
            interval = _int(self.env.get("MATTS_ANALYST_HEALTHY_INTERVAL_SECONDS"), 900)
        return {"mode": "adaptive", "next_interval_seconds": max(60, interval)}

    def push_high_findings(self, payload: dict[str, Any]) -> None:
        high = [row for row in _records(payload.get("findings")) if row.get("severity") == "high"]
        if not high:
            return
        try:
            self.legacy_adapter.run_automation_event({
                "type": "analyst.high",
                "severity": "high",
                "title": high[0].get("title"),
                "findings": high[:5],
                "source": "performance_analyst",
            })
        except Exception:
            pass

    def estimate_llm_cost(self, model: dict[str, Any]) -> float:
        # The proxy records actual spend; this conservative marker lets the
        # analyst cap work even when the usage row is delayed or unavailable.
        return round(max(0.0001, _number(model.get("max_text_price_usd")) * 0.000003), 8) if model.get("id") else 0.0

    def text_from_payload(self, payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("text", "message", "answer"):
            if payload.get(key):
                return str(payload[key])
        response = _record(payload.get("response"))
        if response.get("text"):
            return str(response["text"])
        content = payload.get("content") if isinstance(payload.get("content"), list) else response.get("content") if isinstance(response.get("content"), list) else []
        return "\n".join(str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("text"))

    def parse_json(self, text: str) -> Any:
        text = str(text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            pass
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        if match:
            try:
                return json.loads(match.group(1))
            except ValueError:
                return None
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                return None
        return None

    def safe_call(self, fn: Callable[[], Any], fallback: Any) -> Any:
        try:
            value = fn()
            return value if value is not None else fallback
        except Exception as exc:
            return {"error": str(exc)} if isinstance(fallback, dict) else fallback


def analyst_worker(service_factory: Callable[[], PerformanceAnalystService], stop_event: threading.Event, initial_delay: float = 10.0) -> None:
    if initial_delay > 0:
        stop_event.wait(initial_delay)
    while not stop_event.is_set():
        try:
            service = service_factory()
            payload = service.payload(force=False, actor={"id": "analyst-worker", "source": "daemon"}, allow_preview=False)
            interval = _int(_record(payload.get("cadence")).get("next_interval_seconds"), 300)
        except Exception:
            interval = 300
        stop_event.wait(max(60, interval))
