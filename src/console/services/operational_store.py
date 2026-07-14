"""Unified SQLite operational store for runtime telemetry and registry state."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_OPERATIONAL_DB = Path.home() / ".cache" / "matts-value-set" / "studio" / "operational.sqlite3"


def operational_db_path(env: dict[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    if source.get("MATTS_OPERATIONAL_DB"):
        return Path(source["MATTS_OPERATIONAL_DB"]).expanduser()
    studio_dir = Path(source.get("MATTS_STUDIO_DIR") or DEFAULT_OPERATIONAL_DB.parent).expanduser()
    return studio_dir / DEFAULT_OPERATIONAL_DB.name


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


class OperationalStore:
    """One SQLite file for runtime records, model registry, and analyst state."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None, clock: Callable[[], float] | None = None) -> None:
        self.db_path = Path(db_path or operational_db_path())
        self.clock = clock or time.time

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self.migrate(conn)
        return conn

    def migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_records (
              kind TEXT NOT NULL,
              record_id TEXT NOT NULL,
              ts REAL NOT NULL DEFAULT 0,
              payload_json TEXT NOT NULL,
              source_path TEXT NOT NULL DEFAULT '',
              source_offset INTEGER NOT NULL DEFAULT 0,
              created_at REAL NOT NULL,
              PRIMARY KEY (kind, record_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_operational_records_kind_ts ON operational_records(kind, ts DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_operational_records_source ON operational_records(kind, source_path)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS operational_sources (
              kind TEXT NOT NULL,
              source_path TEXT NOT NULL,
              source_mtime_ns INTEGER NOT NULL DEFAULT 0,
              source_size INTEGER NOT NULL DEFAULT 0,
              row_count INTEGER NOT NULL DEFAULT 0,
              synced_at REAL NOT NULL,
              PRIMARY KEY (kind, source_path)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_state (
              state_key TEXT PRIMARY KEY,
              payload_json TEXT NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_registry (
              model_id TEXT PRIMARY KEY,
              enabled INTEGER NOT NULL DEFAULT 0,
              model_type TEXT NOT NULL DEFAULT 'unknown',
              route_enabled INTEGER NOT NULL DEFAULT 0,
              sort_order INTEGER NOT NULL DEFAULT 0,
              payload_json TEXT NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(model_registry)").fetchall()}
        if "sort_order" not in columns:
            conn.execute("ALTER TABLE model_registry ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_model_registry_route ON model_registry(route_enabled, model_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_model_registry_order ON model_registry(sort_order, model_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS digitalocean_snapshots (
              snapshot_id TEXT PRIMARY KEY,
              created_at REAL NOT NULL,
              source TEXT NOT NULL DEFAULT 'digitalocean',
              payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_do_snapshots_created ON digitalocean_snapshots(created_at DESC)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyst_runs (
              run_id TEXT PRIMARY KEY,
              created_at REAL NOT NULL,
              status TEXT NOT NULL,
              fingerprint TEXT NOT NULL,
              model_id TEXT NOT NULL DEFAULT '',
              proxy_grade TEXT NOT NULL DEFAULT '',
              severity_counts_json TEXT NOT NULL DEFAULT '{}',
              payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyst_runs_created ON analyst_runs(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyst_runs_fingerprint ON analyst_runs(fingerprint)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyst_findings (
              finding_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              severity TEXT NOT NULL,
              lifecycle_status TEXT NOT NULL DEFAULT 'new',
              title TEXT NOT NULL,
              fingerprint TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              first_seen_at REAL NOT NULL,
              last_seen_at REAL NOT NULL,
              acknowledged_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyst_findings_run ON analyst_findings(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyst_findings_fingerprint ON analyst_findings(fingerprint)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_analyst_findings_status ON analyst_findings(lifecycle_status, severity)")
        conn.commit()

    def _record_id(self, kind: str, record: dict[str, Any]) -> str:
        for key in ("trace_id", "id", "event_id", "request_id"):
            value = str(record.get(key) or "").strip()
            if value:
                return value
        ts = str(record.get("timestamp") or record.get("ts") or record.get("created_at") or "")
        digest = hashlib.sha256(("%s|%s|%s" % (kind, ts, _json_dumps(record))).encode("utf-8")).hexdigest()
        return digest[:32]

    def _jsonl_record_id(self, kind: str, record: dict[str, Any], source_path: Path, source_offset: int) -> str:
        for key in ("trace_id", "id", "event_id", "request_id"):
            value = str(record.get(key) or "").strip()
            if value:
                return value
        digest = hashlib.sha256(
            ("%s|%s|%s|%s" % (kind, source_path, source_offset, _json_dumps(record))).encode("utf-8")
        ).hexdigest()
        return digest[:32]

    def _record_ts(self, record: dict[str, Any]) -> float:
        for key in ("timestamp", "ts", "created_at", "generated_at", "checked_at"):
            try:
                value = float(record.get(key))
            except (TypeError, ValueError, AttributeError):
                continue
            if value:
                return value
        return float(self.clock())

    def upsert_record(self, kind: str, record: dict[str, Any], source_path: str = "", source_offset: int = 0) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("operational record must be a dictionary")
        now = float(self.clock())
        record_id = self._record_id(kind, record)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO operational_records (kind, record_id, ts, payload_json, source_path, source_offset, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, record_id) DO UPDATE SET
                  ts=excluded.ts,
                  payload_json=excluded.payload_json,
                  source_path=excluded.source_path,
                  source_offset=excluded.source_offset
                """,
                (str(kind), record_id, self._record_ts(record), _json_dumps(record), str(source_path or ""), int(source_offset or 0), now),
            )
            conn.commit()
        return record

    def backfill_jsonl(self, kind: str, path: str | os.PathLike[str], limit: int | None = None) -> dict[str, Any]:
        source = Path(path)
        if not source.exists():
            return {"kind": kind, "source_path": str(source), "rows": 0, "inserted": 0, "exists": False}
        try:
            stat = source.stat()
        except OSError:
            return {"kind": kind, "source_path": str(source), "rows": 0, "inserted": 0, "exists": False}
        with self.connect() as conn:
            cached = conn.execute(
                "SELECT source_mtime_ns, source_size, row_count FROM operational_sources WHERE kind = ? AND source_path = ?",
                (kind, str(source)),
            ).fetchone()
            if cached and int(cached["source_mtime_ns"]) == stat.st_mtime_ns and int(cached["source_size"]) == stat.st_size:
                return {"kind": kind, "source_path": str(source), "rows": int(cached["row_count"]), "inserted": 0, "exists": True, "cached": True}
        try:
            lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        if limit:
            lines = lines[-int(limit):]
        rows = 0
        inserted = 0
        now = float(self.clock())
        with self.connect() as conn:
            conn.execute("DELETE FROM operational_records WHERE kind = ? AND source_path = ?", (kind, str(source)))
            for index, line in enumerate(lines):
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                rows += 1
                record_id = self._jsonl_record_id(kind, record, source, index)
                before = conn.total_changes
                conn.execute(
                    """
                    INSERT INTO operational_records (kind, record_id, ts, payload_json, source_path, source_offset, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(kind, record_id) DO UPDATE SET
                      ts=excluded.ts,
                      payload_json=excluded.payload_json,
                      source_path=excluded.source_path,
                      source_offset=excluded.source_offset
                    """,
                    (kind, record_id, self._record_ts(record), _json_dumps(record), str(source), index, now),
                )
                if conn.total_changes > before:
                    inserted += 1
            conn.execute(
                """
                INSERT INTO operational_sources (kind, source_path, source_mtime_ns, source_size, row_count, synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, source_path) DO UPDATE SET
                  source_mtime_ns=excluded.source_mtime_ns,
                  source_size=excluded.source_size,
                  row_count=excluded.row_count,
                  synced_at=excluded.synced_at
                """,
                (kind, str(source), stat.st_mtime_ns, stat.st_size, rows, now),
            )
            conn.commit()
        return {"kind": kind, "source_path": str(source), "rows": rows, "inserted": inserted, "exists": True}

    def read_records(self, kind: str, limit: int = 200, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        rows: list[dict[str, Any]] = []
        source_path = str(filters.get("source_path") or "")
        where = "WHERE kind = ?"
        params: list[Any] = [kind]
        if source_path:
            where += " AND source_path = ?"
            params.append(source_path)
        params.append(max(1, int(limit or 200)) * 4)
        with self.connect() as conn:
            db_rows = conn.execute(
                "SELECT payload_json FROM operational_records %s ORDER BY ts DESC, created_at DESC LIMIT ?" % where,
                tuple(params),
            ).fetchall()
        for row in db_rows:
            payload = _loads(row["payload_json"], {})
            if not isinstance(payload, dict):
                continue
            if not self._matches(payload, filters):
                continue
            rows.append(payload)
            if len(rows) >= int(limit or 200):
                break
        return rows

    def _matches(self, payload: dict[str, Any], filters: dict[str, Any]) -> bool:
        model = filters.get("model")
        if model and model not in {payload.get("requested_model"), payload.get("routed_model"), payload.get("model"), payload.get("upstream_model")}:
            return False
        status = filters.get("status")
        if status and str(payload.get("status") or payload.get("outcome") or "") != str(status):
            return False
        session = filters.get("session")
        if session and session not in {payload.get("session_id"), payload.get("chat_id"), payload.get("tmux_session")}:
            return False
        min_cost = filters.get("min_cost")
        if min_cost not in (None, ""):
            try:
                if float(payload.get("cost_usd") or 0) < float(min_cost):
                    return False
            except (TypeError, ValueError):
                return False
        return True

    def read_usage_since(self, since_ts: float, now: float | None = None) -> float:
        now = float(now if now is not None else self.clock())
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM operational_records WHERE kind = 'usage' AND ts >= ? AND ts <= ?",
                (float(since_ts), now),
            ).fetchall()
        total = 0.0
        for row in rows:
            payload = _loads(row["payload_json"], {})
            if not isinstance(payload, dict):
                continue
            cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}
            try:
                total += float(cost.get("total_cost_usd") or payload.get("cost_usd") or 0)
            except (TypeError, ValueError):
                continue
        return round(total, 8)

    def upsert_runtime_state(self, key: str, payload: Any) -> Any:
        now = float(self.clock())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO runtime_state (state_key, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (str(key), _json_dumps(payload), now),
            )
            conn.commit()
        return payload

    def get_runtime_state(self, key: str, fallback: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json FROM runtime_state WHERE state_key = ?", (str(key),)).fetchone()
        return _loads(row["payload_json"], fallback) if row else fallback

    def save_model_registry(self, models: Iterable[dict[str, Any]], route_enabled: Callable[[dict[str, Any]], bool] | None = None) -> list[dict[str, Any]]:
        now = float(self.clock())
        rows = [dict(model) for model in models if isinstance(model, dict) and str(model.get("id") or "").strip()]
        with self.connect() as conn:
            conn.execute("DELETE FROM model_registry")
            for index, model in enumerate(rows):
                conn.execute(
                    """
                    INSERT INTO model_registry (model_id, enabled, model_type, route_enabled, sort_order, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(model.get("id") or ""),
                        1 if model.get("enabled") else 0,
                        str(model.get("type") or "unknown"),
                        1 if (route_enabled(model) if route_enabled else model.get("route_enabled")) else 0,
                        index,
                        _json_dumps(model),
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO runtime_state (state_key, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                ("model_registry_exported_at", _json_dumps(now), now),
            )
            conn.commit()
        return rows

    def load_model_registry(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload_json FROM model_registry ORDER BY sort_order ASC, model_id ASC").fetchall()
        models = [_loads(row["payload_json"], {}) for row in rows]
        return [model for model in models if isinstance(model, dict)]

    def save_digitalocean_snapshot(self, payload: dict[str, Any], source: str = "digitalocean") -> dict[str, Any]:
        if not isinstance(payload, dict):
            payload = {"payload": payload}
        created_at = float(payload.get("checked_at") or payload.get("generated_at") or self.clock())
        digest = hashlib.sha256(("%s|%s|%s" % (source, created_at, _json_dumps(payload))).encode("utf-8")).hexdigest()[:24]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO digitalocean_snapshots (snapshot_id, created_at, source, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (digest, created_at, source, _json_dumps(payload)),
            )
            conn.commit()
        return payload

    def latest_digitalocean_snapshots(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM digitalocean_snapshots ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit or 20)),),
            ).fetchall()
        return [payload for payload in (_loads(row["payload_json"], {}) for row in rows) if isinstance(payload, dict)]

    def save_analyst_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("analyst run payload must be a dictionary")
        now = float(payload.get("generated_at") or self.clock())
        run_id = str(payload.get("run_id") or hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()[:24])
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        severity_counts = summary.get("severity_counts") if isinstance(summary.get("severity_counts"), dict) else {}
        findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analyst_runs (run_id, created_at, status, fingerprint, model_id, proxy_grade, severity_counts_json, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    str(payload.get("status") or "ok"),
                    str(payload.get("fingerprint") or ""),
                    str(payload.get("model_id") or ""),
                    str((payload.get("proxy") or {}).get("grade") if isinstance(payload.get("proxy"), dict) else ""),
                    _json_dumps(severity_counts),
                    _json_dumps({**payload, "run_id": run_id}),
                ),
            )
            seen: set[str] = set()
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                fingerprint = str(finding.get("fingerprint") or hashlib.sha256(_json_dumps(finding).encode("utf-8")).hexdigest()[:24])
                finding_id = str(finding.get("id") or fingerprint)
                seen.add(finding_id)
                existing = conn.execute("SELECT first_seen_at, acknowledged_at FROM analyst_findings WHERE finding_id = ?", (finding_id,)).fetchone()
                first_seen = float(existing["first_seen_at"]) if existing else now
                acknowledged_at = float(existing["acknowledged_at"]) if existing else 0.0
                lifecycle_status = "ongoing" if existing else "new"
                row = {**finding, "id": finding_id, "fingerprint": fingerprint, "lifecycle_status": lifecycle_status}
                conn.execute(
                    """
                    INSERT INTO analyst_findings (finding_id, run_id, severity, lifecycle_status, title, fingerprint, payload_json, first_seen_at, last_seen_at, acknowledged_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(finding_id) DO UPDATE SET
                      run_id=excluded.run_id,
                      severity=excluded.severity,
                      lifecycle_status=excluded.lifecycle_status,
                      title=excluded.title,
                      payload_json=excluded.payload_json,
                      last_seen_at=excluded.last_seen_at
                    """,
                    (
                        finding_id,
                        run_id,
                        str(finding.get("severity") or "low").lower(),
                        lifecycle_status,
                        str(finding.get("title") or "Finding"),
                        fingerprint,
                        _json_dumps(row),
                        first_seen,
                        now,
                        acknowledged_at,
                    ),
                )
            conn.execute(
                """
                UPDATE analyst_findings
                SET lifecycle_status = 'resolved', last_seen_at = ?
                WHERE lifecycle_status != 'resolved'
                  AND last_seen_at < ?
                  AND finding_id NOT IN (%s)
                """ % (",".join("?" for _ in seen) or "''"),
                tuple([now, now] + list(seen)),
            )
            conn.commit()
        return {**payload, "run_id": run_id}

    def latest_analyst_run(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json FROM analyst_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        payload = _loads(row["payload_json"], None) if row else None
        return payload if isinstance(payload, dict) else None

    def analyst_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload_json FROM analyst_runs ORDER BY created_at DESC LIMIT ?", (max(1, int(limit or 20)),)).fetchall()
        return [payload for payload in (_loads(row["payload_json"], {}) for row in rows) if isinstance(payload, dict)]

    def acknowledge_finding(self, finding_id: str, actor: dict[str, Any] | None = None) -> dict[str, Any] | None:
        now = float(self.clock())
        with self.connect() as conn:
            row = conn.execute("SELECT payload_json FROM analyst_findings WHERE finding_id = ?", (str(finding_id),)).fetchone()
            if not row:
                return None
            payload = _loads(row["payload_json"], {})
            if isinstance(payload, dict):
                payload = {**payload, "acknowledged": True, "acknowledged_at": now, "acknowledged_by": (actor or {}).get("id") or "operator"}
            conn.execute(
                "UPDATE analyst_findings SET acknowledged_at = ?, payload_json = ? WHERE finding_id = ?",
                (now, _json_dumps(payload), str(finding_id)),
            )
            conn.commit()
        return payload if isinstance(payload, dict) else {"id": finding_id, "acknowledged": True}

    def prune(self, retention_days: int | None = None) -> dict[str, int]:
        days = retention_days if retention_days is not None else int(os.environ.get("MATTS_OPERATIONAL_RETENTION_DAYS", "90"))
        cutoff = float(self.clock()) - max(1, int(days)) * 86400
        deleted: dict[str, int] = {}
        with self.connect() as conn:
            for table, column in (
                ("operational_records", "ts"),
                ("digitalocean_snapshots", "created_at"),
                ("analyst_runs", "created_at"),
            ):
                before = conn.total_changes
                conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
                deleted[table] = conn.total_changes - before
            before = conn.total_changes
            conn.execute("DELETE FROM analyst_findings WHERE lifecycle_status = 'resolved' AND last_seen_at < ?", (cutoff,))
            deleted["analyst_findings"] = conn.total_changes - before
            conn.commit()
        return deleted

    def parity(self, sources: dict[str, str | os.PathLike[str]]) -> dict[str, Any]:
        result: dict[str, Any] = {"database": str(self.db_path), "sources": {}}
        for kind, source in sources.items():
            backfill = self.backfill_jsonl(kind, source)
            with self.connect() as conn:
                db_count = conn.execute("SELECT COUNT(*) AS count FROM operational_records WHERE kind = ?", (kind,)).fetchone()["count"]
            result["sources"][kind] = {**backfill, "database_rows": int(db_count), "parity": int(db_count) >= int(backfill.get("rows") or 0)}
        return result
