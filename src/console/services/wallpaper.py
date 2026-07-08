"""Wallpaper metadata and cached image response helpers."""
import hashlib
import re
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


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

    def __init__(self, cache_dir, public_json_url, randbelow, urlopen_func=None):
        self.cache_dir = cache_dir
        self.public_json_url = public_json_url
        self.randbelow = randbelow
        self.urlopen = urlopen_func or urlopen

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

    def image_response(self, remote_url, image_id):
        if not remote_url.startswith("https://www.bing.com/"):
            return HTTPStatus.BAD_REQUEST, b"", "text/plain"
        cache_dir = self.cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(urlparse(remote_url).path).suffix or ".jpg"
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", image_id or hashlib.sha1(remote_url.encode("utf-8")).hexdigest())[:80]
        path = cache_dir / (safe_id + suffix)
        if not path.exists():
            req = Request(remote_url, headers={"user-agent": "matts-console/1.0"}, method="GET")
            with self.urlopen(req, timeout=30) as resp:
                path.write_bytes(resp.read())
        return HTTPStatus.OK, path.read_bytes(), "image/jpeg"
