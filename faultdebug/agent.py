"""Resident local collector agent using a restricted Unix socket.

The agent is deliberately local and bounded.  A launcher registers one
process by passing its shared-memory memfd with ``SCM_RIGHTS``.  A later fault
notification causes the agent to snapshot registered peers in the same session
and publish each snapshot through :class:`ArtifactSpool`.
"""
from __future__ import annotations

import argparse
import array
import json
import mmap
import os
import re
import select
import signal
import socket
import stat
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact import ArtifactError, write_artifact
from .collector import _atomic_json
from .format import HEADER, collect_mapping
from .session import ProcessIdentity, SESSION_SCHEMA, SessionIdentityError
from .spool import ArtifactSpool, SpoolError

MAX_MESSAGE_BYTES = 16 * 1024
AGENT_REQUEST_TIMEOUT_SECONDS = 0.25
SOCKET_MODE = 0o600
ROOT_MODE = 0o700
SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")


class AgentError(RuntimeError):
    pass


@dataclass
class Registration:
    identity: ProcessIdentity
    pid: int
    parent_pid: int
    owner_pid: int
    shm_fd: int
    registered_monotonic_ns: int

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.identity.session_id, self.identity.process_id, self.identity.process_generation)


def _peer_pid(conn: socket.socket) -> int:
    """Return the authenticated Unix peer PID, failing closed elsewhere."""
    if not hasattr(socket, "SO_PEERCRED"):
        raise AgentError("SO_PEERCRED is unavailable on this platform")
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, _uid, _gid = struct.unpack("3i", raw)
    if pid <= 0:
        raise AgentError("invalid Unix peer credentials")
    return pid


