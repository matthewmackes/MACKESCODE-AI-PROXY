"""Typed runtime state repositories."""
from src.console.services.operational_store import OperationalStore
from src.console.store.base import RuntimeStateRepository


class _OperationalJsonlRepository(RuntimeStateRepository):
    operational_kind = ""

    def __init__(self, *args, operational_store=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.operational_store = operational_store if operational_store is not None else OperationalStore(clock=self.clock)

    def _backfill(self):
        try:
            return self.operational_store.backfill_jsonl(self.operational_kind, self.file_path())
        except Exception:
            return None

    def _append_operational(self, record):
        try:
            self.operational_store.upsert_record(self.operational_kind, record, source_path=str(self.file_path()))
        except Exception:
            pass

    def _read_operational(self, limit=200, filters=None):
        try:
            self._backfill()
            filters = dict(filters or {})
            filters.setdefault("source_path", str(self.file_path()))
            rows = self.operational_store.read_records(self.operational_kind, limit=limit, filters=filters)
            if rows:
                return rows
        except Exception:
            pass
        return []


class TraceRepository(_OperationalJsonlRepository):
    operational_kind = "traces"

    def __init__(self, path, clock=None, operational_store=None):
        super().__init__(
            path,
            "traces",
            schema_version=1,
            retention={"default_limit": 200, "format": "jsonl"},
            redacted_keys={"authorization", "token", "api_key", "access_key", "secret", "messages", "prompt", "response", "raw"},
            clock=clock,
            operational_store=operational_store,
        )

    def append(self, record):
        clean = self.append_jsonl(record)
        self._append_operational(clean)
        return clean

    def read(self, limit=200, filters=None):
        rows = self._read_operational(limit=limit, filters=filters)
        return rows if rows else self.read_jsonl(limit=limit, reverse=True, malformed="skip")


class AuditRepository(_OperationalJsonlRepository):
    operational_kind = "audit"

    def __init__(self, path, clock=None, operational_store=None):
        super().__init__(
            path,
            "audit",
            schema_version=1,
            retention={"default_limit": 5000, "format": "jsonl"},
            redacted_keys={"authorization", "token", "api_key", "access_key", "secret", "password"},
            clock=clock,
            operational_store=operational_store,
        )

    def append(self, record):
        clean = self.append_jsonl(record)
        self._append_operational(clean)
        return clean

    def read(self, limit=5000, filters=None):
        rows = self._read_operational(limit=limit, filters=filters)
        return rows if rows else self.read_jsonl(limit=limit, reverse=True, malformed="skip")
