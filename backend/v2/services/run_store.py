"""SQLite-backed v2 Run Experience storage."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from src.console.services.eval_gates import EvalGateBlocked, EvalGateService
from src.console.services.operational_store import operational_db_path


PROJECT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DB = operational_db_path()
TEMPLATE_VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*}}")


class RunStore:
    """Persist prompt templates and run profiles for the v2 Run workspace."""

    def __init__(self, db_path: str | os.PathLike[str] | None = None, clock=None) -> None:
        self.db_path = Path(db_path or os.environ.get("MATTS_V2_RUN_DB", DEFAULT_DB))
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
            CREATE TABLE IF NOT EXISTS prompt_templates (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              body TEXT NOT NULL,
              variables_json TEXT NOT NULL DEFAULT '[]',
              examples_json TEXT NOT NULL DEFAULT '[]',
              owner_notes TEXT NOT NULL DEFAULT '',
              tags_json TEXT NOT NULL DEFAULT '[]',
              version INTEGER NOT NULL DEFAULT 1,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        self._ensure_column(conn, "prompt_templates", "examples_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_column(conn, "prompt_templates", "owner_notes", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompt_template_versions (
              template_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              body TEXT NOT NULL,
              variables_json TEXT NOT NULL DEFAULT '[]',
              examples_json TEXT NOT NULL DEFAULT '[]',
              owner_notes TEXT NOT NULL DEFAULT '',
              tags_json TEXT NOT NULL DEFAULT '[]',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              archived_at REAL NOT NULL,
              PRIMARY KEY (template_id, version)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_profiles (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL DEFAULT '',
              template_id TEXT NOT NULL DEFAULT '',
              settings_json TEXT NOT NULL DEFAULT '{}',
              tags_json TEXT NOT NULL DEFAULT '[]',
              version INTEGER NOT NULL DEFAULT 1,
              active INTEGER NOT NULL DEFAULT 0,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        self._ensure_column(conn, "run_profiles", "active", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_profile_versions (
              profile_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL DEFAULT '',
              template_id TEXT NOT NULL DEFAULT '',
              settings_json TEXT NOT NULL DEFAULT '{}',
              tags_json TEXT NOT NULL DEFAULT '[]',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL,
              archived_at REAL NOT NULL,
              PRIMARY KEY (profile_id, version)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_branches (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              root_session_id TEXT NOT NULL DEFAULT '',
              parent_branch_id TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              messages_json TEXT NOT NULL DEFAULT '[]',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              tags_json TEXT NOT NULL DEFAULT '[]',
              version INTEGER NOT NULL DEFAULT 1,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_snapshots (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              title TEXT NOT NULL,
              trace_id TEXT NOT NULL DEFAULT '',
              summary TEXT NOT NULL DEFAULT '',
              agentboard_json TEXT NOT NULL DEFAULT '{}',
              resource_json TEXT NOT NULL DEFAULT '{}',
              tags_json TEXT NOT NULL DEFAULT '[]',
              version INTEGER NOT NULL DEFAULT 1,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_records (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              trace_id TEXT NOT NULL DEFAULT '',
              session_id TEXT NOT NULL DEFAULT '',
              profile_id TEXT NOT NULL DEFAULT '',
              profile_version INTEGER NOT NULL DEFAULT 0,
              prompt_template_id TEXT NOT NULL DEFAULT '',
              prompt_template_version INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'recorded',
              input_json TEXT NOT NULL DEFAULT '{}',
              result_json TEXT NOT NULL DEFAULT '{}',
              metadata_json TEXT NOT NULL DEFAULT '{}',
              tags_json TEXT NOT NULL DEFAULT '[]',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS eval_gate_records (
              id TEXT PRIMARY KEY,
              surface TEXT NOT NULL,
              target_id TEXT NOT NULL DEFAULT '',
              target_version INTEGER NOT NULL DEFAULT 0,
              decision TEXT NOT NULL,
              allowed INTEGER NOT NULL DEFAULT 0,
              required INTEGER NOT NULL DEFAULT 0,
              change_hash TEXT NOT NULL DEFAULT '',
              gate_json TEXT NOT NULL DEFAULT '{}',
              created_at REAL NOT NULL
            )
            """
        )
        conn.commit()

    def list_prompt_templates(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM prompt_templates ORDER BY updated_at DESC, name ASC").fetchall()
        return [self._template_from_row(row) for row in rows]

    def save_prompt_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = float(self.clock())
        item_id = str(payload.get("id") or uuid.uuid4())
        name = str(payload.get("name") or "").strip()
        body = str(payload.get("body") or "").strip()
        if not name:
            raise ValueError("prompt template name is required")
        if not body:
            raise ValueError("prompt template body is required")
        description = str(payload.get("description") or "").strip()
        variables = self._string_list(payload.get("variables"))
        examples = self._examples_list(payload.get("examples"))
        owner_notes = str(payload.get("owner_notes") or "").strip()
        tags = self._string_list(payload.get("tags"))
        eval_gate = payload.get("eval_gate") if isinstance(payload.get("eval_gate"), dict) else None
        gate_result = None
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (item_id,)).fetchone()
            version = int(existing["version"]) + 1 if existing else int(payload.get("version") or 1)
            created_at = float(existing["created_at"]) if existing else now
            before = self._template_from_row(existing) if existing else {}
            after = {
                "id": item_id,
                "name": name,
                "description": description,
                "body": body,
                "variables": variables,
                "examples": examples,
                "owner_notes": owner_notes,
                "tags": tags,
                "version": version,
            }
            gate_result = self._enforce_eval_gate("prompt_template", before, after, eval_gate, item_id, version)
            if existing:
                self._archive_template_version(conn, existing, now)
            conn.execute(
                """
                INSERT INTO prompt_templates (id, name, description, body, variables_json, examples_json, owner_notes, tags_json, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  description=excluded.description,
                  body=excluded.body,
                  variables_json=excluded.variables_json,
                  examples_json=excluded.examples_json,
                  owner_notes=excluded.owner_notes,
                  tags_json=excluded.tags_json,
                  version=excluded.version,
                  updated_at=excluded.updated_at
                """,
                (item_id, name, description, body, json.dumps(variables), json.dumps(examples, sort_keys=True), owner_notes, json.dumps(tags), version, created_at, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (item_id,)).fetchone()
            self._archive_template_version(conn, row, now)
            gate_record = self._record_eval_gate(conn, "prompt_template", item_id, version, gate_result)
            conn.commit()
        result = self._template_from_row(row)
        if gate_record:
            result["eval_gate"] = gate_record
        return result

    def list_prompt_template_versions(self, template_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM prompt_template_versions WHERE template_id = ? ORDER BY version DESC", (template_id,)).fetchall()
        return [self._template_version_from_row(row) for row in rows]

    def rollback_prompt_template(self, template_id: str, version: int) -> dict[str, Any]:
        with self.connect() as conn:
            current = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (template_id,)).fetchone()
            if not current:
                raise ValueError("prompt template not found")
            target = conn.execute("SELECT * FROM prompt_template_versions WHERE template_id = ? AND version = ?", (template_id, int(version))).fetchone()
            if not target:
                raise ValueError("prompt template version not found")
        payload = self._template_version_from_row(target)
        payload["id"] = template_id
        return self.save_prompt_template(payload)

    def preview_prompt_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = str(payload.get("body") or "")
        if not body and payload.get("template_id"):
            template_id = str(payload.get("template_id") or "")
            with self.connect() as conn:
                row = conn.execute("SELECT * FROM prompt_templates WHERE id = ?", (template_id,)).fetchone()
            if row:
                body = str(row["body"] or "")
        values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
        declared_variables = self._string_list(payload.get("variables"))
        found_variables = []
        missing = set()

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in found_variables:
                found_variables.append(name)
            if name not in values or values.get(name) in (None, ""):
                missing.add(name)
                return match.group(0)
            return str(values.get(name))

        rendered = TEMPLATE_VARIABLE_RE.sub(replace, body)
        variables = declared_variables or found_variables
        return {
            "body": body,
            "rendered": rendered,
            "variables": variables,
            "used_variables": found_variables,
            "missing_variables": sorted(missing),
        }

    def list_run_profiles(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM run_profiles ORDER BY active DESC, updated_at DESC, name ASC").fetchall()
        return [self._profile_from_row(row) for row in rows]

    def save_run_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = float(self.clock())
        item_id = str(payload.get("id") or uuid.uuid4())
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("run profile name is required")
        description = str(payload.get("description") or "").strip()
        model = str(payload.get("model") or "").strip()
        template_id = str(payload.get("template_id") or "").strip()
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        tags = self._string_list(payload.get("tags"))
        eval_gate = payload.get("eval_gate") if isinstance(payload.get("eval_gate"), dict) else None
        gate_result = None
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM run_profiles WHERE id = ?", (item_id,)).fetchone()
            version = int(existing["version"]) + 1 if existing else int(payload.get("version") or 1)
            created_at = float(existing["created_at"]) if existing else now
            active = int(existing["active"]) if existing else 0
            before = self._profile_from_row(existing) if existing else {}
            after = {
                "id": item_id,
                "name": name,
                "description": description,
                "model": model,
                "template_id": template_id,
                "settings": settings,
                "tags": tags,
                "version": version,
                "active": bool(active),
            }
            gate_result = self._enforce_eval_gate("run_profile", before, after, eval_gate, item_id, version)
            if existing:
                self._archive_profile_version(conn, existing, now)
            conn.execute(
                """
                INSERT INTO run_profiles (id, name, description, model, template_id, settings_json, tags_json, version, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name=excluded.name,
                  description=excluded.description,
                  model=excluded.model,
                  template_id=excluded.template_id,
                  settings_json=excluded.settings_json,
                  tags_json=excluded.tags_json,
                  version=excluded.version,
                  active=excluded.active,
                  updated_at=excluded.updated_at
                """,
                (item_id, name, description, model, template_id, json.dumps(settings, sort_keys=True), json.dumps(tags), version, active, created_at, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM run_profiles WHERE id = ?", (item_id,)).fetchone()
            self._archive_profile_version(conn, row, now)
            gate_record = self._record_eval_gate(conn, "run_profile", item_id, version, gate_result)
            conn.commit()
        result = self._profile_from_row(row)
        if gate_record:
            result["eval_gate"] = gate_record
        return result

    def activate_run_profile(self, profile_id: str, eval_gate: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM run_profiles WHERE id = ?", (profile_id,)).fetchone()
            if not row:
                raise ValueError("run profile not found")
            now = float(self.clock())
            before = self._profile_from_row(row)
            after = dict(before)
            after["active"] = True
            gate_result = self._enforce_eval_gate("run_profile", before, after, eval_gate, profile_id, int(row["version"]))
            conn.execute("UPDATE run_profiles SET active = 0")
            conn.execute("UPDATE run_profiles SET active = 1, updated_at = ? WHERE id = ?", (now, profile_id))
            conn.commit()
            row = conn.execute("SELECT * FROM run_profiles WHERE id = ?", (profile_id,)).fetchone()
            self._archive_profile_version(conn, row, now)
            gate_record = self._record_eval_gate(conn, "run_profile", profile_id, int(row["version"]), gate_result)
            conn.commit()
        result = self._profile_from_row(row)
        if gate_record:
            result["eval_gate"] = gate_record
        return result

    def list_run_profile_versions(self, profile_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM run_profile_versions WHERE profile_id = ? ORDER BY version DESC", (profile_id,)).fetchall()
        return [self._profile_version_from_row(row) for row in rows]

    def rollback_run_profile(self, profile_id: str, version: int) -> dict[str, Any]:
        with self.connect() as conn:
            current = conn.execute("SELECT * FROM run_profiles WHERE id = ?", (profile_id,)).fetchone()
            if not current:
                raise ValueError("run profile not found")
            target = conn.execute("SELECT * FROM run_profile_versions WHERE profile_id = ? AND version = ?", (profile_id, int(version))).fetchone()
            if not target:
                raise ValueError("run profile version not found")
        payload = self._profile_version_from_row(target)
        payload["id"] = profile_id
        return self.save_run_profile(payload)

    def payload(self) -> dict[str, Any]:
        return {
            "prompt_templates": self.list_prompt_templates(),
            "run_profiles": self.list_run_profiles(),
            "active_run_profile": next((profile for profile in self.list_run_profiles() if profile.get("active")), None),
            "run_records": self.list_run_records(),
            "eval_gate_records": self.list_eval_gate_records(),
            "conversation_branches": self.list_conversation_branches(),
            "session_snapshots": self.list_session_snapshots(),
            "database": str(self.db_path),
        }

    def preview_eval_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        return self._gate_service(payload.get("eval_gate")).preview(
            payload.get("surface") or "run_profile",
            before=payload.get("before"),
            after=payload.get("after"),
            policy=payload.get("policy"),
            eval_gate=payload.get("eval_gate"),
        )

    def list_eval_gate_records(self, target_id: str = "") -> list[dict[str, Any]]:
        with self.connect() as conn:
            if target_id:
                rows = conn.execute("SELECT * FROM eval_gate_records WHERE target_id = ? ORDER BY created_at DESC", (target_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM eval_gate_records ORDER BY created_at DESC LIMIT 100").fetchall()
        return [self._gate_record_from_row(row) for row in rows]

    def list_run_records(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM run_records ORDER BY updated_at DESC, title ASC").fetchall()
        return [self._run_record_from_row(row) for row in rows]

    def save_run_record(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = float(self.clock())
        item_id = str(payload.get("id") or uuid.uuid4())
        title = str(payload.get("title") or "").strip()
        trace_id = str(payload.get("trace_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        profile_id = str(payload.get("profile_id") or "").strip()
        if not title:
            title = trace_id or session_id or profile_id
        if not title:
            raise ValueError("run record title, trace_id, session_id, or profile_id is required")
        status = str(payload.get("status") or "recorded").strip() or "recorded"
        input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        tags = self._string_list(payload.get("tags"))
        profile_version = int(payload.get("profile_version") or 0)
        prompt_template_id = str(payload.get("prompt_template_id") or "").strip()
        prompt_template_version = int(payload.get("prompt_template_version") or 0)

        with self.connect() as conn:
            if profile_id and profile_version <= 0:
                profile = conn.execute("SELECT version FROM run_profiles WHERE id = ?", (profile_id,)).fetchone()
                if not profile:
                    raise ValueError("run profile not found")
                profile_version = int(profile["version"])
            if prompt_template_id and prompt_template_version <= 0:
                template = conn.execute("SELECT version FROM prompt_templates WHERE id = ?", (prompt_template_id,)).fetchone()
                if not template:
                    raise ValueError("prompt template not found")
                prompt_template_version = int(template["version"])
            existing = conn.execute("SELECT created_at FROM run_records WHERE id = ?", (item_id,)).fetchone()
            created_at = float(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO run_records
                  (id, title, trace_id, session_id, profile_id, profile_version, prompt_template_id, prompt_template_version,
                   status, input_json, result_json, metadata_json, tags_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  trace_id=excluded.trace_id,
                  session_id=excluded.session_id,
                  profile_id=excluded.profile_id,
                  profile_version=excluded.profile_version,
                  prompt_template_id=excluded.prompt_template_id,
                  prompt_template_version=excluded.prompt_template_version,
                  status=excluded.status,
                  input_json=excluded.input_json,
                  result_json=excluded.result_json,
                  metadata_json=excluded.metadata_json,
                  tags_json=excluded.tags_json,
                  updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    title,
                    trace_id,
                    session_id,
                    profile_id,
                    profile_version,
                    prompt_template_id,
                    prompt_template_version,
                    status,
                    json.dumps(input_payload, sort_keys=True),
                    json.dumps(result, sort_keys=True),
                    json.dumps(metadata, sort_keys=True),
                    json.dumps(tags),
                    created_at,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM run_records WHERE id = ?", (item_id,)).fetchone()
        return self._run_record_from_row(row)

    def list_conversation_branches(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM conversation_branches ORDER BY updated_at DESC, title ASC").fetchall()
        return [self._branch_from_row(row) for row in rows]

    def save_conversation_branch(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = float(self.clock())
        item_id = str(payload.get("id") or uuid.uuid4())
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("conversation branch title is required")
        root_session_id = str(payload.get("root_session_id") or "").strip()
        parent_branch_id = str(payload.get("parent_branch_id") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        tags = self._string_list(payload.get("tags"))
        with self.connect() as conn:
            existing = conn.execute("SELECT version, created_at FROM conversation_branches WHERE id = ?", (item_id,)).fetchone()
            version = int(existing["version"]) + 1 if existing else int(payload.get("version") or 1)
            created_at = float(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO conversation_branches (id, title, root_session_id, parent_branch_id, summary, messages_json, metadata_json, tags_json, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  root_session_id=excluded.root_session_id,
                  parent_branch_id=excluded.parent_branch_id,
                  summary=excluded.summary,
                  messages_json=excluded.messages_json,
                  metadata_json=excluded.metadata_json,
                  tags_json=excluded.tags_json,
                  version=excluded.version,
                  updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    title,
                    root_session_id,
                    parent_branch_id,
                    summary,
                    json.dumps(messages),
                    json.dumps(metadata, sort_keys=True),
                    json.dumps(tags),
                    version,
                    created_at,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM conversation_branches WHERE id = ?", (item_id,)).fetchone()
        return self._branch_from_row(row)

    def list_session_snapshots(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM session_snapshots ORDER BY updated_at DESC, title ASC").fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    def save_session_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = float(self.clock())
        item_id = str(payload.get("id") or uuid.uuid4())
        session_id = str(payload.get("session_id") or "").strip()
        title = str(payload.get("title") or "").strip() or session_id
        if not session_id:
            raise ValueError("session snapshot session_id is required")
        if not title:
            raise ValueError("session snapshot title is required")
        trace_id = str(payload.get("trace_id") or "").strip()
        summary = str(payload.get("summary") or "").strip()
        agentboard = payload.get("agentboard") if isinstance(payload.get("agentboard"), dict) else {}
        resource = payload.get("resource") if isinstance(payload.get("resource"), dict) else {}
        tags = self._string_list(payload.get("tags"))
        with self.connect() as conn:
            existing = conn.execute("SELECT version, created_at FROM session_snapshots WHERE id = ?", (item_id,)).fetchone()
            version = int(existing["version"]) + 1 if existing else int(payload.get("version") or 1)
            created_at = float(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO session_snapshots (id, session_id, title, trace_id, summary, agentboard_json, resource_json, tags_json, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  session_id=excluded.session_id,
                  title=excluded.title,
                  trace_id=excluded.trace_id,
                  summary=excluded.summary,
                  agentboard_json=excluded.agentboard_json,
                  resource_json=excluded.resource_json,
                  tags_json=excluded.tags_json,
                  version=excluded.version,
                  updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    session_id,
                    title,
                    trace_id,
                    summary,
                    json.dumps(agentboard, sort_keys=True),
                    json.dumps(resource, sort_keys=True),
                    json.dumps(tags),
                    version,
                    created_at,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM session_snapshots WHERE id = ?", (item_id,)).fetchone()
        return self._snapshot_from_row(row)

    def _template_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "body": row["body"],
            "variables": self._loads(row["variables_json"], []),
            "examples": self._loads(row["examples_json"], []),
            "owner_notes": row["owner_notes"],
            "tags": self._loads(row["tags_json"], []),
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _template_version_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["template_id"],
            "template_id": row["template_id"],
            "name": row["name"],
            "description": row["description"],
            "body": row["body"],
            "variables": self._loads(row["variables_json"], []),
            "examples": self._loads(row["examples_json"], []),
            "owner_notes": row["owner_notes"],
            "tags": self._loads(row["tags_json"], []),
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
        }

    def _profile_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "model": row["model"],
            "template_id": row["template_id"],
            "settings": self._loads(row["settings_json"], {}),
            "tags": self._loads(row["tags_json"], []),
            "version": row["version"],
            "active": bool(row["active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _profile_version_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["profile_id"],
            "profile_id": row["profile_id"],
            "name": row["name"],
            "description": row["description"],
            "model": row["model"],
            "template_id": row["template_id"],
            "settings": self._loads(row["settings_json"], {}),
            "tags": self._loads(row["tags_json"], []),
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
        }

    def _branch_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "root_session_id": row["root_session_id"],
            "parent_branch_id": row["parent_branch_id"],
            "summary": row["summary"],
            "messages": self._loads(row["messages_json"], []),
            "metadata": self._loads(row["metadata_json"], {}),
            "tags": self._loads(row["tags_json"], []),
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _snapshot_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "title": row["title"],
            "trace_id": row["trace_id"],
            "summary": row["summary"],
            "agentboard": self._loads(row["agentboard_json"], {}),
            "resource": self._loads(row["resource_json"], {}),
            "tags": self._loads(row["tags_json"], []),
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _run_record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "trace_id": row["trace_id"],
            "session_id": row["session_id"],
            "profile_id": row["profile_id"],
            "profile_version": row["profile_version"],
            "prompt_template_id": row["prompt_template_id"],
            "prompt_template_version": row["prompt_template_version"],
            "status": row["status"],
            "input": self._loads(row["input_json"], {}),
            "result": self._loads(row["result_json"], {}),
            "metadata": self._loads(row["metadata_json"], {}),
            "tags": self._loads(row["tags_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _gate_record_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        gate = self._loads(row["gate_json"], {})
        return {
            "id": row["id"],
            "surface": row["surface"],
            "target_id": row["target_id"],
            "target_version": row["target_version"],
            "decision": row["decision"],
            "allowed": bool(row["allowed"]),
            "required": bool(row["required"]),
            "change_hash": row["change_hash"],
            "gate": gate,
            "created_at": row["created_at"],
        }

    def _gate_service(self, eval_gate: dict[str, Any] | None = None) -> EvalGateService:
        eval_gate = eval_gate if isinstance(eval_gate, dict) else {}
        return EvalGateService(
            list_datasets=lambda: eval_gate.get("datasets") if isinstance(eval_gate.get("datasets"), list) else [],
            list_runs=lambda limit=100: eval_gate.get("runs") if isinstance(eval_gate.get("runs"), list) else [],
            clock=self.clock,
        )

    def _enforce_eval_gate(self, surface: str, before: dict[str, Any], after: dict[str, Any], eval_gate: dict[str, Any] | None, target_id: str, target_version: int) -> dict[str, Any]:
        eval_gate = eval_gate if isinstance(eval_gate, dict) else {}
        if not eval_gate:
            return {}
        gate = self._gate_service(eval_gate).enforce(
            surface,
            before=before,
            after=after,
            policy=eval_gate.get("policy"),
            eval_gate=eval_gate,
            actor=(eval_gate.get("override") or {}).get("actor") if isinstance(eval_gate.get("override"), dict) else None,
        )
        gate["target_id"] = target_id
        gate["target_version"] = int(target_version or 0)
        return gate

    def _record_eval_gate(self, conn: sqlite3.Connection, surface: str, target_id: str, target_version: int, gate: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(gate, dict) or not (gate.get("required") or gate.get("change", {}).get("changed")):
            return None
        record_id = str(uuid.uuid4())
        created_at = float(gate.get("created_at") or self.clock())
        conn.execute(
            """
            INSERT INTO eval_gate_records
              (id, surface, target_id, target_version, decision, allowed, required, change_hash, gate_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                surface,
                target_id,
                int(target_version or 0),
                str(gate.get("decision") or ""),
                1 if gate.get("allowed") else 0,
                1 if gate.get("required") else 0,
                str((gate.get("change") or {}).get("hash") or ""),
                json.dumps(gate, sort_keys=True),
                created_at,
            ),
        )
        row = conn.execute("SELECT * FROM eval_gate_records WHERE id = ?", (record_id,)).fetchone()
        return self._gate_record_from_row(row) if row else None

    def _loads(self, raw: str, fallback: Any) -> Any:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return fallback
        return value

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item or "").strip()]

    def _examples_list(self, value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        examples = []
        for item in value[:20]:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("name") or "").strip()
                values = item.get("values")
                rendered = str(item.get("rendered") or item.get("prompt") or "").strip()
                note = str(item.get("note") or item.get("description") or "").strip()
                if isinstance(values, dict):
                    value_text = json.dumps(values, sort_keys=True)
                else:
                    value_text = str(values or "").strip()
            else:
                title = ""
                value_text = ""
                rendered = str(item or "").strip()
                note = ""
            if title or value_text or rendered or note:
                examples.append({"title": title, "values": value_text, "rendered": rendered, "note": note})
        return examples

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}
        if column not in columns:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, definition))

    def _archive_profile_version(self, conn: sqlite3.Connection, row: sqlite3.Row, archived_at: float) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO run_profile_versions
              (profile_id, version, name, description, model, template_id, settings_json, tags_json, created_at, updated_at, archived_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                int(row["version"]),
                row["name"],
                row["description"],
                row["model"],
                row["template_id"],
                row["settings_json"],
                row["tags_json"],
                row["created_at"],
                row["updated_at"],
                archived_at,
            ),
        )

    def _archive_template_version(self, conn: sqlite3.Connection, row: sqlite3.Row, archived_at: float) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO prompt_template_versions
              (template_id, version, name, description, body, variables_json, examples_json, owner_notes, tags_json, created_at, updated_at, archived_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                int(row["version"]),
                row["name"],
                row["description"],
                row["body"],
                row["variables_json"],
                row["examples_json"],
                row["owner_notes"],
                row["tags_json"],
                row["created_at"],
                row["updated_at"],
                archived_at,
            ),
        )
