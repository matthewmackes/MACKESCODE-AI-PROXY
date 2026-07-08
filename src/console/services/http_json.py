"""Shared JSON HTTP helpers for proxy and DigitalOcean API calls."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class JsonHttpService:
    """Owns JSON request/response handling and consistent network errors."""

    def __init__(self, urlopen_func=None, do_base_url="https://api.digitalocean.com"):
        self.urlopen = urlopen_func or urlopen
        self.do_base_url = do_base_url.rstrip("/")

    def request_json(self, url, payload=None, timeout=240, method="POST"):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers={"content-type": "application/json"}, method=method)
        try:
            with self.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body)
            except ValueError:
                detail = {"error": {"message": "provider request failed"}}
            return exc.code, detail
        except URLError as exc:
            return 502, {"error": {"message": str(exc.reason)}}

    def do_get(self, path, token, query=None, timeout=30):
        url = self.do_base_url + path
        if query:
            url += "?" + urlencode(query)
        req = Request(url, headers={
            "content-type": "application/json",
            "authorization": "Bearer " + token,
        }, method="GET")
        try:
            with self.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body)
            except ValueError:
                detail = {"error": body or exc.reason}
            return exc.code, detail
        except URLError as exc:
            return 502, {"error": str(exc.reason)}

    def do_request(self, path, token, payload=None, timeout=60, method="GET"):
        url = self.do_base_url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers={
            "content-type": "application/json",
            "authorization": "Bearer " + token,
        }, method=method)
        try:
            with self.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, json.loads(body) if body else {}
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body)
            except ValueError:
                detail = {"error": body or exc.reason}
            return exc.code, detail
        except URLError as exc:
            return 502, {"error": str(exc.reason)}

    def public_json_url(self, url, timeout=12):
        req = Request(url, headers={"accept": "application/json", "user-agent": "matts-console/1.0"}, method="GET")
        try:
            with self.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(body)
            except ValueError:
                detail = {"error": exc.reason}
            return exc.code, detail
        except URLError as exc:
            return 502, {"error": str(exc.reason)}
