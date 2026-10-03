#!/usr/bin/env python3
"""Bound collector readiness and idle-agent connection waits."""
from __future__ import annotations

import os
import pathlib
import socket
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.agent import AGENT_REQUEST_TIMEOUT_SECONDS, AgentClient, AgentServer  # noqa: E402
from faultdebug.collector import collect_report  # noqa: E402


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd")) if pathlib.Path("/proc/self/fd").is_dir() else -1


def _connect_when_listening(socket_path: pathlib.Path) -> socket.socket:
    deadline = time.monotonic() + 2
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            candidate.connect(str(socket_path))
            return candidate
        except (ConnectionRefusedError, FileNotFoundError) as exc:
            last_error = exc
            candidate.close()
            time.sleep(0.005)
    raise AssertionError(f"agent socket did not become connectable: {last_error}")


def check_collector_deadlines() -> None:
    shm_fd = os.memfd_create("faultdebug-ready-timeout", os.MFD_CLOEXEC)
    ready_read, ready_write = os.pipe()
    try:
        started = time.monotonic()
        code, report = collect_report(shm_fd, ready_read, os.getpid(), 0.05)
        elapsed = time.monotonic() - started
        assert code == 3 and report["collector"]["phase"] == "ready_timeout", report
        assert elapsed < 0.5, f"readiness timeout exceeded budget: {elapsed:.3f}s"

        os.close(ready_write)
        ready_write = -1
        started = time.monotonic()
        code, report = collect_report(shm_fd, ready_read, os.getpid(), 0.5)
        assert code == 2 and report["collector"]["phase"] == "startup", report
        assert time.monotonic() - started < 0.2, "EOF readiness result was not immediate"
    finally:
        for fd in (ready_read, ready_write, shm_fd):
            if fd >= 0:
                os.close(fd)


def check_idle_agent_connection() -> None:
    baseline_fds = _fd_count()
    with tempfile.TemporaryDirectory(prefix="faultdebug-agent-bounded-") as raw:
        root = pathlib.Path(raw)
        socket_path = root / "agent.sock"
        server = AgentServer(socket_path, root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        idle: socket.socket | None = None
        try:
            deadline = time.monotonic() + 2
            while not socket_path.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            assert socket_path.exists(), "agent did not bind its socket"

            idle = _connect_when_listening(socket_path)
            time.sleep(0.05)
            started = time.monotonic()
            response = AgentClient(socket_path, timeout=1.5).status()
            elapsed = time.monotonic() - started
            assert response["state"] == "running", response
            assert elapsed < 0.8, f"idle peer blocked follow-on request for {elapsed:.3f}s"
            idle.settimeout(0.5)
            assert idle.recv(1) == b"", "server did not close a timed-out idle request"
            assert server._status_generation > 0

            # A second idle connection must not prevent stop from completing.
            idle.close()
            idle = _connect_when_listening(socket_path)
            time.sleep(0.05)
            server.stop()
            thread.join(0.8)
            assert not thread.is_alive(), "agent shutdown exceeded the idle-request bound"
            assert not socket_path.exists(), "agent socket remained after shutdown"
        finally:
            if idle is not None:
                idle.close()
            server.stop()
            if thread.is_alive():
                # Release a pending accept/receive so the test cannot leak a thread
                # even when an assertion documents a regression.
                try:
                    release = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    release.connect(str(socket_path))
                    release.close()
                except OSError:
                    pass
                thread.join(1)
        assert not thread.is_alive(), "agent server thread leaked"
    final_fds = _fd_count()
    if baseline_fds >= 0 and final_fds >= 0:
        assert final_fds == baseline_fds, f"agent/collector FD leak: {baseline_fds} -> {final_fds}"
    assert AGENT_REQUEST_TIMEOUT_SECONDS <= 0.5


def main() -> int:
    check_collector_deadlines()
    check_idle_agent_connection()
    print("collector-agent-bounded: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
