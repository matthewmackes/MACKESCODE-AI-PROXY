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


def json_error(status, message, code=None, category=None, details=None):
    return int(status), error_payload(message, status, code=code, category=category, details=details)
