"""Standard error payload helpers for console HTTP and API responses."""


def error_category(status):
    code = int(status)
    if code == 401:
        return "auth"
    if code == 403:
        return "permission"
    if code == 404:
        return "not_found"
    if 400 <= code < 500:
        return "client"
    if 500 <= code < 600:
        return "server"
    return "unknown"


def error_code(status, category=None):
    category = category or error_category(status)
    return "%s_error" % category


def error_payload(message, status, code=None, category=None, details=None):
    category = category or error_category(status)
    payload = {
        "error": str(message),
        "message": str(message),
        "code": code or error_code(status, category),
        "category": category,
        "status": int(status),
    }
    if details is not None:
        payload["details"] = details
    return payload


def normalize_error_payload(payload, status, code=None, category=None, default_message="request failed"):
    if isinstance(payload, dict):
        message = payload.get("message")
        raw_error = payload.get("error")
        if not message:
            if isinstance(raw_error, dict):
                message = raw_error.get("message") or default_message
            elif raw_error:
                message = str(raw_error)
            else:
                message = default_message
        normalized = dict(payload)
        normalized.update(error_payload(message, status, code=code or payload.get("code"), category=category or payload.get("category")))
        if isinstance(raw_error, dict):
            normalized.setdefault("details", {})
            if isinstance(normalized["details"], dict):
                normalized["details"].setdefault("upstream_error", raw_error)
        return normalized
    return error_payload(default_message, status, code=code, category=category, details={"response": payload})


def json_error(status, message, code=None, category=None, details=None):
    return int(status), error_payload(message, status, code=code, category=category, details=details)