def _pid_parent(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        return None
    return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # kill(0) also succeeds for zombies.  A zombie no longer has a usable
        # shared-memory owner, so treat it as unavailable for peer snapshots.
        state = None
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("State:"):
                state = line.split()[1]
                break
        if state == "Z":
            return False
        os.kill(pid, 0)
    except (FileNotFoundError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def _safe_component(value: str, field: str) -> str:
    if not SAFE_COMPONENT.fullmatch(value):
        raise AgentError(f"{field} cannot be used in a local artifact name")
    return value


def _identity_from_request(request: dict[str, Any]) -> tuple[ProcessIdentity, int, int]:
    session = request.get("session")
    process = request.get("process")
    if not isinstance(session, dict) or not isinstance(process, dict):
        raise AgentError("session and process objects are required")
    if session.get("schema", SESSION_SCHEMA) != SESSION_SCHEMA:
        raise AgentError("unsupported session schema")
    identity = process.get("identity") if isinstance(process.get("identity"), dict) else process
    if not isinstance(identity, dict):
        raise AgentError("process.identity must be an object")
    session_id = session.get("session_id")
    if session_id != identity.get("session_id"):
        raise AgentError("session and process identity IDs do not match")
    try:
        result = ProcessIdentity(
            session_id=str(identity["session_id"]),
            process_id=str(identity["process_id"]),
            process_generation=int(identity.get("process_generation", 1)),
            parent_process_id=identity.get("parent_process_id"),
            role=identity.get("role"),
        )
    except (KeyError, TypeError, ValueError, SessionIdentityError) as exc:
        raise AgentError(f"invalid process identity: {exc}") from exc
    try:
        pid = int(process["pid"])
        parent_pid = int(process.get("parent_pid", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentError("process pid and parent_pid are required") from exc
    if pid <= 0 or parent_pid <= 0:
        raise AgentError("process pid and parent_pid must be positive")
    _safe_component(result.process_id, "process_id")
    _safe_component(result.session_id, "session_id")
    return result, pid, parent_pid


class AgentServer:
    """Single-threaded bounded local agent.

    Requests are handled serially so registration maps and memfd ownership do
    not require a second synchronization domain.  The server is suitable for a
    local supervisor process; it does not accept remote or TCP connections.
    """

    def __init__(self, socket_path: Path, spool_root: Path, *, max_bytes: int = 64 * 1024 * 1024,
                 max_files: int = 1000, status_path: Path | None = None) -> None:
        self.spool_root = Path(spool_root).resolve()
        self.socket_path = Path(socket_path).resolve()
        try:
            if os.path.commonpath((str(self.spool_root), str(self.socket_path))) != str(self.spool_root):
                raise AgentError("socket path must be under spool root")
        except ValueError as exc:
            raise AgentError("socket path and spool root must share a filesystem root") from exc
        self.spool_root.mkdir(parents=True, exist_ok=True, mode=ROOT_MODE)
        os.chmod(self.spool_root, ROOT_MODE)
        self.status_path = Path(status_path or (self.spool_root / "agent-status.json")).resolve()
        if os.path.commonpath((str(self.spool_root), str(self.status_path))) != str(self.spool_root):
            raise AgentError("status path must be under spool root")
        self.spool = ArtifactSpool(self.spool_root, max_bytes=max_bytes, max_files=max_files)
        self.staging_root = self.spool_root / ".agent-staging"
        self.staging_root.mkdir(mode=ROOT_MODE, exist_ok=True)
        os.chmod(self.staging_root, ROOT_MODE)
        self.registrations: dict[tuple[str, str, int], Registration] = {}
        self._socket: socket.socket | None = None
        self._stop = threading.Event()
        self._incident_counter = 0
        self._status_generation = self._next_generation()
        self._set_status("running", event="restarted" if self._status_generation > 1 else "started")

    def _next_generation(self) -> int:
        try:
            value = json.loads(self.status_path.read_text()).get("generation", 0)
            return max(1, int(value) + 1)
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return 1

    def _set_status(self, state: str, *, event: str | None = None, error: str | None = None,
                    incident: dict[str, Any] | None = None) -> None:
        record: dict[str, Any] = {
            "schema": SESSION_SCHEMA,
            "state": state,
            "generation": self._status_generation,
            "pid": os.getpid(),
            "updated_monotonic_ns": time.monotonic_ns(),
            "socket": str(self.socket_path),
            "spool_root": str(self.spool_root),
            "registrations": len(self.registrations),
        }
        if event:
            record["event"] = event
        if error:
            record["error"] = error[:512]
        if incident:
            record["incident"] = incident
        try:
            _atomic_json(self.status_path, record)
            os.chmod(self.status_path, 0o600)
        except OSError:
            # A status write failure must not turn a valid fault snapshot into
            # an unreported success; callers receive disk_error explicitly.
            pass

    def _bind(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True, mode=ROOT_MODE)
        os.chmod(self.socket_path.parent, ROOT_MODE)
        if self.socket_path.exists():
            if not stat.S_ISSOCK(self.socket_path.stat().st_mode):
                raise AgentError("refusing to replace a non-socket path")
            self.socket_path.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(self.socket_path))
            os.chmod(self.socket_path, SOCKET_MODE)
            sock.listen(32)
            sock.settimeout(0.25)
        except Exception:
            sock.close()
            raise
        self._socket = sock

    @property
    def registered_count(self) -> int:
        return len(self.registrations)

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self._stop.set()
        for registration in list(self.registrations.values()):
            try:
                os.close(registration.shm_fd)
            except OSError:
                pass
        self.registrations.clear()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        self._set_status("stopped", event="stopped")

    def serve_forever(self, stop_event: threading.Event | None = None) -> None:
        external_stop = stop_event
        self._bind()
        try:
            while not self._stop.is_set() and not (external_stop and external_stop.is_set()):
                try:
                    conn, _ = self._socket.accept() if self._socket is not None else (None, None)
                except socket.timeout:
                    continue
                except OSError as exc:
                    if self._stop.is_set():
                        break
                    self._set_status("error", event="accept_error", error=str(exc))
                    continue
                if conn is None:
                    continue
                with conn:
                    self._handle_connection(conn)
        finally:
            self.close()

    def _receive(self, conn: socket.socket) -> tuple[dict[str, Any], list[int], int]:
        data, ancillary, flags, _address = conn.recvmsg(
            MAX_MESSAGE_BYTES, socket.CMSG_SPACE(8 * array.array("i").itemsize)
        )
        fds: list[int] = []
        for level, kind, payload in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array("i")
                values.frombytes(payload[:len(payload) - (len(payload) % values.itemsize)])
                fds.extend(int(value) for value in values)
        try:
            if flags & getattr(socket, "MSG_CTRUNC", 0):
                raise AgentError("agent ancillary data was truncated")
            if not data or len(data) > MAX_MESSAGE_BYTES:
                raise AgentError("empty or oversized agent request")
            try:
                request = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AgentError("agent request is not valid JSON") from exc
            if not isinstance(request, dict):
                raise AgentError("agent request must be an object")
            return request, fds, _peer_pid(conn)
        except Exception:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise

    @staticmethod
    def _reply(conn: socket.socket, value: dict[str, Any]) -> None:
        conn.sendall((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())

    def _authorize_registration(self, pid: int, parent_pid: int, peer_pid: int) -> None:
        if pid == peer_pid:
            return
        if parent_pid != peer_pid or _pid_parent(pid) != peer_pid:
            raise AgentError("peer credentials do not match registered process or parent")

    def _handle_connection(self, conn: socket.socket) -> None:
        fds: list[int] = []
        owned_fd: int | None = None
        try:
            conn.settimeout(AGENT_REQUEST_TIMEOUT_SECONDS)
            request, fds, peer_pid = self._receive(conn)
            operation = request.get("op")
            if operation == "register":
                if len(fds) != 1:
                    raise AgentError("register requires exactly one shared-memory FD")
                identity, pid, parent_pid = _identity_from_request(request)
                self._authorize_registration(pid, parent_pid, peer_pid)
                shm_fd = fds[0]
                owned_fd = shm_fd
                if os.fstat(shm_fd).st_size < HEADER.size:
                    raise AgentError("shared-memory FD is shorter than the ABI header")
                key = (identity.session_id, identity.process_id, identity.process_generation)
                if key in self.registrations:
                    raise AgentError("process identity is already registered")
                self.registrations[key] = Registration(identity, pid, parent_pid, peer_pid, shm_fd, time.monotonic_ns())
                owned_fd = None
                self._set_status("running", event="registered")
                self._reply(conn, {"ok": True, "state": "registered", "session_id": identity.session_id,
                                    "process_id": identity.process_id, "process_generation": identity.process_generation})
            elif operation == "unregister":
                identity, pid, parent_pid = _identity_from_request(request)
                key = (identity.session_id, identity.process_id, identity.process_generation)
                registration = self.registrations.get(key)
                if registration is None:
                    self._reply(conn, {"ok": True, "state": "absent", "process_id": identity.process_id})
                elif peer_pid != registration.owner_pid:
                    raise AgentError("unregister peer is not the registration owner")
                else:
                    self.registrations.pop(key, None)
                    os.close(registration.shm_fd)
                    self._set_status("running", event="unregistered")
                    self._reply(conn, {"ok": True, "state": "unregistered", "process_id": identity.process_id})
            elif operation == "fault":
                identity, _pid, _parent_pid = _identity_from_request(request)
                signal_number = int(request.get("signal", 0))
                if signal_number <= 0 or signal_number > 255:
                    raise AgentError("fault signal must be between 1 and 255")
                key = (identity.session_id, identity.process_id, identity.process_generation)
                registration = self.registrations.get(key)
                if registration is None:
                    raise AgentError("fault process is not registered")
                if peer_pid != registration.owner_pid:
                    raise AgentError("fault peer is not the registration owner")
                result = self._snapshot_incident(registration, signal_number)
                self._reply(conn, result)
            elif operation == "status":
                self._reply(conn, {"ok": True, "state": "running", "registrations": len(self.registrations),
                                    "generation": self._status_generation})
            else:
                raise AgentError("unsupported agent operation")
        except socket.timeout:
            # An accepted peer that never sends a request is not an agent
            # failure. Closing it lets the serial server accept the next peer
            # and observe shutdown within the same bounded deadline.
            return
        except Exception as exc:
            self._set_status("error", event="request_error", error=str(exc))
            try:
                self._reply(conn, {"ok": False, "state": "error", "error": str(exc)[:512]})
            except OSError:
                pass
        finally:
            if owned_fd is not None:
                try:
                    os.close(owned_fd)
                except OSError:
                    pass
            for fd in fds:
                if fd != owned_fd and not any(registration.shm_fd == fd for registration in self.registrations.values()):
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    def _snapshot_one(self, registration: Registration, *, incident_id: str, trigger: Registration,
                      signal_number: int, peer: bool) -> Path:
        with mmap.mmap(registration.shm_fd, os.fstat(registration.shm_fd).st_size, access=mmap.ACCESS_READ) as mapping:
            report = collect_mapping(mapping)
        report["session"] = registration.identity.session_record()
        report["process"] = {
            "pid": registration.pid,
            "parent_pid": registration.parent_pid,
            "identity": registration.identity.process_record(pid=registration.pid, parent_pid=registration.parent_pid),
        }
        report["target"] = {"returncode": -signal_number if not peer else None,
                             "signal": signal_number if not peer else None}
        report["collector"] = {
            "ok": True,
            "status": "limited",
            "phase": "incident_snapshot",
            "incident_id": incident_id,
            "trigger_process_id": trigger.identity.process_id,
            "trigger_signal": signal_number,
            "partial": True,
        }
        report["evidence_class"] = "incident_snapshot" if peer else "observed"
        stem = f"fault-{_safe_component(registration.identity.process_id, 'process_id')}-g{registration.identity.process_generation}-{incident_id}"
        source = write_artifact(report, self.staging_root, registration.pid, artifact_stem=stem)
        try:
            return self.spool.ingest(source)
        finally:
            try:
                source.unlink()
            except FileNotFoundError:
                pass

    def _snapshot_incident(self, trigger: Registration, signal_number: int) -> dict[str, Any]:
        self._incident_counter += 1
        incident_id = f"incident-{trigger.identity.session_id}-{time.monotonic_ns()}-{self._incident_counter}"
        artifacts: list[str] = []
        unavailable: list[str] = []
        errors: list[dict[str, str]] = []
        same_session = [row for row in self.registrations.values()
                        if row.identity.session_id == trigger.identity.session_id]
        for registration in same_session:
            is_trigger = registration.key == trigger.key
            if not is_trigger and not _pid_alive(registration.pid):
                unavailable.append(registration.identity.process_id)
                continue
            try:
                artifacts.append(str(self._snapshot_one(registration, incident_id=incident_id,
                                                        trigger=trigger, signal_number=signal_number,
                                                        peer=not is_trigger)))
            except (OSError, ArtifactError, SpoolError, ValueError) as exc:
                errors.append({"process_id": registration.identity.process_id, "error": str(exc)[:512]})
        status = "disk_error" if errors else ("peer_unavailable" if unavailable else "limited")
        result = {
            "ok": not errors,
            "status": status,
            "phase": "incident_snapshot",
            "incident_id": incident_id,
            "trigger_process_id": trigger.identity.process_id,
            "trigger_signal": signal_number,
            "partial": True,
            "artifacts": artifacts,
            "peer_count": max(0, len(same_session) - 1),
            "unavailable_process_ids": unavailable,
            "errors": errors,
        }
        self._set_status("disk_error" if errors else "running", event="incident_snapshot", error=(errors[0]["error"] if errors else None), incident=result)
        return result


class AgentClient:
    """Client for registration, fault notification, and cleanup."""

    def __init__(self, socket_path: Path, *, timeout: float = 2.0) -> None:
        self.socket_path = Path(socket_path)
        self.timeout = timeout

    def _request(self, request: dict[str, Any], *, fd: int | None = None) -> dict[str, Any]:
        payload = (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(payload) > MAX_MESSAGE_BYTES:
            raise AgentError("agent request is too large")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self.socket_path))
            if fd is None:
                sock.sendall(payload)
            else:
                sock.sendmsg([payload], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))])
            response = sock.recv(MAX_MESSAGE_BYTES)
        except (OSError, TimeoutError) as exc:
            raise AgentError(f"agent unavailable: {exc}") from exc
        finally:
            sock.close()
        if not response:
            raise AgentError("agent returned no response")
        try:
            result = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentError("agent returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise AgentError("agent response must be an object")
        if result.get("ok") is not True:
            raise AgentError(str(result.get("error", "agent request failed")))
        return result

    def register(self, identity: ProcessIdentity, *, pid: int, parent_pid: int, shm_fd: int) -> dict[str, Any]:
        request = {"op": "register", "session": identity.session_record(),
                   "process": {"identity": identity.process_record(pid=pid, parent_pid=parent_pid),
                               "pid": pid, "parent_pid": parent_pid}}
        return self._request(request, fd=shm_fd)

    def unregister(self, identity: ProcessIdentity, *, pid: int, parent_pid: int) -> dict[str, Any]:
        request = {"op": "unregister", "session": identity.session_record(),
                   "process": {"identity": identity.process_record(pid=pid, parent_pid=parent_pid),
                               "pid": pid, "parent_pid": parent_pid}}
        return self._request(request)

    def notify_fault(self, identity: ProcessIdentity, *, pid: int, parent_pid: int, signal_number: int) -> dict[str, Any]:
        request = {"op": "fault", "session": identity.session_record(),
                   "process": {"identity": identity.process_record(pid=pid, parent_pid=parent_pid),
                               "pid": pid, "parent_pid": parent_pid},
                   "signal": signal_number}
        return self._request(request)

    def status(self) -> dict[str, Any]:
        return self._request({"op": "status"})


def serve(socket_path: Path, spool_root: Path, *, max_bytes: int = 64 * 1024 * 1024,
          max_files: int = 1000, status_path: Path | None = None) -> int:
    stop = threading.Event()
    server = AgentServer(socket_path, spool_root, max_bytes=max_bytes, max_files=max_files,
                         status_path=status_path)
    def _stop(_signal: int, _frame: Any) -> None:
        stop.set()
        server.stop()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        server.serve_forever(stop)
    except (AgentError, OSError, SpoolError) as exc:
        server._set_status("error", event="startup_error", error=str(exc))
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="faultdebug-agent")
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--spool-root", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-files", type=int, default=1000)
    parser.add_argument("--status-path", type=Path)
    ns = parser.parse_args()
    return serve(ns.socket, ns.spool_root, max_bytes=ns.max_bytes, max_files=ns.max_files,
                 status_path=ns.status_path)


if __name__ == "__main__":
    raise SystemExit(main())
