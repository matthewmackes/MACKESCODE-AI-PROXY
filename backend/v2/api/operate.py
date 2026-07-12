"""v2 Automation, Eval, CI, and Release operation routes."""
from __future__ import annotations

from typing import Any, Optional

from backend.v2.api.auth import capability_service, identity_from_request
from backend.v2.api.cost_control import enforce_cost_pause
from backend.v2.services.legacy_console import LegacyConsoleAdapter

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Query = None  # type: ignore[assignment]
    Request = object  # type: ignore[assignment]


operate_adapter = LegacyConsoleAdapter()
router = APIRouter(prefix="/v2/operate", tags=["operate"]) if APIRouter else None


def _identity(request: Request, authorization: Optional[str], console_token: Optional[str], token: Optional[str]) -> dict[str, Any]:
    return identity_from_request(request, authorization, console_token, token)


def _require(identity: dict[str, Any], action: str) -> None:
    decision = capability_service.decide(identity, action)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.to_dict())


def _active_high_risk_drift_names() -> set[str]:
    try:
        payload = operate_adapter.operate_payload()
    except Exception:
        return set()
    config_drift = payload.get("config_drift") if isinstance(payload, dict) else {}
    drift_rows = config_drift.get("drift") if isinstance(config_drift, dict) else []
    names: set[str] = set()
    for row in drift_rows if isinstance(drift_rows, list) else []:
        if not isinstance(row, dict):
            continue
        risk = str(row.get("risk") or "medium").lower()
        if risk not in {"critical", "high"}:
            continue
        if not row.get("changed", True) or row.get("acknowledged"):
            continue
        name = str(row.get("name") or row.get("id") or "").strip()
        if name:
            names.add(name)
    return names


def _requested_drift_items(payload: dict[str, Any]) -> set[str] | None:
    items = payload.get("items")
    if isinstance(items, str):
        return {items}
    if isinstance(items, list):
        return {str(item) for item in items if str(item).strip()}
    return None


def _confirmed_high_risk_items(payload: dict[str, Any]) -> set[str]:
    items = payload.get("confirmed_high_risk_items")
    if isinstance(items, str):
        return {items}
    if isinstance(items, list):
        return {str(item) for item in items if str(item).strip()}
    return set()


def _require_high_risk_confirmation(payload: dict[str, Any], action: str) -> None:
    high_risk = _active_high_risk_drift_names()
    if action == "acknowledge":
        requested = _requested_drift_items(payload)
        if requested is not None:
            high_risk = high_risk & requested
    if not high_risk:
        return
    confirmed_items = _confirmed_high_risk_items(payload)
    if payload.get("confirm_high_risk") is True and high_risk <= confirmed_items:
        return
    if payload.get("confirm_high_risk") is True:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "config_drift_high_risk_confirmation_items_mismatch",
                "message": "high-risk config drift confirmation must include the active high-risk item names",
                "items": sorted(high_risk),
                "confirmed_items": sorted(confirmed_items),
            },
        )
    raise HTTPException(
        status_code=400,
        detail={
            "code": "config_drift_high_risk_confirmation_required",
            "message": "high-risk config drift requires explicit confirmation",
            "items": sorted(high_risk),
        },
    )


if router:

    @router.get("")
    def operate_payload(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "console.view")
        return operate_adapter.operate_payload()

    @router.post("/ci-triage/preview")
    def ci_triage_preview(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.repository.import")
        return operate_adapter.preview_ci_triage(payload)

    @router.post("/ci-triage/launch")
    def ci_triage_launch(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.repository.import")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.launch_ci_triage(payload)

    @router.post("/repository-context/preview")
    def repository_context_preview(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.repository.import")
        return operate_adapter.preview_repository_context(payload)

    @router.post("/repository-context/import")
    def repository_context_import(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.repository.import")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.import_repository_context(payload)

    @router.post("/release/report")
    def release_report(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.rollback.admin")
        return operate_adapter.write_release_candidate_report(payload)

    @router.post("/config-drift/baseline")
    def config_drift_baseline(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.config_drift.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        _require_high_risk_confirmation(payload, "baseline")
        try:
            return operate_adapter.mark_config_drift_baseline(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "config_drift_baseline_invalid", "message": str(exc)}) from exc

    @router.post("/config-drift/acknowledge")
    def config_drift_acknowledge(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.config_drift.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        _require_high_risk_confirmation(payload, "acknowledge")
        try:
            return operate_adapter.acknowledge_config_drift(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"code": "config_drift_ack_invalid", "message": str(exc)}) from exc

    @router.post("/rollback/preview")
    def rollback_preview(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.rollback.admin")
        return operate_adapter.preview_rollback(payload)

    @router.post("/rollback/apply")
    def rollback_apply(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.rollback.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.apply_rollback(payload)

    @router.post("/reviews/update")
    def review_update(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.review.manage")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.update_review(payload)

    @router.post("/reviews/promote")
    def review_promote(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.review.manage")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.promote_review(payload)

    @router.post("/evals/datasets")
    def save_eval_dataset(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "evals.run")
        return operate_adapter.save_eval_dataset(payload)

    @router.post("/evals/datasets/build")
    def build_eval_dataset(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "evals.run")
        return operate_adapter.build_eval_dataset(payload)

    @router.post("/evals/run")
    def run_eval(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "evals.run")
        enforce_cost_pause("operate.evals.run", "llm_service", identity)
        return operate_adapter.run_eval(payload)

    @router.post("/automation/rules")
    def automation_rules_save(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.automation.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.save_automation_rules(payload)

    @router.post("/automation/test")
    def automation_test(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.automation.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.test_automation_event(payload)

    @router.post("/automation/run")
    def automation_run(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.automation.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.run_automation_event(payload)

    @router.post("/automation/schedules/run-due")
    def automation_schedules_run_due(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "operate.automation.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.run_due_automation_schedules(payload)

    @router.post("/model-deprecations/preview")
    def model_deprecation_preview(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "models.admin")
        return operate_adapter.preview_model_deprecation(payload)

    @router.post("/model-deprecations/apply")
    def model_deprecation_apply(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "models.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.apply_model_deprecation(payload)

    @router.post("/model-deprecations/rollback")
    def model_deprecation_rollback(
        payload: dict[str, Any],
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_matts_console_token: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> dict[str, Any]:
        identity = _identity(request, authorization, x_matts_console_token, token)
        _require(identity, "models.admin")
        payload = dict(payload or {})
        payload["actor"] = identity
        return operate_adapter.rollback_model_deprecation(payload)
