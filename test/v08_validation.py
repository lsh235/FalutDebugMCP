#!/usr/bin/env python3
"""Independent v0.8 session/collector acceptance checks.

This gate creates expected relations in the fixture instead of using analyzer
output as its oracle. Two peers publish one explicit RPC endpoint pair and a
third process publishes a partial crash artifact without an RPC event. Resident
agent registration/restart and evidence-store quarantine are exercised through
their documented APIs; only unavailable optional regression inputs are NOT RUN.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.aggregate import ArtifactIndex  # noqa: E402
from faultdebug.artifact import HEADER, read_artifact, write_artifact  # noqa: E402
from faultdebug.discovery import inspect_spool  # noqa: E402
from faultdebug.evidence_store import EvidenceStore, SCHEMA_VERSION  # noqa: E402
from faultdebug.rpc import process_relations  # noqa: E402
from faultdebug.run import run_target  # noqa: E402
from faultdebug.session import session_manifest  # noqa: E402
from faultdebug.spool import ArtifactSpool, SpoolError  # noqa: E402


def result(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    if status not in {"PASS", "FAIL", "NOT RUN"}:
        raise ValueError(f"invalid status {status!r}")
    row = {"name": name, "status": status, "reason": reason}
    row.update(extra)
    return row


_CHILD = r'''
import json, os, pathlib, signal, sys
from faultdebug.artifact import write_artifact

role, output, session_id = sys.argv[1:4]
pid = os.getpid()
participants = ["peer-a", "peer-b", "crasher"]
identity = {"schema": 1, "session_id": session_id, "process_id": role,
            "process_generation": 1, "role": role}
report = {
    "header": {"status": (1 << 9) if role == "crasher" else 0,
                "abi_version": 1},
    "session": {"schema": 1, "session_id": session_id,
                 "participant_id": role,
                 "expected_participants": participants},
    "process": {"pid": pid, "parent_pid": os.getppid(), "identity": identity},
    "target": {"returncode": -signal.SIGSEGV if role == "crasher" else 0,
                "signal": signal.SIGSEGV if role == "crasher" else None},
    "collector": {"ok": True, "status": "partial" if role == "crasher" else "complete",
                  "partial": role == "crasher"},
    "crashes": ([{"signal": signal.SIGSEGV, "address": 0,
                   "monotonic_ns": 300}] if role == "crasher" else []),
}
if role == "peer-a":
    report["rpc_trace"] = {"schema": 1, "complete": True, "events": [{
        "rpc_id": "rpc-v08-1", "phase": "send", "direction": 2,
        "pid": pid, "method_id": 7, "sequence": 1, "monotonic_ns": 100}]}
elif role == "peer-b":
    report["rpc_trace"] = {"schema": 1, "complete": True, "events": [{
        "rpc_id": "rpc-v08-1", "phase": "receive", "direction": 1,
        "pid": pid, "method_id": 7, "sequence": 1, "monotonic_ns": 200}]}
path = write_artifact(report, pathlib.Path(output), pid)
print(json.dumps({"role": role, "pid": pid, "artifact": str(path)}), flush=True)
if role == "crasher":
    os.kill(pid, signal.SIGSEGV)
'''


def _three_process_fixture(work: pathlib.Path) -> dict[str, Any]:
    """Run two peers and one real SIGSEGV child and verify explicit joins."""
    artifact_root = work / "three-process-artifacts"
    artifact_root.mkdir(parents=True)
    session_id = "v08-session-fixed"
    roles = ("peer-a", "peer-b", "crasher")
    children: list[tuple[str, subprocess.Popen[str]]] = []
    for role in roles:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        child = subprocess.Popen(
            [sys.executable, "-c", _CHILD, role, str(artifact_root), session_id],
            cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        children.append((role, child))

    rows: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for role, child in children:
        stdout, stderr = child.communicate(timeout=30)
        lines = [line for line in stdout.splitlines() if line.strip()]
        try:
            rows[role] = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError):
            failures.append({"role": role, "returncode": child.returncode,
                             "stdout": stdout[-500:], "stderr": stderr[-500:]})
        expected_returncode = -signal.SIGSEGV if role == "crasher" else 0
        if child.returncode != expected_returncode:
            failures.append({"role": role, "reason": "unexpected child returncode",
                             "returncode": child.returncode, "expected": expected_returncode})
    if failures or set(rows) != set(roles):
        return result("three_process_session", "FAIL",
                      "three-process fixture did not publish expected child artifacts",
                      failures=failures, rows=rows)

    reports: list[dict[str, Any]] = []
    paths: list[pathlib.Path] = []
    for role in roles:
        path = pathlib.Path(rows[role]["artifact"])
        paths.append(path)
        reports.append(read_artifact(path))
    manifest = session_manifest(reports, artifact_refs=[str(path) for path in paths])
    relations = process_relations(reports)
    pid_by_role = {role: int(rows[role]["pid"]) for role in roles}
    relation_pairs = {(row.get("from_pid"), row.get("to_pid"))
                      for row in relations["observed"]}
    expected_pair = {(pid_by_role["peer-a"], pid_by_role["peer-b"])}
    participants = {row.get("participant_id") for row in manifest["participants"]}
    if manifest["session"].get("session_id") != session_id:
        return result("three_process_session", "FAIL", "explicit session identity was not retained",
                      manifest=manifest)
    if participants != set(roles):
        return result("three_process_session", "FAIL", "participant identity was lost or inferred",
                      participants=sorted(participants), expected=sorted(roles))
    if relation_pairs != expected_pair or len(relations["observed"]) != 1:
        return result("three_process_session", "FAIL",
                      "explicit peer relation did not match independent role expectation",
                      observed=relations["observed"], unresolved=relations["unresolved"],
                      expected_pairs=sorted(expected_pair))
    if any(pid_by_role["crasher"] in pair for pair in relation_pairs):
        return result("three_process_session", "FAIL",
                      "crasher was incorrectly promoted to a causal endpoint", relations=relations)
    crash_report = reports[roles.index("crasher")]
    if crash_report.get("collector", {}).get("partial") is not True:
        return result("three_process_session", "FAIL", "crash artifact did not retain partial status",
                      collector=crash_report.get("collector"))
    return result("three_process_session", "PASS",
                  "two peers and one crashing process produced explicit session evidence",
                  session_id=session_id, participants=sorted(participants),
                  relation_pairs=[list(pair) for pair in sorted(relation_pairs)],
                  crash_signal=crash_report.get("target", {}).get("signal"))


def _store_pagination_reopen(work: pathlib.Path) -> dict[str, Any]:
    """Check bounded spool rotation and restartable SQLite pagination."""
    source = work / "store-source"
    spool_root = work / "store"
    source.mkdir()
    for pid in range(501, 506):
        write_artifact({
            "header": {"status": 0, "abi_version": 1},
            "process": {"pid": pid, "start_monotonic_ns": pid},
            "context": {"session_id": "v08-store"},
            "collector": {"ok": True, "status": "complete", "partial": False},
            "crashes": [],
        }, source, pid)
    spool = ArtifactSpool(spool_root, max_bytes=1024 * 1024, max_files=3)
    for path in sorted(source.glob("*.fault")):
        spool.ingest(path)
    retained = sorted(path.name for path in spool.list_files())
    if len(retained) != 3:
        return result("store_pagination_reopen", "FAIL", "spool file quota was not enforced",
                      retained=retained)
    reopened = ArtifactSpool(spool_root, max_bytes=1024 * 1024, max_files=3)
    reopened_names = sorted(path.name for path in reopened.list_files())
    if reopened_names != retained or reopened.stats()["files"] != 3:
        return result("store_pagination_reopen", "FAIL", "reopened spool differs from retained set",
                      retained=retained, reopened=reopened_names, stats=reopened.stats())

    db = work / "artifact-index.sqlite3"
    index = ArtifactIndex(db)
    index.add([spool_root / name for name in retained])
    page_a = index.query(limit=2, offset=0)
    page_b = index.query(limit=2, offset=2)
    index.close()
    reopened_index = ArtifactIndex(db)
    all_rows = reopened_index.query(limit=10, offset=0)
    reopened_index.close()
    page_names = [pathlib.Path(row["artifact"]).name for row in page_a + page_b]
    if len(page_a) != 2 or len(page_b) != 1 or sorted(page_names) != retained:
        return result("store_pagination_reopen", "FAIL", "independent page union was incorrect",
                      page_a=page_a, page_b=page_b, retained=retained)
    reopened_names_index = sorted(pathlib.Path(row["artifact"]).name for row in all_rows)
    if reopened_names_index != retained:
        return result("store_pagination_reopen", "FAIL", "reopened index lost artifacts",
                      indexed=reopened_names_index, expected=retained)
    return result("store_pagination_reopen", "PASS",
                  "spool quota, page union, and SQLite reopen retained the expected set",
                  retained=retained, page_sizes=[len(page_a), len(page_b)])


def _malformed_corrupt(work: pathlib.Path) -> dict[str, Any]:
    """Verify corruption is visible and never admitted as a valid artifact."""
    root = work / "malformed"
    source = write_artifact({"header": {"status": 0}, "process": {"pid": 901},
                             "collector": {"ok": True}, "crashes": []}, root, 901)
    raw = source.read_bytes()
    truncated = root / "fault-truncated.fault"
    truncated.write_bytes(raw[:-1])
    checksum = root / "fault-checksum.fault"
    corrupted = bytearray(raw)
    corrupted[-1] ^= 1
    checksum.write_bytes(corrupted)
    version = root / "fault-version.fault"
    version.write_bytes(HEADER.pack(b"FDAR", 99, 0, len(raw) - HEADER.size,
                                    901, raw[20:52]) + raw[HEADER.size:])
    rejected: list[str] = []
    spool = ArtifactSpool(work / "malformed-spool", max_bytes=1024 * 1024, max_files=8)
    for path in (truncated, checksum, version):
        try:
            read_artifact(path)
        except Exception:
            rejected.append(path.name)
        try:
            spool.ingest(path)
        except SpoolError:
            pass
        else:
            return result("malformed_corrupt_artifact", "FAIL",
                          "corrupt artifact was admitted to the spool", path=path.name)
    discovered = inspect_spool(root)
    invalid = {row["path"] for row in discovered["artifacts"] if row["status"] == "FAIL"}
    expected = {truncated.name, checksum.name, version.name}
    if set(rejected) != expected or not expected <= invalid:
        return result("malformed_corrupt_artifact", "FAIL",
                      "corrupt artifacts were accepted or not surfaced",
                      rejected=rejected, invalid=sorted(invalid))
    return result("malformed_corrupt_artifact", "PASS",
                  "truncated, checksum, and version-mismatch files were rejected and diagnosed",
                  rejected=sorted(rejected), valid_files=spool.stats()["files"])


_AGENT_TARGET = r'''
import os, signal, sys, time
fd = int(os.environ["FAULTDEBUG_READY_FD"])
os.write(fd, b"R")
os.close(fd)
role = sys.argv[1]
if role == "crasher":
    time.sleep(0.8)
    os.kill(os.getpid(), signal.SIGSEGV)
else:
    time.sleep(3.0)
'''


def _start_agent(work: pathlib.Path) -> tuple[subprocess.Popen[str], pathlib.Path, pathlib.Path]:
    spool_root = work / "agent" / "spool"
    socket_path = spool_root / "collector.sock"
    status_path = spool_root / "status.json"
    spool_root.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [sys.executable, "-m", "faultdebug.cli", "agent", "--socket", str(socket_path),
         "--spool-root", str(spool_root), "--status-path", str(status_path)],
        cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    from faultdebug.agent import AgentClient
    client = AgentClient(socket_path, timeout=1.0)
    deadline = time.monotonic() + 10.0
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"agent exited during startup: {process.returncode}: {stderr[-500:]}")
            try:
                client.status()
                return process, socket_path, spool_root
            except Exception:
                time.sleep(0.05)
        raise RuntimeError("agent socket did not become ready")
    except Exception:
        _stop_agent(process)
        raise


def _stop_agent(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _resident_agent_api(work: pathlib.Path) -> dict[str, Any]:
    """Exercise the real Unix socket/SCM_RIGHTS resident-agent contract."""
    if importlib.util.find_spec("faultdebug.agent") is None:
        return result("resident_agent_api", "NOT RUN", "faultdebug.agent module is unavailable")
    agent = None
    try:
        agent, socket_path, spool_root = _start_agent(work)
        from faultdebug.agent import AgentClient
        client = AgentClient(socket_path, timeout=3.0)
        roles = ("peer-a", "peer-b", "crasher")
        session_id = "v08-agent-session"
        target = work / "agent-target.py"
        target.write_text(_AGENT_TARGET)
        launch_dir = work / "agent-launch-artifacts"
        launch_dir.mkdir()

        def launch(role: str) -> dict[str, Any]:
            return run_target([sys.executable, str(target), role], artifact_dir=launch_dir / role,
                              identity={"session_id": session_id, "process_id": role,
                                        "process_generation": 1, "role": role},
                              agent_socket=socket_path)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(launch, role) for role in roles]
            reports = [future.result(timeout=30) for future in futures]
        status_before = client.status()
        artifacts = sorted(spool_root.glob("*.fault"))
        if len(artifacts) != 3:
            return result("resident_agent_api", "FAIL",
                          "agent did not publish one trigger and two peer snapshots",
                          artifacts=[str(path) for path in artifacts], reports=reports)
        captured = [read_artifact(path) for path in artifacts]
        manifest = session_manifest(captured, artifact_refs=[str(path) for path in artifacts])
        relation = process_relations(captured)
        participants = {row.get("participant_id") for row in manifest["participants"]}
        expected = set(roles)
        signals = sorted(
            ((report.get("target") or {}).get("signal") for report in captured),
            key=lambda value: -1 if value is None else value,
        )
        if manifest["session"].get("session_id") != session_id or participants != expected:
            return result("resident_agent_api", "FAIL",
                          "agent snapshots lost explicit session/process identity",
                          session=manifest.get("session"), participants=sorted(participants))
        if relation["observed"]:
            return result("resident_agent_api", "FAIL",
                          "agent promoted shared session identity into an unobserved causal relation",
                          relations=relation)
        if signals != [None, None, signal.SIGSEGV]:
            return result("resident_agent_api", "FAIL",
                          "agent trigger/peer signal roles were not preserved", signals=signals)
        if not all((report.get("collector") or {}).get("phase") == "incident_snapshot"
                   for report in captured):
            return result("resident_agent_api", "FAIL",
                          "peer snapshots did not retain incident_snapshot phase",
                          collectors=[report.get("collector") for report in captured])

        _stop_agent(agent)
        agent = None
        restarted, restarted_socket, restarted_spool = _start_agent(work)
        try:
            restarted_status = AgentClient(restarted_socket).status()
            retained = sorted(restarted_spool.glob("*.fault"))
        finally:
            _stop_agent(restarted)
        if int(restarted_status.get("generation", 0)) <= int(status_before.get("generation", 0)):
            return result("resident_agent_api", "FAIL", "agent restart did not advance status generation",
                          before=status_before, after=restarted_status)
        if [path.name for path in retained] != [path.name for path in artifacts]:
            return result("resident_agent_api", "FAIL", "agent restart did not retain the spool",
                          before=[path.name for path in artifacts], after=[path.name for path in retained])
        return result("resident_agent_api", "PASS",
                      "SCM_RIGHTS registration, two peer snapshots, crash trigger, no inferred relation, and restart passed",
                      artifacts=len(artifacts), participants=sorted(participants),
                      generation_before=status_before.get("generation"),
                      generation_after=restarted_status.get("generation"))
    except (OSError, RuntimeError, ValueError, TimeoutError, concurrent.futures.TimeoutError) as exc:
        return result("resident_agent_api", "FAIL", f"resident agent fixture failed: {exc}")
    finally:
        if agent is not None:
            _stop_agent(agent)


def _evidence_store_contract(work: pathlib.Path) -> dict[str, Any]:
    """Check schema-v2 pagination, restart, trust classes, and quarantine."""
    expected = {"build_id": "v08-build", "binary_sha256": "b" * 64,
                "source_sha256": "s" * 64, "index_sha256": "i" * 64}
    artifacts = work / "evidence-artifacts"
    artifacts.mkdir()

    def make(session: str, process: str, pid: int, provenance: bool = True) -> pathlib.Path:
        report = {
            "header": {"status": 0, "abi_version": 1},
            "session": {"schema": 1, "session_id": session, "participant_id": process},
            "process": {"pid": pid, "parent_pid": 1, "start_monotonic_ns": pid,
                        "identity": {"schema": 1, "session_id": session,
                                      "process_id": process, "process_generation": 1,
                                      "role": process}},
            "target": {"returncode": 0, "signal": None},
            "collector": {"ok": True, "status": "complete", "partial": False},
            "crashes": [],
        }
        if provenance:
            report["provenance"] = dict(expected)
        return write_artifact(report, artifacts, pid)

    try:
        first = make("v08-store-a", "store-a", 601)
        second = make("v08-store-b", "store-b", 602, provenance=False)
        db = work / "evidence.sqlite3"
        with EvidenceStore(db) as store:
            trusted = store.ingest(first, expected=expected)
            unresolved = store.ingest(second)
            page0 = store.list_sessions(page=0, limit=1)
            page1 = store.list_sessions(page=1, limit=1)
            selected = store.get_session("v08-store-a", page=0, limit=1)
            corrupt = artifacts / "corrupt.fault"
            corrupt.write_bytes(first.read_bytes()[:-1])
            quarantined = store.ingest(corrupt)
            quarantine_rows = store.quarantine_rows()
        with EvidenceStore(db) as reopened:
            after_restart = reopened.list_sessions(page=0, limit=10)
        if trusted.get("trust_state") != "verified" or unresolved.get("trust_state") != "unresolved":
            return result("evidence_store_contract", "FAIL", "trust state classification changed",
                          trusted=trusted, unresolved=unresolved)
        if page0.get("schema") != SCHEMA_VERSION or page0.get("total") != 2:
            return result("evidence_store_contract", "FAIL", "session page metadata is incorrect",
                          page0=page0)
        if len(page0.get("sessions", [])) != 1 or len(page1.get("sessions", [])) != 1:
            return result("evidence_store_contract", "FAIL", "session pagination did not split independently",
                          page0=page0, page1=page1)
        if selected.get("derived", {}).get("process_relations"):
            return result("evidence_store_contract", "FAIL",
                          "store inferred a relation without explicit endpoint evidence", selected=selected)
        if quarantined.get("status") != "quarantined" or quarantine_rows.get("total") != 1:
            return result("evidence_store_contract", "FAIL", "corrupt artifact was not quarantined",
                          quarantined=quarantined, rows=quarantine_rows)
        if after_restart.get("total") != 2:
            return result("evidence_store_contract", "FAIL", "store reopen lost valid sessions",
                          reopened=after_restart)
        return result("evidence_store_contract", "PASS",
                      "schema-v2 trust classes, page pagination, reopen, and corruption quarantine passed",
                      pages=[len(page0["sessions"]), len(page1["sessions"])],
                      quarantine=quarantine_rows.get("total"))
    except Exception as exc:
        return result("evidence_store_contract", "FAIL", f"evidence store contract failed: {exc}")


def _agent_native_regression(build_dir: pathlib.Path | None) -> dict[str, Any]:
    """Replay the focused native FDAR/agent check when a fixture build exists."""
    if build_dir is None:
        return result("agent_native_regression", "NOT RUN", "--build-dir was not supplied")
    peer_binary = build_dir / "test" / "fd_soak"
    trigger_binary = build_dir / "test" / "fd_signals"
    if not peer_binary.is_file() or not trigger_binary.is_file():
        return result("agent_native_regression", "NOT RUN", "native peer/trigger fixtures are unavailable",
                      peer_binary=str(peer_binary), trigger_binary=str(trigger_binary))
    completed = subprocess.run(
        [sys.executable, str(ROOT / "test" / "agent_test.py"),
         "--peer-binary", str(peer_binary), "--trigger-binary", str(trigger_binary)],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    if completed.returncode != 0:
        return result("agent_native_regression", "FAIL", "native agent regression failed",
                      returncode=completed.returncode, stdout=completed.stdout[-1000:],
                      stderr=completed.stderr[-1000:])
    return result("agent_native_regression", "PASS",
                  "focused native agent/FDAR check passed", stdout=completed.stdout[-1000:])


def _v07_regression(work: pathlib.Path, build_dir: pathlib.Path | None,
                    grpc_build_dir: pathlib.Path | None) -> dict[str, Any]:
    output = work / "v07-regression"
    command = [sys.executable, str(ROOT / "test" / "v07_validation.py"),
               "--output", str(output)]
    if build_dir is not None:
        command.extend(["--build-dir", str(build_dir)])
    if grpc_build_dir is not None:
        command.extend(["--grpc-build-dir", str(grpc_build_dir)])
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True,
                                   capture_output=True, timeout=240)
    except Exception as exc:
        return result("v07_regression", "FAIL", f"v0.7 regression command failed to run: {exc}")
    report_path = output / "report.json"
    if not report_path.is_file():
        return result("v07_regression", "FAIL", "v0.7 regression did not emit report",
                      returncode=completed.returncode, stderr=completed.stderr[-1000:])
    try:
        report = json.loads(report_path.read_text())
    except Exception as exc:
        return result("v07_regression", "FAIL", f"v0.7 report is not JSON: {exc}")
    status = report.get("status")
    if status not in {"PASS", "FAIL", "NOT RUN"}:
        status = "FAIL"
    return result("v07_regression", status, "existing v0.7 gate replayed without changing expectations",
                  returncode=completed.returncode, checks=report.get("checks", []),
                  stderr=completed.stderr[-1000:])


def main() -> int:
    parser = argparse.ArgumentParser(description="independent v0.8 validation")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--build-dir", type=pathlib.Path,
                        help="native fixture build directory for v0.7 regression")
    parser.add_argument("--grpc-build-dir", type=pathlib.Path,
                        help="optional gRPC fixture build directory for v0.7 regression")
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="faultdebug-v08-") as raw:
        work = pathlib.Path(raw)
        checks = [
            _three_process_fixture(work),
            _store_pagination_reopen(work),
            _malformed_corrupt(work),
            _resident_agent_api(work),
            _evidence_store_contract(work),
            _agent_native_regression(ns.build_dir),
            _v07_regression(work, ns.build_dir, ns.grpc_build_dir),
        ]
    statuses = [item["status"] for item in checks]
    overall = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "version": "0.8.0", "status": overall, "checks": checks}
    path = ns.output / "report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    counts = {state: statuses.count(state) for state in ("PASS", "FAIL", "NOT RUN")}
    print(json.dumps({"status": overall, "checks": counts, "report": str(path)}, sort_keys=True))
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
