"""JWT-style console session tokens using only the Python standard library."""
import base64
import hashlib
import hmac
import json
import secrets
import time


def b64url_encode(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


class AuthSessionService:
    """Issue, verify, refresh, and revoke signed console sessions."""

    def __init__(self, session_file, secret, clock=None, token_urlsafe=None, access_ttl=3600, refresh_ttl=604800):
        self.session_file = session_file
        self.secret = secret
        self.clock = clock or time.time
        self.token_urlsafe = token_urlsafe or secrets.token_urlsafe
        self.access_ttl = int(access_ttl or 3600)
        self.refresh_ttl = int(refresh_ttl or 604800)

    def read_state(self):
        try:
            data = json.loads(self.session_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        sessions = data.get("sessions") if isinstance(data, dict) else {}
        return {"sessions": sessions if isinstance(sessions, dict) else {}}

    def write_state(self, state):
        path = self.session_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(0o600)

    def signing_key(self):
        raw = str(self.secret() or "").encode("utf-8")
        return hashlib.sha256(raw).digest()

    def sign(self, payload):
        header = {"alg": "HS256", "typ": "JWT"}
        first = b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        second = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        body = (first + "." + second).encode("ascii")
        signature = hmac.new(self.signing_key(), body, hashlib.sha256).digest()
        return first + "." + second + "." + b64url_encode(signature)

    def verify_token(self, token, token_type):
        parts = str(token or "").split(".")
        if len(parts) != 3:
            return None
        body = (parts[0] + "." + parts[1]).encode("ascii")
        expected = b64url_encode(hmac.new(self.signing_key(), body, hashlib.sha256).digest())
        if not hmac.compare_digest(parts[2], expected):
            return None
        try:
            payload = json.loads(b64url_decode(parts[1]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if payload.get("typ") != token_type:
            return None
        if float(payload.get("exp") or 0) <= self.clock():
            return None
        return payload

    def create_session(self, identity):
        now = int(self.clock())
        session_id = self.token_urlsafe(18)
        refresh_jti = self.token_urlsafe(18)
        identity = {
            "id": (identity or {}).get("id") or "unknown",
            "roles": list((identity or {}).get("roles") or []),
            "permissions": list((identity or {}).get("permissions") or []),
            "source": (identity or {}).get("source") or "unknown",
        }
        state = self.read_state()
        state["sessions"][session_id] = {
            "identity": identity,
            "created_at": now,
            "updated_at": now,
            "access_expires_at": now + self.access_ttl,
            "refresh_expires_at": now + self.refresh_ttl,
            "refresh_jti": refresh_jti,
            "revoked": False,
        }
        self.write_state(state)
        return self.session_payload(session_id, state["sessions"][session_id])

    def session_payload(self, session_id, record):
        now = int(self.clock())
        identity = dict(record.get("identity") or {})
        access_exp = now + self.access_ttl
        refresh_exp = int(record.get("refresh_expires_at") or (now + self.refresh_ttl))
        access = self.sign({
            "typ": "access",
            "sid": session_id,
            "sub": identity.get("id"),
            "roles": identity.get("roles") or [],
            "permissions": identity.get("permissions") or [],
            "iat": now,
            "exp": access_exp,
        })
        refresh = self.sign({
            "typ": "refresh",
            "sid": session_id,
            "jti": record.get("refresh_jti"),
            "sub": identity.get("id"),
            "iat": now,
            "exp": refresh_exp,
        })
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "session_id": session_id,
            "expires_in": self.access_ttl,
            "refresh_expires_at": refresh_exp,
            "identity": identity,
        }

    def verify_access(self, token):
        payload = self.verify_token(token, "access")
        if not payload:
            return None
        state = self.read_state()
        record = state["sessions"].get(payload.get("sid"))
        if not record or record.get("revoked"):
            return None
        identity = dict(record.get("identity") or {})
        identity["source"] = "jwt-session"
        identity["session_id"] = payload.get("sid")
        identity["permissions"] = list(payload.get("permissions") or identity.get("permissions") or [])
        identity["roles"] = list(payload.get("roles") or identity.get("roles") or [])
        return identity

    def refresh(self, refresh_token):
        payload = self.verify_token(refresh_token, "refresh")
        if not payload:
            return 401, {"error": "refresh token is invalid or expired", "code": "invalid_refresh_token"}
        state = self.read_state()
        record = state["sessions"].get(payload.get("sid"))
        if not record or record.get("revoked") or record.get("refresh_jti") != payload.get("jti"):
            return 401, {"error": "refresh token is invalid or expired", "code": "invalid_refresh_token"}
        now = int(self.clock())
        record["updated_at"] = now
        record["access_expires_at"] = now + self.access_ttl
        record["refresh_expires_at"] = now + self.refresh_ttl
        record["refresh_jti"] = self.token_urlsafe(18)
        self.write_state(state)
        return 200, self.session_payload(payload.get("sid"), record)

    def revoke(self, session_id):
        state = self.read_state()
        record = state["sessions"].get(session_id)
        if not record:
            return False
        record["revoked"] = True
        record["updated_at"] = int(self.clock())
        self.write_state(state)
        return True

    def active_sessions(self):
        now = self.clock()
        rows = []
        for session_id, record in self.read_state()["sessions"].items():
            if record.get("revoked") or float(record.get("refresh_expires_at") or 0) <= now:
                continue
            identity = record.get("identity") or {}
            rows.append({
                "session_id": session_id,
                "actor": identity.get("id"),
                "roles": identity.get("roles") or [],
                "created_at": record.get("created_at"),
                "updated_at": record.get("updated_at"),
                "access_expires_at": record.get("access_expires_at"),
                "refresh_expires_at": record.get("refresh_expires_at"),
            })
        return rows
