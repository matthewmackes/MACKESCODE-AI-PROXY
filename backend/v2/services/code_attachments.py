"""Session-scoped Code screenshot/image attachment storage."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any


SUPPORTED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _safe_name(value: str, fallback: str = "default") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value or "").strip("-._")
    return text[:80] or fallback


def _image_dimensions(mime_type: str, data: bytes) -> tuple[int, int]:
    if mime_type == "image/png" and len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if mime_type == "image/gif" and len(data) >= 10 and data[:6] in {b"GIF87a", b"GIF89a"}:
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if mime_type == "image/webp" and len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X" and len(data) >= 30:
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
    if mime_type == "image/jpeg" and data[:2] == b"\xff\xd8":
        idx = 2
        while idx + 9 < len(data):
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            idx += 2
            if marker in {0xD8, 0xD9}:
                continue
            length = int.from_bytes(data[idx:idx + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and idx + 7 < len(data):
                return int.from_bytes(data[idx + 5:idx + 7], "big"), int.from_bytes(data[idx + 3:idx + 5], "big")
            idx += max(2, length)
    return 0, 0


class CodeAttachmentStore:
    """Persist image uploads under a Code session without logging raw bytes."""

    def __init__(self, root_dir: Path | None = None, clock: Any | None = None, uuid_factory: Any | None = None) -> None:
        base = Path(os.environ.get("MATTS_V2_CODE_ATTACHMENT_DIR", Path.home() / ".cache" / "matts-value-set" / "studio" / "code-attachments"))
        self.root_dir = root_dir or base
        self.clock = clock or time.time
        self.uuid_factory = uuid_factory or uuid.uuid4
        self.max_bytes = int(os.environ.get("MATTS_V2_CODE_ATTACHMENT_MAX_BYTES", str(8 * 1024 * 1024)))

    def session_dir(self, session_id: str) -> Path:
        return self.root_dir / _safe_name(session_id, "default")

    def metadata_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "attachments.json"

    def load(self, session_id: str) -> list[dict[str, Any]]:
        path = self.metadata_path(session_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = data.get("attachments") if isinstance(data, dict) else data
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def save(self, session_id: str, rows: list[dict[str, Any]]) -> None:
        directory = self.session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        self.metadata_path(session_id).write_text(json.dumps({"attachments": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def decode_payload(self, payload: dict[str, Any]) -> bytes:
        raw = str(payload.get("data") or "")
        if "," in raw and raw.startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            return base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("attachment data must be valid base64") from exc

    def create(self, payload: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or payload.get("session") or "default")
        mime_type = str(payload.get("mime_type") or payload.get("type") or "").lower()
        if mime_type not in SUPPORTED_IMAGE_TYPES:
            raise ValueError("unsupported image type")
        data = self.decode_payload(payload)
        if not data:
            raise ValueError("attachment data is required")
        if len(data) > self.max_bytes:
            raise ValueError("attachment exceeds configured size limit")
        attachment_id = self.uuid_factory().hex
        suffix = SUPPORTED_IMAGE_TYPES[mime_type]
        original_name = _safe_name(str(payload.get("filename") or "screenshot"))
        filename = original_name if original_name.lower().endswith(suffix) else original_name + suffix
        stored_name = attachment_id + suffix
        directory = self.session_dir(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / stored_name
        path.write_bytes(data)
        width, height = _image_dimensions(mime_type, data)
        row = {
            "id": attachment_id,
            "session_id": _safe_name(session_id, "default"),
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(data).hexdigest(),
            "path": str(path),
            "created_at": self.clock(),
            "actor_id": str((actor or {}).get("id") or "anonymous"),
        }
        rows = self.load(session_id)
        rows.append(row)
        self.save(session_id, rows)
        return self.public_metadata(row)

    def public_metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "session_id", "filename", "mime_type", "size_bytes", "width", "height", "sha256", "created_at", "actor_id")}

    def list(self, session_id: str) -> list[dict[str, Any]]:
        return [self.public_metadata(row) for row in self.load(session_id)]

    def delete(self, session_id: str, attachment_id: str) -> dict[str, Any]:
        rows = self.load(session_id)
        kept = []
        deleted: dict[str, Any] | None = None
        for row in rows:
            if row.get("id") == attachment_id:
                deleted = row
                try:
                    Path(str(row.get("path") or "")).unlink()
                except OSError:
                    pass
            else:
                kept.append(row)
        self.save(session_id, kept)
        return {"deleted": bool(deleted), "attachment": self.public_metadata(deleted or {}) if deleted else None}

    def data_uri(self, session_id: str, attachment_id: str) -> str:
        for row in self.load(session_id):
            if row.get("id") == attachment_id:
                data = Path(str(row.get("path") or "")).read_bytes()
                return "data:%s;base64,%s" % (row.get("mime_type") or "application/octet-stream", base64.b64encode(data).decode("ascii"))
        raise ValueError("attachment not found")
