"""Authentication helpers for the console HTTP handler."""
import secrets
from urllib.parse import parse_qs, urlparse


class AuthHandler:
    """Parse console auth tokens and evaluate request authorization."""

    def __init__(self, auth_enabled, auth_token):
        self.auth_enabled = auth_enabled
        self.auth_token = auth_token

    def request_token(self, path, headers):
        parsed = urlparse(path)
        query_token = (parse_qs(parsed.query).get("token") or [""])[0]
        if query_token:
            return query_token
        header_token = headers.get("x-matts-console-token", "").strip()
        if header_token:
            return header_token
        auth = headers.get("authorization", "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def authorized(self, path, headers):
        return not self.auth_enabled() or secrets.compare_digest(self.request_token(path, headers), self.auth_token())
