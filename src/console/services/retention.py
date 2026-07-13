"""Bounded growth (size-based rotation) for append-only runtime JSONL logs.

``usage.jsonl``, ``traces.jsonl``, and the proxy request log are appended on
every proxy request and otherwise grow without bound. ``RetentionService``
rewrites a file that exceeds ``max_bytes`` down to its last ``keep_bytes``
(aligned to a line boundary) and archives the trimmed head to a
single-generation ``<name>.1.jsonl.gz`` sibling, overwriting the previous
archive. The live file is replaced atomically (temp file + ``os.replace``,
the same pattern as ``model_registry.save``), so readers always see either
the old or the new complete file.

Concurrency tradeoff (deliberate, documented): rotation takes the same
sidecar ``<name>.lock`` flock that ``RuntimeStateRepository.append_jsonl``
uses, so console-side writers (traces, audit) are fully serialized with
rotation. The proxy process appends with a plain ``open(path, "a")`` and no
lock, so a row appended between the tail snapshot and ``os.replace`` can be
lost — a handful of lines at worst, once per rotation (roughly per 32 MB of
log). That loss is accepted for an operator-local log: the proxy's
incremental budget aggregator keys on the file's inode and size, detects the
replace, and re-seeds itself from the rotated file, and console analytics
caches key on ``(mtime, size)`` so they re-read naturally. After rotation,
"all time" style totals reflect only the retained window plus whatever the
aggregator had already accumulated in memory.

Thresholds can be overridden with ``MATTS_RETENTION_MAX_BYTES`` and
``MATTS_RETENTION_KEEP_BYTES``.
"""
import contextlib
import fcntl
import gzip
import os
import tempfile
import threading
import time
from pathlib import Path

DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_KEEP_BYTES = 8 * 1024 * 1024
DEFAULT_SWEEP_INTERVAL_SECONDS = 600.0
MAX_BYTES_ENV = "MATTS_RETENTION_MAX_BYTES"
KEEP_BYTES_ENV = "MATTS_RETENTION_KEEP_BYTES"
_COPY_CHUNK_BYTES = 1024 * 1024


def _positive_int(value, default):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


class RetentionService:
    """Rotate oversized runtime JSONL files, archiving the trimmed head."""

    def __init__(self, targets=None, max_bytes=None, keep_bytes=None, sweep_interval=DEFAULT_SWEEP_INTERVAL_SECONDS, clock=None, env=None):
        env = os.environ if env is None else env
        self.targets = list(targets or [])
        self.max_bytes = _positive_int(env.get(MAX_BYTES_ENV), DEFAULT_MAX_BYTES) if max_bytes is None else _positive_int(max_bytes, DEFAULT_MAX_BYTES)
        self.keep_bytes = _positive_int(env.get(KEEP_BYTES_ENV), DEFAULT_KEEP_BYTES) if keep_bytes is None else _positive_int(keep_bytes, DEFAULT_KEEP_BYTES)
        if self.keep_bytes >= self.max_bytes:
            # A keep window at or above the trigger threshold would rotate on
            # every sweep; clamp to a sane fraction instead of erroring.
            self.keep_bytes = max(1, self.max_bytes // 4)
        self.sweep_interval = float(sweep_interval)
        self.clock = clock or time.time
        self._lock = threading.Lock()
        self._last_sweep = None

    @staticmethod
    def archive_path(path):
        """`usage.jsonl` -> sibling `usage.1.jsonl.gz` (single generation)."""
        path = Path(path)
        name = path.name
        stem = name[: -len(".jsonl")] if name.endswith(".jsonl") else name
        return path.with_name(stem + ".1.jsonl.gz")

    @staticmethod
    @contextlib.contextmanager
    def _file_lock(path):
        """Same sidecar-lock convention as RuntimeStateRepository.file_lock."""
        lock_path = path.with_name(path.name + ".lock")
        with lock_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def maintain(self, force=False):
        """Throttled sweep over all targets; cheap no-op between intervals.

        Returns the per-file results for a sweep that ran, or an empty list
        when throttled. One failing target never aborts the sweep.
        """
        now = self.clock()
        with self._lock:
            if not force and self._last_sweep is not None and (now - self._last_sweep) < self.sweep_interval:
                return []
            self._last_sweep = now
        results = []
        for target in self.targets:
            try:
                path = target() if callable(target) else target
            except Exception as exc:
                results.append({"path": None, "rotated": False, "error": str(exc)})
                continue
            if not path:
                continue
            try:
                results.append(self.rotate_if_needed(path))
            except OSError as exc:
                results.append({"path": str(path), "rotated": False, "error": str(exc)})
        return results

    def rotate_if_needed(self, path, max_bytes=None, keep_bytes=None):
        """Trim ``path`` to its last ``keep_bytes`` once it exceeds ``max_bytes``.

        Missing files and files at or under the threshold are no-ops. The
        trimmed head is gzip-archived (overwriting the previous archive)
        before the live file is atomically replaced with the line-aligned
        tail.
        """
        path = Path(path)
        max_bytes = self.max_bytes if max_bytes is None else _positive_int(max_bytes, self.max_bytes)
        keep_bytes = self.keep_bytes if keep_bytes is None else _positive_int(keep_bytes, self.keep_bytes)
        try:
            size = path.stat().st_size
        except OSError:
            return {"path": str(path), "rotated": False, "reason": "missing"}
        if size <= max_bytes:
            return {"path": str(path), "rotated": False, "reason": "under_threshold", "size_bytes": size}
        with self._file_lock(path):
            return self._rotate_locked(path, max_bytes, keep_bytes)

    def _rotate_locked(self, path, max_bytes, keep_bytes):
        # Re-stat under the lock: another process may have rotated already.
        try:
            stat = path.stat()
        except OSError:
            return {"path": str(path), "rotated": False, "reason": "missing"}
        size = stat.st_size
        if size <= max_bytes:
            return {"path": str(path), "rotated": False, "reason": "under_threshold", "size_bytes": size}
        with path.open("rb") as src:
            src.seek(max(0, size - keep_bytes))
            window = src.read(keep_bytes)
        # Align the kept tail to the first line boundary inside the window so
        # every retained line is complete. Degenerate case: a single line
        # larger than keep_bytes has no usable boundary; keep the raw window
        # (readers tolerate one malformed leading row).
        cut = window.find(b"\n") + 1
        if cut <= 0 or cut >= len(window):
            cut = 0
        tail = window[cut:]
        head_len = size - len(tail)
        archive = self.archive_path(path)
        self._archive_head(path, head_len, archive)
        self._replace_with_tail(path, tail, stat.st_mode & 0o777)
        return {
            "path": str(path),
            "rotated": True,
            "size_bytes": size,
            "kept_bytes": len(tail),
            "archived_bytes": head_len,
            "archive": str(archive),
        }

    @staticmethod
    def _archive_head(path, head_len, archive):
        """Stream the first ``head_len`` bytes into the gz archive atomically."""
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".retention-", suffix=".gz.tmp")
        try:
            with os.fdopen(fd, "wb") as raw:
                with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz, path.open("rb") as src:
                    remaining = head_len
                    while remaining > 0:
                        chunk = src.read(min(_COPY_CHUNK_BYTES, remaining))
                        if not chunk:
                            break
                        gz.write(chunk)
                        remaining -= len(chunk)
                raw.flush()
                os.fsync(raw.fileno())
            os.replace(tmp, str(archive))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _replace_with_tail(path, tail, mode):
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".retention-", suffix=".jsonl.tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(tail)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, str(path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
