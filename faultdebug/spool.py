"""Bounded local spool for verified ``.fault`` artifacts.

The spool is deliberately local and file based.  It verifies the FDAR checksum
before copying, writes a temporary file followed by ``fsync`` and ``rename``,
and rotates the oldest valid artifacts under explicit byte/file limits.  It
does not transmit artifacts, encrypt them, or inspect arbitrary payload keys.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Iterator, Sequence

from .artifact import HEADER, MAGIC, VERSION, ArtifactError, read_artifact

REDACTED = "[REDACTED]"
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_FILES = 1000
_TEMP_PREFIX = ".faultdebug-"
_TEMP_SUFFIX = ".tmp"


class SpoolError(ValueError):
    """An artifact cannot be safely admitted to the local spool."""


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _verified_payload(path: Path) -> tuple[dict, int, bytes]:
    try:
        raw = path.read_bytes()
        if len(raw) < HEADER.size:
            raise ArtifactError("artifact is truncated")
        magic, version, _flags, length, pid, digest = HEADER.unpack_from(raw)
        report = read_artifact(path)
    except (OSError, ArtifactError, ValueError, json.JSONDecodeError) as exc:
        raise SpoolError(f"invalid artifact {path}: {exc}") from exc
    if magic != MAGIC or version != VERSION or length != len(raw) - HEADER.size:
        raise SpoolError(f"invalid artifact header: {path}")
    if not isinstance(report, dict):
        raise SpoolError(f"artifact report must be an object: {path}")
    payload = raw[HEADER.size:]
    if hashlib.sha256(payload).digest() != digest:
        raise SpoolError(f"artifact checksum mismatch: {path}")
    return report, pid, payload


def _redact_report(report: dict, identifiers: frozenset[str]) -> dict:
    """Redact only configured top-level context IDs.

    This intentionally does not recursively walk the report: arbitrary future
    payload-shaped fields must never be treated as safe metadata to rewrite.
    """
    if not identifiers:
        return report
    context = report.get("context")
    if not isinstance(context, dict):
        return report
    result = dict(report)
    context_copy = dict(context)
    changed = False
    for key in ("trace_id", "correlation_id"):
        value = context_copy.get(key)
        if value is not None and str(value) in identifiers:
            context_copy[key] = REDACTED
            changed = True
    if changed:
        result["context"] = context_copy
    return result


def _encode_payload(report: dict, pid: int) -> bytes:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(payload).digest()
    return HEADER.pack(MAGIC, VERSION, 0, len(payload), pid, digest) + payload


class ArtifactSpool:
    """A bounded, crash-safe local spool for completed fault artifacts."""

    def __init__(self, root: Path, *, max_bytes: int, max_files: int,
                 redact_context_ids: Sequence[str] = ()) -> None:
        if max_bytes <= HEADER.size or max_files < 1:
            raise SpoolError("max_bytes must exceed the artifact header and max_files must be positive")
        self.root = Path(root)
        self.max_bytes = int(max_bytes)
        self.max_files = int(max_files)
        self.redact_context_ids = frozenset(str(value) for value in redact_context_ids)
        self.root.mkdir(parents=True, exist_ok=True)
        self.recover()

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        lock_path = self.root / ".spool.lock"
        with lock_path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def recover(self) -> dict[str, object]:
        """Remove only this spool's abandoned temporary files.

        Final ``.fault`` files are left in place for inspection; malformed
        finals are reported and never ingested or silently deleted.
        """
        with self._lock():
            removed = 0
            for path in self.root.glob(f"{_TEMP_PREFIX}*{_TEMP_SUFFIX}"):
                try:
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
            invalid: list[str] = []
            for path in self.root.glob("*.fault"):
                try:
                    _verified_payload(path)
                except SpoolError:
                    invalid.append(path.name)
            rotated = self._rotate_for(0, incoming_count=0)
            if removed or rotated:
                _fsync_directory(self.root)
            return {"removed_temps": removed, "invalid_files": invalid}

    def _entries(self) -> list[tuple[Path, int, int]]:
        entries: list[tuple[Path, int, int]] = []
        for path in self.root.glob("*.fault"):
            try:
                _verified_payload(path)
                stat = path.stat()
            except (SpoolError, OSError):
                continue
            entries.append((path, stat.st_size, stat.st_mtime_ns))
        entries.sort(key=lambda row: (row[2], row[0].name))
        return entries

    def _rotate_for(self, incoming_size: int, *, incoming_count: int = 1) -> list[str]:
        entries = self._entries()
        removed: list[str] = []
        total = sum(row[1] for row in entries)
        while entries and (len(entries) + incoming_count > self.max_files or total + incoming_size > self.max_bytes):
            path, size, _mtime = entries.pop(0)
            path.unlink()
            total -= size
            removed.append(path.name)
        if len(entries) + incoming_count > self.max_files or total + incoming_size > self.max_bytes:
            raise SpoolError("artifact exceeds spool limits after rotation")
        return removed

    def ingest(self, source: Path) -> Path:
        """Verify and atomically copy one completed artifact into the spool."""
        source = Path(source)
        report, pid, payload = _verified_payload(source)
        report = _redact_report(report, self.redact_context_ids)
        encoded = _encode_payload(report, pid)
        if len(encoded) > self.max_bytes:
            raise SpoolError("artifact exceeds max_bytes")
        with self._lock():
            stem = source.name if source.name.endswith(".fault") else f"fault-{pid}.fault"
            destination = self.root / stem
            serial = 0
            while destination.exists():
                serial += 1
                destination = self.root / f"{Path(stem).stem}-{serial}.fault"
            temporary = self.root / f"{_TEMP_PREFIX}{os.getpid()}-{secrets.token_hex(8)}{_TEMP_SUFFIX}"
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
                _fsync_directory(self.root)
                self._rotate_for(0, incoming_count=0)
                _fsync_directory(self.root)
            except Exception:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                raise
            return destination

    def list_files(self) -> list[Path]:
        with self._lock():
            return [row[0] for row in self._entries()]

    def stats(self) -> dict[str, int]:
        with self._lock():
            entries = self._entries()
            return {"files": len(entries), "bytes": sum(row[1] for row in entries),
                    "max_files": self.max_files, "max_bytes": self.max_bytes}
