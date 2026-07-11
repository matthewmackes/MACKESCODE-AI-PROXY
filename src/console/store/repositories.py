"""Typed runtime state repositories."""
from src.console.store.base import RuntimeStateRepository


class TraceRepository(RuntimeStateRepository):
    def __init__(self, path, clock=None):
        super().__init__(
            path,
            "traces",
            schema_version=1,
            retention={"default_limit": 200, "format": "jsonl"},
            redacted_keys={"authorization", "token", "api_key", "access_key", "secret", "messages", "prompt", "response", "raw"},
            clock=clock,
        )

    def append(self, record):
        return self.append_jsonl(record)

    def read(self, limit=200):
        return self.read_jsonl(limit=limit, reverse=True, malformed="skip")


class AuditRepository(RuntimeStateRepository):
    def __init__(self, path, clock=None):
        super().__init__(
            path,
            "audit",
            schema_version=1,
            retention={"default_limit": 5000, "format": "jsonl"},
            redacted_keys={"authorization", "token", "api_key", "access_key", "secret", "password"},
            clock=clock,
        )

    def append(self, record):
        return self.append_jsonl(record)

    def read(self, limit=5000):
        return self.read_jsonl(limit=limit, reverse=True, malformed="skip")
