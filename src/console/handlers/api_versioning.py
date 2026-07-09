"""API version negotiation helpers for console JSON routes."""

SUPPORTED_API_VERSIONS = {"v1"}
DEFAULT_API_VERSION = "v1"
VENDOR_PREFIX = "application/vnd.matts-value-set."


def requested_header_version(headers):
    headers = headers or {}
    explicit = headers.get("x-matts-api-version", "").strip().lower()
    if explicit:
        return explicit
    accept = headers.get("accept", "")
    for part in str(accept).split(","):
        media = part.split(";", 1)[0].strip().lower()
        if media.startswith(VENDOR_PREFIX) and media.endswith("+json"):
            return media[len(VENDOR_PREFIX):-len("+json")]
    return ""


def api_version_info(path, headers=None):
    """Return normalized routing metadata for API paths."""
    path = str(path or "")
    header_version = requested_header_version(headers)
    if path == "/api/v1":
        return {
            "is_api": True,
            "path": "/api",
            "version": "v1",
            "deprecated": False,
            "unsupported": False,
            "raw_path": path,
            "requested_version": header_version or "v1",
        }
    if path.startswith("/api/v1/"):
        return {
            "is_api": True,
            "path": "/api/" + path[len("/api/v1/"):],
            "version": "v1",
            "deprecated": False,
            "unsupported": False,
            "raw_path": path,
            "requested_version": header_version or "v1",
        }
    if path.startswith("/api/v"):
        requested = path[len("/api/"):].split("/", 1)[0].lower()
        return {
            "is_api": True,
            "path": path,
            "version": requested,
            "deprecated": False,
            "unsupported": True,
            "raw_path": path,
            "requested_version": requested,
        }
    if path == "/api" or path.startswith("/api/"):
        requested = header_version or DEFAULT_API_VERSION
        return {
            "is_api": True,
            "path": path,
            "version": requested,
            "deprecated": True,
            "unsupported": requested not in SUPPORTED_API_VERSIONS,
            "raw_path": path,
            "requested_version": requested,
        }
    return {
        "is_api": False,
        "path": path,
        "version": "",
        "deprecated": False,
        "unsupported": False,
        "raw_path": path,
        "requested_version": header_version,
    }


def api_version_headers(info):
    if not info or not info.get("is_api"):
        return {}
    headers = {
        "x-matts-api-version": info.get("version") or DEFAULT_API_VERSION,
        "x-matts-api-supported-versions": ", ".join(sorted(SUPPORTED_API_VERSIONS)),
    }
    if info.get("deprecated"):
        headers["deprecation"] = "true"
        headers["warning"] = '299 - "Unversioned API path is deprecated; use /api/v1/..."'
        headers["link"] = '</api/v1/>; rel="successor-version"'
    return headers
