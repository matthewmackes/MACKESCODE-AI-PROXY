"""Wallpaper metadata and cached image response helpers.

The Create page proxies a remote wallpaper image through the console so the
browser never talks to the upstream host directly. Because the console can bind
to ``0.0.0.0`` (see ``docs/THREAT_MODEL.md``), the ``remote`` URL is
attacker-influenced input: a LAN caller could try to turn this proxy into an
SSRF/DoS primitive by pointing it at cloud-metadata (``169.254.169.254``),
loopback, or RFC1918 addresses, or at a huge/slow resource.

The remote-fetch path is therefore hardened with:

- a strict host allowlist (only the legitimate Bing wallpaper host), enforced
  *before* any network call;
- an https-only scheme check (rejects ``file://``, ``gopher://``, plain http,
  etc.);
- literal private/loopback/link-local/reserved IP blocking without DNS;
- redirect suppression (a no-redirect opener) plus final-URL re-validation so an
  allowlisted host cannot bounce the fetch to an internal address;
- a hard response-size cap and a connect/read timeout to bound DoS exposure.

The allowlist, timeout, and size cap are module constants and are also
injectable through the constructor so they can be exercised in tests.
"""
import hashlib
import ipaddress
import re
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener, urlopen, HTTPRedirectHandler


# Only these hosts may be fetched by the wallpaper image proxy. This is the
# centralized allowlist that the (previously inline) Bing check implied.
WALLPAPER_ALLOWED_HOSTS = frozenset({"www.bing.com"})
# The wallpaper source is https-only; rejecting everything else also rejects
# non-http(s) schemes such as file://, gopher://, ftp://.
WALLPAPER_ALLOWED_SCHEMES = frozenset({"https"})
# Connect/read timeout (seconds) applied to the upstream fetch.
WALLPAPER_FETCH_TIMEOUT = 30
# Never buffer more than this from the upstream response (8 MiB).
WALLPAPER_MAX_BYTES = 8 * 1024 * 1024
# Streaming read size while enforcing the response cap.
WALLPAPER_READ_CHUNK = 64 * 1024
# Hostnames that must never be fetched even if an allowlist were widened.
WALLPAPER_BLOCKED_HOST_LITERALS = frozenset({
    "localhost",
    "ip6-localhost",
    "ip6-loopback",
})


class WallpaperFetchError(Exception):
    """Raised when a remote wallpaper URL is unsafe or the fetch is aborted."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse to follow HTTP redirects.

    Returning ``None`` from ``redirect_request`` makes urllib fall through to
    ``http_error_default`` which raises the underlying ``HTTPError`` instead of
    silently following a ``3xx`` to a possibly-internal ``Location``.
    """

    def redirect_request(self, *args, **kwargs):
        return None


# Default opener used in production: no redirect following.
_WALLPAPER_OPENER = build_opener(_NoRedirectHandler)


def _default_urlopen(req, timeout=WALLPAPER_FETCH_TIMEOUT):
    return _WALLPAPER_OPENER.open(req, timeout=timeout)


def _is_blocked_literal(host):
    """True if ``host`` is a hostname/IP literal that must never be fetched.

    Blocks obvious loopback names and any literal IP that is loopback, private
    (RFC1918), link-local (incl. ``169.254.169.254`` cloud metadata),
    unspecified (``0.0.0.0``/``::``), reserved, or multicast. Non-IP hostnames
    return ``False`` here and are governed by the allowlist instead.
    """
    if not host:
        return True
    host = host.lower()
    if host in WALLPAPER_BLOCKED_HOST_LITERALS:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_multicast
    )


