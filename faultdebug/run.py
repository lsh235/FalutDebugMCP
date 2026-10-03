from __future__ import annotations
import argparse, json, mmap, os, selectors, signal, subprocess, tempfile, time, select
from pathlib import Path
from .format import (FormatError, HEADER, THREAD, EVENT, MODULE, CRASH,
                     RPC_HEADER, RPC_EVENT, RPC_MAX_EVENTS, RPC_SIDECAR_OFFSET,
                     collect_mapping, STATUS_CRASHED, STATUS_PARTIAL)
from .artifact import write_artifact
from .context import context_to_env, normalize_context
from .collector import register_process, unregister_process
from .agent import AgentClient, AgentError
from .session import ProcessIdentity, identity_from_env, identity_to_env

THREAD_CAPACITY, EVENT_CAPACITY, MODULE_CAPACITY, CRASH_CAPACITY = 64, 4096, 256, 2
RING_SIZE = THREAD.size + EVENT.size * EVENT_CAPACITY
# ABI v1 stays at V1_SHARED_SIZE.  The launcher reserves the optional sidecar
# after its canonical aligned offset; older runtimes/readers ignore the
# zero-filled extension, while v0.4 can publish bounded numeric RPC events.
SHM_SIZE = RPC_SIDECAR_OFFSET + RPC_HEADER.size + RPC_MAX_EVENTS * RPC_EVENT.size

def _runtime_environment(argv: list[str]) -> dict[str, str]:
    env = os.environ.copy()
    candidates = []
    if env.get("FAULTDEBUG_RUNTIME_DIR"): candidates.append(Path(env["FAULTDEBUG_RUNTIME_DIR"]))
    target = Path(argv[0]).resolve()
    # A fixture may live in a separate build tree while cwd/build contains an
    # older runtime.  Prefer the target's own directory and build parent so
    # newly exported producer symbols (for example attempt-aware RPC APIs)
    # cannot resolve against a stale library.  The explicit environment
    # override remains the highest-priority choice.
    candidates.extend([target.parent, target.parent.parent,
                       Path.cwd() / "build", Path.cwd() / "out"])
    runtime_dir = next((p.resolve() for p in candidates if (p / "libfaultdebug_runtime.so").is_file()), None)
    if runtime_dir:
        current = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = str(runtime_dir) + ((os.pathsep + current) if current else "")
    return env

