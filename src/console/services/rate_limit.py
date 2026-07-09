"""In-memory API rate limiting for the console."""
from collections import defaultdict, deque
import time


class RateLimitService:
    """Fixed-window request limiter keyed by token/actor and endpoint."""

    def __init__(self, config, clock=None):
        self.config = config or {}
        self.clock = clock or time.time
        self.buckets = defaultdict(deque)

    def enabled(self):
        return bool(self.config.get("enabled", False))

    def window_seconds(self):
        try:
            return max(1, int(self.config.get("window_seconds", 60)))
        except (TypeError, ValueError):
            return 60

    def rule_for(self, method, path):
        paths = self.config.get("paths") if isinstance(self.config.get("paths"), dict) else {}
        if isinstance(paths.get(path), dict):
            return paths[path]
        method = str(method or "").upper()
        key = "write_limit" if method in {"POST", "PUT", "PATCH", "DELETE"} else "default_limit"
        try:
            limit = int(self.config.get(key, self.config.get("default_limit", 300)))
        except (TypeError, ValueError):
            limit = 300
        return {"limit": max(1, limit)}

    def check(self, key, method, path):
        if not self.enabled():
            return {"allowed": True, "headers": {}, "limit": 0, "remaining": 0, "reset": 0, "retry_after": 0}
        rule = self.rule_for(method, path)
        window = self.window_seconds()
        try:
            limit = max(1, int(rule.get("limit", 300)))
        except (TypeError, ValueError):
            limit = 300
        now = float(self.clock())
        bucket_key = "%s:%s:%s" % (key or "anonymous", str(method or "GET").upper(), path)
        bucket = self.buckets[bucket_key]
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        allowed = len(bucket) < limit
        if allowed:
            bucket.append(now)
        oldest = bucket[0] if bucket else now
        reset = int(oldest + window)
        remaining = max(0, limit - len(bucket))
        retry_after = 0 if allowed else max(1, int(reset - now))
        headers = {
            "x-ratelimit-limit": str(limit),
            "x-ratelimit-remaining": str(remaining),
            "x-ratelimit-reset": str(reset),
        }
        if not allowed:
            headers["retry-after"] = str(retry_after)
        return {
            "allowed": allowed,
            "headers": headers,
            "limit": limit,
            "remaining": remaining,
            "reset": reset,
            "retry_after": retry_after,
        }
