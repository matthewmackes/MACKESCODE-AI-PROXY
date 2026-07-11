"""Standard error payload helpers for console HTTP and API responses."""


def _levenshtein(left, right, limit=64):
    left = str(left or "")[:limit]
    right = str(right or "")[:limit]
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def route_suggestions(path, routes, limit=5):
    """Return nearest route strings for a missing API path."""

    requested = str(path or "").split("?", 1)[0]
    candidates = sorted({str(route) for route in routes if route})
    if not requested or not candidates:
        return []
    requested_parts = [part for part in requested.strip("/").split("/") if part]

    def score(route):
        route_parts = [part for part in route.strip("/").split("/") if part]
        prefix_matches = 0
        for left, right in zip(requested_parts, route_parts):
            if left != right:
                break
            prefix_matches += 1
        distance = _levenshtein(requested, route)
        length_delta = abs(len(requested) - len(route))
        return (distance - prefix_matches, length_delta, route)

    return [route for _score, _delta, route in sorted((score(route) for route in candidates))[:max(1, int(limit or 5))]]


def _sorted_methods(methods):
    order = {"GET": 0, "POST": 1, "PUT": 2, "PATCH": 3, "DELETE": 4, "OPTIONS": 5, "HEAD": 6}
    return sorted({str(item).upper() for item in methods if item}, key=lambda item: (order.get(item, 99), item))


def _route_method_rows(routes, route_methods, limit):
    rows = []
    for route in routes[:max(1, int(limit or 5))]:
        methods = _sorted_methods((route_methods or {}).get(route, []))
        rows.append({"path": route, "methods": methods})
    return rows


def route_not_found_details(path, method, routes, limit=5, route_methods=None):
    clean_path = str(path or "").split("?", 1)[0]
    request_method = str(method or "").upper()
    details = {"path": clean_path, "method": request_method}
    route_methods = {str(route): _sorted_methods(methods) for route, methods in (route_methods or {}).items()}
    all_routes = sorted({str(route) for route in routes if route} | set(route_methods.keys()))
    method_routes = [route for route in all_routes if request_method in route_methods.get(route, [request_method])]
    exact_methods = route_methods.get(clean_path)
    if exact_methods and request_method not in exact_methods:
        details["method_mismatch"] = True
        details["allowed_methods"] = exact_methods
        details["suggested_endpoints"] = [clean_path]
        details["nearby_endpoints"] = [{"path": clean_path, "methods": exact_methods}]
        details["suggested_fix"] = "Use %s %s; this endpoint exists but not for %s." % (exact_methods[0], clean_path, request_method)
        return details
    suggestions = route_suggestions(clean_path, method_routes or all_routes, limit=limit)
    nearby = route_suggestions(clean_path, all_routes, limit=limit)
    if suggestions:
        details["suggested_endpoints"] = suggestions
        details["suggested_fix"] = "Use one of the suggested endpoints for this HTTP method, or refresh the UI if it is calling a stale route."
    if route_methods and nearby:
        details["nearby_endpoints"] = _route_method_rows(nearby, route_methods, limit)
        other_method_routes = [route for route in nearby if route not in set(method_routes)]
        if other_method_routes:
            details["other_method_endpoints"] = _route_method_rows(other_method_routes, route_methods, limit)
            if not suggestions:
                first = details["other_method_endpoints"][0]
                methods = first.get("methods") or []
                if methods:
                    details["suggested_endpoints"] = [first["path"]]
                    details["suggested_fix"] = "Use %s %s; the closest endpoint exists under a different HTTP method." % (methods[0], first["path"])
    return details


def error_category(status):
    code = int(status)
    if code == 401:
        return "auth"
    if code == 403:
        return "permission"
    if code == 404:
        return "not_found"
    if code == 429:
        return "rate_limit"
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
