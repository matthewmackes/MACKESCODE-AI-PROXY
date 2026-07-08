import io
import json
import unittest
from urllib.error import HTTPError, URLError

from src.console.services.http_json import JsonHttpService


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else b"{}"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class JsonHttpServiceTests(unittest.TestCase):
    def test_request_json_posts_payload_and_decodes_response(self):
        seen = {}

        def urlopen_func(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["data"] = req.data
            seen["timeout"] = timeout
            return FakeResponse(201, b'{"ok": true}')

        service = JsonHttpService(urlopen_func=urlopen_func)
        status, payload = service.request_json("http://proxy.local/v1/messages", {"hello": "world"}, timeout=9, method="PUT")

        self.assertEqual(status, 201)
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(seen["url"], "http://proxy.local/v1/messages")
        self.assertEqual(seen["method"], "PUT")
        self.assertEqual(json.loads(seen["data"].decode("utf-8")), {"hello": "world"})
        self.assertEqual(seen["timeout"], 9)

    def test_request_json_shapes_http_and_url_errors(self):
        service = JsonHttpService(urlopen_func=lambda req, timeout=0: (_ for _ in ()).throw(
            HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b'{"error":"no"}'))
        ))
        status, payload = service.request_json("http://proxy.local")

        offline = JsonHttpService(urlopen_func=lambda req, timeout=0: (_ for _ in ()).throw(URLError("offline")))
        offline_status, offline_payload = offline.request_json("http://proxy.local")

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "no"})
        self.assertEqual(offline_status, 502)
        self.assertEqual(offline_payload["error"]["message"], "offline")

    def test_do_get_adds_query_and_bearer_token(self):
        seen = {}

        def urlopen_func(req, timeout=0):
            seen["url"] = req.full_url
            seen["method"] = req.get_method()
            seen["auth"] = req.headers.get("Authorization")
            return FakeResponse(200, b'{"items": []}')

        service = JsonHttpService(urlopen_func=urlopen_func)
        status, payload = service.do_get("/v2/test", "tok", {"page": 1, "per_page": 100})

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"items": []})
        self.assertEqual(seen["method"], "GET")
        self.assertEqual(seen["auth"], "Bearer tok")
        self.assertIn("page=1", seen["url"])
        self.assertIn("per_page=100", seen["url"])

    def test_do_request_handles_empty_success_and_plain_error_body(self):
        service = JsonHttpService(urlopen_func=lambda req, timeout=0: FakeResponse(204, b""))
        status, payload = service.do_request("/v2/delete", "tok", method="DELETE")

        error_service = JsonHttpService(urlopen_func=lambda req, timeout=0: (_ for _ in ()).throw(
            HTTPError(req.full_url, 500, "server error", {}, io.BytesIO(b"plain"))
        ))
        error_status, error_payload = error_service.do_request("/v2/delete", "tok")

        self.assertEqual(status, 204)
        self.assertEqual(payload, {})
        self.assertEqual(error_status, 500)
        self.assertEqual(error_payload, {"error": "plain"})

    def test_public_json_url_uses_public_headers_and_reports_errors(self):
        seen = {}

        def urlopen_func(req, timeout=0):
            seen["accept"] = req.headers.get("Accept")
            seen["agent"] = req.headers.get("User-agent")
            return FakeResponse(200, b'{"status": "ok"}')

        service = JsonHttpService(urlopen_func=urlopen_func)
        status, payload = service.public_json_url("https://status.local")

        offline = JsonHttpService(urlopen_func=lambda req, timeout=0: (_ for _ in ()).throw(URLError("offline")))
        offline_status, offline_payload = offline.public_json_url("https://status.local")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})
        self.assertEqual(seen["accept"], "application/json")
        self.assertEqual(seen["agent"], "matts-console/1.0")
        self.assertEqual(offline_status, 502)
        self.assertEqual(offline_payload, {"error": "offline"})


if __name__ == "__main__":
    unittest.main()
