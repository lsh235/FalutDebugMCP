"""Post-exit collector and local multi-daemon registration API."""
from __future__ import annotations

import argparse
import json
import mmap
import math
import os
import secrets
import select
import time
from dataclasses import dataclass
from pathlib import Path

from .session import ProcessIdentity, SESSION_SCHEMA


def _target_gone(pid: int) -> bool:
    try:
        stat_line = Path(f"/proc/{pid}/stat").read_text()
        close = stat_line.rfind(")")
        if close >= 0 and len(stat_line) > close + 2 and stat_line[close + 2] == "Z":
            return True
    except FileNotFoundError:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}-{secrets.token_hex(8)}.tmp"
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
        directory_fd = os.open(path.parent, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


@dataclass(frozen=True)
class CollectorRegistration:
    """Durable metadata for one locally supervised target.

    File descriptors are intentionally not serialized: they are process-local.
    The registering launcher retains them and calls ``collect_registered``.
    Another local agent may use this manifest for inventory and recovery, while
    a future FD-passing transport can attach the descriptors explicitly.
    """

    path: Path
    identity: ProcessIdentity
    pid: int
    artifact_dir: Path


def register_process(
    registry: Path,
    *,
    identity: ProcessIdentity,
    pid: int,
    artifact_dir: Path,
) -> CollectorRegistration:
    """Atomically register a running process for local collection."""
    if pid <= 0:
        raise ValueError("pid must be positive")
    registry = Path(registry)
    path = registry / f"{identity.session_id}-{identity.process_id}.json"
    record = {
        "schema": SESSION_SCHEMA,
        "state": "registered",
        "registered_monotonic_ns": time.monotonic_ns(),
        "session": identity.session_record(),
        "process": identity.process_record(pid=pid),
        "pid": pid,
        "artifact_dir": str(Path(artifact_dir).resolve()),
    }
    _atomic_json(path, record)
    return CollectorRegistration(path, identity, pid, Path(artifact_dir))


def unregister_process(registration: CollectorRegistration | Path) -> None:
    path = registration.path if isinstance(registration, CollectorRegistration) else Path(registration)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _wait_for_target(pid: int, timeout: float) -> bool:
    """Wait for this process instance, avoiding PID reuse when pidfd exists."""
    pidfd_open = getattr(os, "pidfd_open", None)
    if pidfd_open is not None:
        try:
            pidfd = pidfd_open(pid, 0)
        except (OSError, ProcessLookupError):
            return _target_gone(pid)
        try:
            ready, _, _ = select.select([pidfd], [], [], max(0.0, timeout))
            return bool(ready)
        finally:
            os.close(pidfd)
    deadline = time.monotonic() + timeout
    while not _target_gone(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    return True


def collect_report(shm_fd: int, ready_fd: int, pid: int, timeout: float) -> tuple[int, dict[str, object]]:
    from .format import collect_mapping
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("timeout must be a finite non-negative number")
    deadline = time.monotonic() + timeout
    readable, _, _ = select.select([ready_fd], [], [], max(0.0, deadline - time.monotonic()))
    if not readable:
        return 3, {"collector": {"ok": False, "phase": "ready_timeout", "timeout_seconds": timeout}}
    ready = os.read(ready_fd, 1)
    if ready != b"R":
        return 2, {"collector": {"ok": False, "phase": "startup", "ready_byte": ready.decode("latin1")}}
    remaining = max(0.0, deadline - time.monotonic())
    if not _wait_for_target(pid, remaining):
        return 3, {"collector": {"ok": False, "phase": "wait_timeout", "timeout_seconds": timeout}}
    with mmap.mmap(shm_fd, os.fstat(shm_fd).st_size, access=mmap.ACCESS_READ) as mapping:
        report = collect_mapping(mapping)
    report["collector"] = {"ok": True, "phase": "post_exit"}
    return 0, report


def collect_registered(
    registration: CollectorRegistration,
    *,
    shm_fd: int,
    ready_fd: int,
    timeout: float,
    output: Path | None = None,
) -> tuple[int, dict[str, object]]:
    """Collect a registered process and optionally atomically publish JSON."""
    try:
        code, report = collect_report(shm_fd, ready_fd, registration.pid, timeout)
        if code == 0:
            report["session"] = registration.identity.session_record()
            report["process"] = registration.identity.process_record(pid=registration.pid)
        if output is not None:
            _atomic_json(Path(output), report)
        return code, report
    finally:
        # A decoder or output failure must not leave a registration that looks
        # live forever; the final artifact and error remain the evidence.
        unregister_process(registration)


def collect(shm_fd: int, ready_fd: int, pid: int, output: Path, timeout: float) -> int:
    code, report = collect_report(shm_fd, ready_fd, pid, timeout)
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(output, report)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(prog="faultdebug-collector")
    parser.add_argument("--shm-fd", type=int, required=True)
    parser.add_argument("--ready-fd", type=int, required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    ns = parser.parse_args()
    return collect(ns.shm_fd, ns.ready_fd, ns.pid, ns.output, ns.timeout)