def run_target(argv: list[str], timeout: float | None = None, artifact_dir: Path | None = None,
               context: dict | None = None, identity: dict | ProcessIdentity | None = None,
               agent_socket: Path | None = None, collect_success: bool = False) -> dict:
    if not argv:
        raise ValueError("target command is required")
    rfd, wfd = os.pipe(); shmfd = os.memfd_create("faultdebug", os.MFD_CLOEXEC); proc = None
    target_started_ns: int | None = None
    identity_data = identity if isinstance(identity, dict) else (
        identity.process_record() if isinstance(identity, ProcessIdentity) else None
    )
    os.ftruncate(shmfd, SHM_SIZE)
    toff = HEADER.size
    moff = toff + THREAD_CAPACITY * RING_SIZE
    coff = moff + MODULE_CAPACITY * MODULE.size
    header = HEADER.pack(0x31444646, 1, HEADER.size, SHM_SIZE, 0, EVENT_CAPACITY, THREAD_CAPACITY, MODULE_CAPACITY, CRASH_CAPACITY, os.getpid(), time.monotonic_ns(), 0, 0, toff, moff, coff, 0)
    os.pwrite(shmfd, header, 0)
    context = normalize_context(context)
    env = _runtime_environment(argv)
    process_identity = identity if isinstance(identity, ProcessIdentity) else identity_from_env(identity_data, env)
    identity_to_env(process_identity, env)
    context_to_env(context, env)
    env.update({"FAULTDEBUG_SHM_FD": str(shmfd), "FAULTDEBUG_READY_FD": str(wfd)})
    registration = None
    agent_client = AgentClient(Path(agent_socket)) if agent_socket is not None else None
    agent_registered = False
    agent_result: dict[str, object] | None = None
    agent_error: dict[str, object] | None = None
    try:
        target_started_ns = time.perf_counter_ns()
        proc = subprocess.Popen(argv, env=env, pass_fds=(shmfd, wfd), close_fds=True); os.close(wfd); wfd = -1
        process = {"pid": proc.pid, "parent_pid": os.getpid(), "executable": str(Path(argv[0]).resolve()), "start_monotonic_ns": time.monotonic_ns()}
        process["identity"] = process_identity.process_record(pid=proc.pid, parent_pid=os.getpid())
        session = process_identity.session_record()
        if artifact_dir is not None:
            registration = register_process(Path(artifact_dir) / ".collector", identity=process_identity,
                                             pid=proc.pid, artifact_dir=Path(artifact_dir))
        if agent_client is not None:
            try:
                agent_client.register(process_identity, pid=proc.pid, parent_pid=os.getpid(), shm_fd=shmfd)
                agent_registered = True
            except AgentError as exc:
                agent_error = {"ok": False, "status": "agent_unavailable", "phase": "registration",
                               "error": str(exc)[:512]}
        wait_ready = timeout if timeout is not None else 10.0
        readable, _, _ = select.select([rfd], [], [], wait_ready); ready = os.read(rfd, 1) if readable else b""; os.close(rfd); rfd = -1
        if ready != b"R":
            if proc.poll() is None: proc.kill()
            proc.wait()
            collector = {"ok": False, "phase": "startup", "ready_byte": ready.decode("latin1")}
            if agent_error is not None:
                collector["agent"] = agent_error
            target_wall_ms = ((time.perf_counter_ns() - target_started_ns) / 1_000_000
                              if target_started_ns is not None else None)
            return {"session": session, "process": process, "context": context or {},
                    "target": {"returncode": proc.returncode,
                               "signal": -proc.returncode if proc.returncode < 0 else None,
                               "wall_time_ms": target_wall_ms}, "collector": collector}
        try: proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait(); partial = True
        else: partial = proc.returncode < 0
        target_wall_ms = ((time.perf_counter_ns() - target_started_ns) / 1_000_000
                          if target_started_ns is not None else None)
        if agent_client is not None and agent_registered and proc.returncode < 0:
            try:
                agent_result = agent_client.notify_fault(process_identity, pid=proc.pid,
                                                         parent_pid=os.getpid(), signal_number=-proc.returncode)
            except AgentError as exc:
                agent_error = {"ok": False, "status": "agent_unavailable", "phase": "fault_notification",
                               "error": str(exc)[:512]}
        with mmap.mmap(shmfd, SHM_SIZE, access=mmap.ACCESS_READ) as mapping: report = collect_mapping(mapping)
        partial = partial and not (report["header"]["status"] & STATUS_CRASHED)
        status = report["header"]["status"] | (STATUS_PARTIAL if partial else 0)
        report["target"] = {"returncode": proc.returncode,
                            "signal": -proc.returncode if proc.returncode < 0 else None,
                            "wall_time_ms": target_wall_ms}
        report["process"] = process
        report["session"] = session
        if context: report["context"] = context
        report["collector"] = {"ok": True, "status": status, "partial": partial}
        if agent_result is not None:
            report["collector"]["agent"] = agent_result
        if agent_error is not None:
            report["collector"]["agent"] = agent_error
        agent_artifacts = agent_result.get("artifacts", []) if agent_result else []
        if isinstance(agent_artifacts, list):
            own = [str(path) for path in agent_artifacts if process_identity.process_id in str(path)]
            if own:
                report["artifact"] = own[0]
        if artifact_dir and (status & STATUS_CRASHED or partial or collect_success) and "artifact" not in report:
            report["artifact"] = str(write_artifact(report, artifact_dir, proc.pid))
        return report
    finally:
        if agent_client is not None and agent_registered and proc is not None:
            try:
                agent_client.unregister(process_identity, pid=proc.pid, parent_pid=os.getpid())
            except AgentError:
                pass
        if registration is not None:
            unregister_process(registration)
        for fd in (rfd, wfd, shmfd):
            if fd >= 0:
                try: os.close(fd)
                except OSError: pass

def run_command(ns: argparse.Namespace) -> int:
    try:
        identity = {
            "session_id": getattr(ns, "session_id", None),
            "process_id": getattr(ns, "process_id", None),
            "process_generation": getattr(ns, "process_generation", 1),
            "role": getattr(ns, "process_role", None),
        }
        identity = {key: value for key, value in identity.items() if value is not None}
        report = run_target(ns.command, ns.timeout, Path(ns.artifact_dir) if ns.artifact_dir else None,
                            getattr(ns, "context", None), identity=identity,
                            agent_socket=Path(ns.agent_socket) if getattr(ns, "agent_socket", None) else None,
                            collect_success=bool(getattr(ns, "collect_success", False)))
    except Exception as exc:
        print(json.dumps({"collector_error": str(exc), "collector_ok": False}))
        return 2
    header = report.get("header") or {}
    threads = report.get("threads") or []
    rpc = report.get("rpc") or {}
    rpc_header = rpc.get("header") or {}
    consistency = report.get("snapshot_consistency") or {}
    trace = {
        "complete": report.get("complete"),
        "status_flags": header.get("status"),
        "thread_event_count": sum(int(row.get("event_count", 0)) for row in threads),
        "thread_dropped_count": sum(int(row.get("dropped_count", 0)) for row in threads),
        "rpc_event_count": rpc_header.get("event_count"),
        "rpc_dropped_count": rpc_header.get("dropped_count"),
        "rpc_flags": rpc_header.get("flags"),
        "snapshot_stable": consistency.get("stable"),
        "snapshot_unstable_record_count": len(consistency.get("unstable_records", [])),
    }
    print(json.dumps({"target": report.get("target"), "collector": report.get("collector"),
                      "artifact": report.get("artifact"), "trace": trace}, sort_keys=True), flush=True)
    if not report.get("collector", {}).get("ok", False): return 2
    target = report.get("target") or {}
    if target.get("signal"):
        sig = int(target["signal"])
        return 128 + sig
    return int(target.get("returncode") or 0)
