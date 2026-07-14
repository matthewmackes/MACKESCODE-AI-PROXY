"""SQLite-backed Research dossier persistence for the v2 Research workspace."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.console.services.operational_store import operational_db_path

DEFAULT_DB = operational_db_path()


class ResearchDossierStore:
    """Persist Research dossiers and per-dossier pinned evidence."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None, clock=None) -> None:
        self.db_path = Path(db_path or os.environ.get("MATTS_V2_RESEARCH_DB", DEFAULT_DB))
        self.clock = clock or time.time

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        self.migrate(conn)
        return conn

    def migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_dossiers (
              id TEXT PRIMARY KEY,
              query TEXT NOT NULL DEFAULT '',
              mode TEXT NOT NULL DEFAULT '',
              dossier_json TEXT NOT NULL DEFAULT '{}',
              pins_json TEXT NOT NULL DEFAULT '[]',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()

    def save_dossier(self, dossier: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(dossier, dict):
            raise ValueError("research dossier payload is required")
        dossier_id = str(dossier.get("dossier_id") or "").strip()
        if not dossier_id:
            raise ValueError("research dossier id is required")
        query = dossier.get("query") if isinstance(dossier.get("query"), dict) else {}
        text = str(query.get("text") or dossier.get("query_text") or "").strip()
        mode = str(query.get("mode") or dossier.get("mode") or "").strip()
        now = float(self.clock())
        existing_created_at = now
        with self.connect() as conn:
            existing = conn.execute("SELECT created_at FROM research_dossiers WHERE id = ?", (dossier_id,)).fetchone()
            if existing:
                existing_created_at = float(existing["created_at"])
            pins = self._valid_pins(dossier, dossier.get("pinned_evidence_ids"))
            dossier = self._with_pins(dossier, pins)
            conn.execute(
                """
                INSERT INTO research_dossiers (id, query, mode, dossier_json, pins_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  query=excluded.query,
                  mode=excluded.mode,
                  dossier_json=excluded.dossier_json,
                  pins_json=excluded.pins_json,
                  updated_at=excluded.updated_at
                """,
                (
                    dossier_id,
                    text,
                    mode,
                    json.dumps(dossier, sort_keys=True),
                    json.dumps(pins),
                    existing_created_at,
                    now,
                ),
            )
            conn.commit()
        return dossier

    def get_dossier(self, dossier_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM research_dossiers WHERE id = ?", (str(dossier_id or ""),)).fetchone()
        return self._row_to_dossier(row) if row else None

    def update_pins(self, dossier_id: str, evidence_ids: Any) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM research_dossiers WHERE id = ?", (str(dossier_id or ""),)).fetchone()
            if not row:
                raise KeyError("research dossier not found")
            dossier = self._row_to_dossier(row)
            pins = self._valid_pins(dossier, evidence_ids, strict=True)
            dossier = self._with_pins(dossier, pins)
            now = float(self.clock())
            conn.execute(
                """
                UPDATE research_dossiers
                SET dossier_json = ?, pins_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(dossier, sort_keys=True), json.dumps(pins), now, str(dossier_id or "")),
            )
            conn.commit()
        return dossier

    def report_packet(self, dossier_id: str) -> dict[str, Any] | None:
        dossier = self.get_dossier(dossier_id)
        if not dossier:
            return None
        report = dossier.get("report_packet") if isinstance(dossier.get("report_packet"), dict) else {}
        return {**report, "dossier_id": dossier.get("dossier_id"), "pinned_evidence_ids": dossier.get("pinned_evidence_ids", [])}

    def _row_to_dossier(self, row: sqlite3.Row) -> dict[str, Any]:
        dossier = self._loads(row["dossier_json"], {})
        pins = self._loads(row["pins_json"], [])
        if not isinstance(dossier, dict):
            dossier = {}
        dossier["dossier_id"] = str(row["id"])
        dossier["pinned_evidence_ids"] = self._valid_pins(dossier, pins)
        return self._with_pins(dossier, dossier["pinned_evidence_ids"])

    def _with_pins(self, dossier: dict[str, Any], pins: list[str]) -> dict[str, Any]:
        next_dossier = dict(dossier)
        next_dossier["pinned_evidence_ids"] = pins
        report = next_dossier.get("report_packet") if isinstance(next_dossier.get("report_packet"), dict) else {}
        evidence = [
            item for item in next_dossier.get("evidence", [])
            if isinstance(item, dict) and str(item.get("evidence_id") or item.get("id") or "") in pins
        ]
        sections = []
        for section in report.get("sections", []) if isinstance(report.get("sections"), list) else []:
            if isinstance(section, dict) and section.get("id") == "pinned-evidence":
                sections.append({**section, "items": evidence})
            elif isinstance(section, dict):
                sections.append(section)
        next_dossier["report_packet"] = {**report, "sections": sections, "pinned_evidence_ids": pins}
        return next_dossier

    def _valid_pins(self, dossier: dict[str, Any], value: Any, strict: bool = False) -> list[str]:
        requested = [str(item).strip() for item in value if str(item or "").strip()] if isinstance(value, list) else []
        evidence_ids = {
            str(item.get("evidence_id") or item.get("id") or "")
            for item in dossier.get("evidence", [])
            if isinstance(item, dict)
        }
        invalid = [item for item in requested if item not in evidence_ids]
        if invalid and strict:
            raise ValueError("unknown evidence id: %s" % invalid[0])
        pins: list[str] = []
        for item in requested:
            if item in evidence_ids and item not in pins:
                pins.append(item)
        return pins

    def _loads(self, raw: str, fallback: Any) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return fallback
