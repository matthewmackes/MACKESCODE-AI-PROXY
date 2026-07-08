import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path

from src.console.services.wallpaper import WallpaperService


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.data


class WallpaperServiceTests(unittest.TestCase):
    def service(self, tmp, public_json=None, randbelow=None, urlopen_func=None):
        return WallpaperService(
            cache_dir=lambda: Path(tmp),
            public_json_url=public_json or (lambda url, timeout=12: (200, {"images": []})),
            randbelow=randbelow or (lambda limit: 3),
            urlopen_func=urlopen_func,
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


if __name__ == "__main__":
    unittest.main()
