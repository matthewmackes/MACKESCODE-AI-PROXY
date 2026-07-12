"""Shared v2 chat response normalization."""
from __future__ import annotations

from typing import Any

from src.console.services.chat import _chat_output_diagnostics


def normalize_chat_result(result: dict[str, Any], client_selected_model: str = "") -> dict[str, Any]:
    """Attach diagnostics and trace aliases without changing the answer text."""
    payload = dict(result or {})
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    text = payload.get("text")
    if not isinstance(payload.get("diagnostics"), dict):
        payload["diagnostics"] = _chat_output_diagnostics(text if isinstance(text, str) else "", raw)

    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    if client_selected_model:
        routing = dict(routing)
        routing.setdefault("client_selected", client_selected_model)
        payload["routing"] = routing

    claude_do = raw.get("claude_do") if isinstance(raw.get("claude_do"), dict) else {}
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    console_trace_id = payload.get("trace_id") or routing.get("trace_id") or trace.get("trace_id") or ""
    upstream_trace_id = claude_do.get("trace_id") or raw.get("trace_id") or ""
    if console_trace_id or upstream_trace_id:
        payload["trace"] = {
            **trace,
            "console_trace_id": console_trace_id,
            "upstream_trace_id": upstream_trace_id,
        }
    return payload