class WallpaperService:
    """Build Create-page wallpaper payloads and cache proxied Bing images."""

    fallback = {
        "ok": False,
        "source": "fallback",
        "url": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=2200&q=80",
        "title": "Scenic workspace",
        "copyright": "Fallback scenic background",
        "caption": "Scenic workspace",
        "errors": [],
    }

    def __init__(
        self,
        cache_dir,
        public_json_url,
        randbelow,
        urlopen_func=None,
        timeout=WALLPAPER_FETCH_TIMEOUT,
        max_bytes=WALLPAPER_MAX_BYTES,
        allowed_hosts=None,
    ):
        self.cache_dir = cache_dir
        self.public_json_url = public_json_url
        self.randbelow = randbelow
        # Default to the no-redirect opener so production fetches cannot be
        # bounced to an internal host by an upstream 3xx.
        self.urlopen = urlopen_func or _default_urlopen
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.allowed_hosts = frozenset(
            h.lower() for h in (allowed_hosts if allowed_hosts is not None else WALLPAPER_ALLOWED_HOSTS)
        )

    def fallback_payload(self, idx, error):
        payload = dict(self.fallback)
        payload["errors"] = []
        payload["idx"] = idx
        if error is not None:
            payload["errors"].append(error)
        return payload

    def payload(self, randomize=False):
        idx = self.randbelow(8) if randomize else 0
        status, payload = self.public_json_url("https://www.bing.com/HPImageArchive.aspx?format=js&idx=%d&n=1&mkt=en-US" % idx, timeout=12)
        if status >= 400 or not isinstance(payload, dict):
            return self.fallback_payload(idx, {"status": status, "response": payload})
        images = payload.get("images") if isinstance(payload.get("images"), list) else []
        item = images[0] if images and isinstance(images[0], dict) else {}
        path = str(item.get("url") or "")
        if not path:
            return self.fallback_payload(idx, "Bing wallpaper response did not include an image URL.")
        full_url = path if path.startswith("http") else "https://www.bing.com" + path
        image_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(item.get("hsh") or item.get("startdate") or hashlib.sha1(full_url.encode("utf-8")).hexdigest()))[:80]
        return {
            "ok": True,
            "source": "bing_hpimagearchive",
            "url": "/api/wallpaper/image?id=%s&remote=%s" % (quote(image_id), quote(full_url, safe="")),
            "remote_url": full_url,
            "title": item.get("title") or "Daily scenic wallpaper",
            "copyright": item.get("copyright") or "",
            "copyrightlink": item.get("copyrightlink") or "",
            "caption": item.get("copyright") or item.get("title") or "Daily scenic wallpaper",
            "startdate": item.get("startdate") or "",
            "idx": idx,
            "errors": [],
        }

    def is_allowed_remote_url(self, remote_url):
        """Return True if ``remote_url`` may be fetched by the image proxy."""
        try:
            self._validate_remote_url(remote_url)
        except WallpaperFetchError:
            return False
        return True

    def _validate_remote_url(self, remote_url):
        """Validate scheme/host of a remote wallpaper URL, raising on rejection.

        Runs before any network call and again on the post-fetch final URL.
        """
        parsed = urlparse(remote_url or "")
        scheme = (parsed.scheme or "").lower()
        if scheme not in WALLPAPER_ALLOWED_SCHEMES:
            raise WallpaperFetchError("wallpaper scheme not allowed: %r" % scheme)
        host = (parsed.hostname or "").lower()
        if not host:
            raise WallpaperFetchError("wallpaper URL is missing a host")
        if _is_blocked_literal(host):
            raise WallpaperFetchError("wallpaper host resolves to a blocked address: %r" % host)
        if host not in self.allowed_hosts:
            raise WallpaperFetchError("wallpaper host not allowlisted: %r" % host)
        return parsed

    def _final_url(self, resp, fallback):
        getter = getattr(resp, "geturl", None)
        if callable(getter):
            try:
                final = getter()
            except Exception:
                final = None
            if final:
                return final
        return fallback

    def _content_length(self, resp):
        headers = getattr(resp, "headers", None)
        if headers is None:
            return None
        try:
            value = headers.get("Content-Length")
        except Exception:
            return None
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _read_capped(self, resp):
        """Read the response body, aborting past ``self.max_bytes``."""
        declared = self._content_length(resp)
        if declared is not None and declared > self.max_bytes:
            raise WallpaperFetchError(
                "wallpaper response too large: %d bytes (cap %d)" % (declared, self.max_bytes)
            )
        chunks = []
        total = 0
        while True:
            chunk = resp.read(WALLPAPER_READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_bytes:
                raise WallpaperFetchError(
                    "wallpaper response exceeded %d bytes" % self.max_bytes
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _fetch(self, remote_url):
        req = Request(remote_url, headers={"user-agent": "matts-console/1.0"}, method="GET")
        try:
            with self.urlopen(req, timeout=self.timeout) as resp:
                # Re-validate the URL actually served. A no-redirect opener
                # normally makes this a no-op, but this also refuses any
                # injected/misbehaving opener that followed a 3xx to an
                # internal host.
                self._validate_remote_url(self._final_url(resp, remote_url))
                return self._read_capped(resp)
        except WallpaperFetchError:
            raise
        except OSError as exc:
            # Covers URLError/HTTPError (redirects refused by the opener),
            # socket timeouts, and connection failures.
            raise WallpaperFetchError("wallpaper upstream fetch failed: %s" % exc) from exc

    def image_response(self, remote_url, image_id):
        try:
            self._validate_remote_url(remote_url)
        except WallpaperFetchError:
            return HTTPStatus.BAD_REQUEST, b"", "text/plain"
        cache_dir = self.cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(urlparse(remote_url).path).suffix or ".jpg"
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", image_id or hashlib.sha1(remote_url.encode("utf-8")).hexdigest())[:80]
        path = cache_dir / (safe_id + suffix)
        if not path.exists():
            try:
                data = self._fetch(remote_url)
            except WallpaperFetchError:
                return HTTPStatus.BAD_GATEWAY, b"", "text/plain"
            path.write_bytes(data)
        return HTTPStatus.OK, path.read_bytes(), "image/jpeg"
