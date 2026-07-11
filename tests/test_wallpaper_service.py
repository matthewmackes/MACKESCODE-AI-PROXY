import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services import wallpaper as wallpaper_module
from src.console.services.wallpaper import WallpaperService


class FakeResponse:
    """Minimal file-like response.

    ``read`` accepts a size argument (like ``http.client.HTTPResponse``) and
    returns the payload exactly once so the capped/streaming reader terminates.
    """

    def __init__(self, data, final_url=None, headers=None):
        self.data = data
        self._sent = False
        self._final_url = final_url
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        if self._sent:
            return b""
        self._sent = True
        return self.data

    def geturl(self):
        return self._final_url


class ChunkedResponse:
    """Response that yields a sequence of chunks to exercise the size cap."""

    def __init__(self, chunks, final_url=None, headers=None):
        self._chunks = list(chunks)
        self._final_url = final_url
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def geturl(self):
        return self._final_url


class WallpaperServiceTests(unittest.TestCase):
    def service(self, tmp, public_json=None, randbelow=None, urlopen_func=None, max_bytes=None):
        kwargs = {}
        if max_bytes is not None:
            kwargs["max_bytes"] = max_bytes
        return WallpaperService(
            cache_dir=lambda: Path(tmp),
            public_json_url=public_json or (lambda url, timeout=12: (200, {"images": []})),
            randbelow=randbelow or (lambda limit: 3),
            urlopen_func=urlopen_func,
            **kwargs,
        )

    def test_payload_builds_same_origin_proxy_url_from_bing_response(self):
        def public_json(url, timeout=12):
            self.assertIn("idx=3", url)
            return 200, {"images": [{
                "url": "/th?id=OHR.Test_EN-US123.jpg",
                "hsh": "abc/123",
                "title": "Mountain",
                "copyright": "Mountain credit",
                "copyrightlink": "https://example.com",
                "startdate": "20260708",
            }]}

        with tempfile.TemporaryDirectory() as tmp:
            payload = self.service(tmp, public_json=public_json).payload(randomize=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], "bing_hpimagearchive")
        self.assertEqual(payload["remote_url"], "https://www.bing.com/th?id=OHR.Test_EN-US123.jpg")
        self.assertIn("/api/wallpaper/image?id=abc-123", payload["url"])
        self.assertEqual(payload["caption"], "Mountain credit")

    def test_payload_falls_back_when_bing_metadata_is_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, public_json=lambda url, timeout=12: (502, {"error": "down"}))
            payload = service.payload(randomize=False)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["source"], "fallback")
        self.assertEqual(payload["idx"], 0)
        self.assertEqual(payload["errors"], [{"status": 502, "response": {"error": "down"}}])

    def test_image_response_rejects_non_bing_remote_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, data, content_type = self.service(tmp).image_response("https://example.com/a.jpg", "a")

        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(data, b"")
        self.assertEqual(content_type, "text/plain")

    def test_image_response_downloads_and_reuses_cache(self):
        calls = []

        def urlopen_func(req, timeout=30):
            calls.append(req.full_url)
            return FakeResponse(b"jpg-bytes")

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, urlopen_func=urlopen_func)
            first = service.image_response("https://www.bing.com/th?id=OHR.Test.jpg", "test image")
            second = service.image_response("https://www.bing.com/th?id=OHR.Test.jpg", "test image")

        self.assertEqual(first, (HTTPStatus.OK, b"jpg-bytes", "image/jpeg"))
        self.assertEqual(second, (HTTPStatus.OK, b"jpg-bytes", "image/jpeg"))
        self.assertEqual(calls, ["https://www.bing.com/th?id=OHR.Test.jpg"])

    # --- SSRF/DoS hardening (finding PR-1.6) ---------------------------------

    def test_image_response_rejects_metadata_and_rfc1918_before_fetch(self):
        """(c) loopback / link-local metadata / RFC1918 URLs never hit the network."""
        calls = []

        def urlopen_func(req, timeout=30):
            calls.append(req.full_url)
            return FakeResponse(b"should-not-happen")

        blocked = [
            "https://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
            "https://127.0.0.1/th?id=x.jpg",               # loopback
            "https://localhost/th?id=x.jpg",               # loopback name
            "https://10.0.0.5/th?id=x.jpg",                # RFC1918
            "https://192.168.1.10/th?id=x.jpg",            # RFC1918
            "https://0.0.0.0/th?id=x.jpg",                 # unspecified
            "http://www.bing.com/th?id=x.jpg",             # non-https scheme
            "file:///etc/passwd",                          # non-http(s) scheme
        ]
        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, urlopen_func=urlopen_func)
            for url in blocked:
                status, data, content_type = service.image_response(url, "x")
                self.assertEqual(status, HTTPStatus.BAD_REQUEST, url)
                self.assertEqual(data, b"")

        self.assertEqual(calls, [], "no blocked URL should have reached the network")

    def test_image_response_refuses_redirect_to_internal_host(self):
        """(a) an allowlisted request whose final URL is internal is refused."""
        def urlopen_func(req, timeout=30):
            # Simulates an opener that followed a 3xx from bing to metadata.
            return FakeResponse(b"secret", final_url="http://169.254.169.254/latest/meta-data/")

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, urlopen_func=urlopen_func)
            status, data, content_type = service.image_response(
                "https://www.bing.com/th?id=OHR.Test.jpg", "redir"
            )
            self.assertEqual(status, HTTPStatus.BAD_GATEWAY)
            self.assertEqual(data, b"")
            # The refused (internal) body must not be written to the cache.
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [])

    def test_image_response_aborts_oversized_streamed_response(self):
        """(b) a body larger than the cap is aborted mid-stream."""
        def urlopen_func(req, timeout=30):
            return ChunkedResponse([b"x" * 32, b"x" * 32], final_url=None)

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, urlopen_func=urlopen_func, max_bytes=16)
            status, data, content_type = service.image_response(
                "https://www.bing.com/th?id=OHR.Big.jpg", "big"
            )
            self.assertEqual(status, HTTPStatus.BAD_GATEWAY)
            self.assertEqual(data, b"")
            # Oversized fetch must not leave a cached file behind.
            self.assertEqual([p.name for p in Path(tmp).iterdir()], [])

    def test_image_response_aborts_on_oversized_content_length_header(self):
        """A too-large declared Content-Length is rejected before buffering."""
        def urlopen_func(req, timeout=30):
            return FakeResponse(b"x", headers={"Content-Length": str(64)})

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, urlopen_func=urlopen_func, max_bytes=16)
            status, data, content_type = service.image_response(
                "https://www.bing.com/th?id=OHR.Big.jpg", "big-header"
            )

        self.assertEqual(status, HTTPStatus.BAD_GATEWAY)
        self.assertEqual(data, b"")

    def test_image_response_allows_legitimate_bing_host(self):
        """(d) the allowlisted host still works (mocked fetch)."""
        def urlopen_func(req, timeout=30):
            return FakeResponse(b"jpg", final_url="https://www.bing.com/th?id=OHR.Ok.jpg")

        with tempfile.TemporaryDirectory() as tmp:
            service = self.service(tmp, urlopen_func=urlopen_func)
            status, data, content_type = service.image_response(
                "https://www.bing.com/th?id=OHR.Ok.jpg", "ok"
            )

        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(data, b"jpg")
        self.assertEqual(content_type, "image/jpeg")

    def test_is_blocked_literal_flags_internal_addresses(self):
        blocked = [
            "127.0.0.1", "169.254.169.254", "10.0.0.1", "172.16.5.4",
            "192.168.1.1", "0.0.0.0", "::1", "localhost", "",
        ]
        for host in blocked:
            self.assertTrue(wallpaper_module._is_blocked_literal(host), host)

        allowed = ["www.bing.com", "example.com", "8.8.8.8"]
        for host in allowed:
            self.assertFalse(wallpaper_module._is_blocked_literal(host), host)

    def test_default_opener_does_not_follow_redirects(self):
        opener = wallpaper_module._WALLPAPER_OPENER
        self.assertTrue(
            any(isinstance(h, wallpaper_module._NoRedirectHandler) for h in opener.handlers),
            "production opener must carry the no-redirect handler",
        )
        # The no-redirect handler suppresses redirect following.
        self.assertIsNone(
            wallpaper_module._NoRedirectHandler().redirect_request(
                None, None, 302, "Found", {}, "http://169.254.169.254/"
            )
        )


if __name__ == "__main__":
    unittest.main()
