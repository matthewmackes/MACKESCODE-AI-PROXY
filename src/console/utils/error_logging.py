"""Structured logging helpers for console errors."""
import json
import logging
import os


LOGGER_NAME = "matts.console.errors"


def console_error_logger():
    return logging.getLogger(LOGGER_NAME)


def configure_console_logging(level=None):
    level_name = (level or os.environ.get("MATTS_CONSOLE_LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(level=getattr(logging, level_name, logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")


def error_log_record(method, path, status, payload):
    payload = payload if isinstance(payload, dict) else {}
    details = payload.get("details")
    details_keys = sorted(details.keys()) if isinstance(details, dict) else []
    return {
        "event": "console_error_response",
        "method": method or "",
        "path": path or "",
        "status": int(status),
        "code": payload.get("code") or "",
        "category": payload.get("category") or "",
        "message": payload.get("message") or payload.get("error") or "",
        "details_keys": details_keys,
    }


def log_error_response(method, path, status, payload, logger=None):
    record = error_log_record(method, path, status, payload)
    (logger or console_error_logger()).warning(json.dumps(record, sort_keys=True))
    return record
