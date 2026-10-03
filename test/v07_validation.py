#!/usr/bin/env python3
"""Independent v0.7 acceptance checks.

The checks use fixed, independently constructed daemon/session records.  They
verify the evidence contract without deriving expected relations from the
product's own output.  Optional native and gRPC inputs are reported as
``NOT RUN`` when they are unavailable; a completed gate failure is ``FAIL``.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.aggregate import build_timeline, collect_artifacts  # noqa: E402
from faultdebug.artifact import HEADER, read_artifact, write_artifact  # noqa: E402
from faultdebug.context import ContextError, context_from_env, normalize_context  # noqa: E402
from faultdebug.discovery import inspect_spool  # noqa: E402
from faultdebug.rpc import incident_report  # noqa: E402
from faultdebug.spool import ArtifactSpool  # noqa: E402


def result(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    item = {"name": name, "status": status, "reason": reason}
    item.update(extra)
    return item


def _multi_daemon_session(work: pathlib.Path) -> dict[str, Any]:
    """Check a three-daemon session and only explicit IPC joins."""
    session = {"trace_id": "v07-session-001", "correlation_id": "corr-001"}
    reports: list[dict[str, Any]] = []
    paths: list[pathlib.Path] = []
    # Independent expected chain: daemon 10 -> 11 -> 12.  A shared trace ID
    # alone is deliberately insufficient evidence for either edge.
    edges = ((10, 11, "m-10-11"), (11, 12, "m-11-12"))
    per_pid = {pid: [] for pid in (10, 11, 12)}
    for sender, receiver, message_id in edges:
        per_pid[sender].append({
            "kind": "send", "message_id": message_id, "channel": "rpc-A",
            "timestamp_ns": sender * 100 + 1, "receiver_pid": receiver,
        })
        per_pid[receiver].append({
            "kind": "receive", "message_id": message_id, "channel": "rpc-A",
            "timestamp_ns": receiver * 100 + 2, "sender_pid": sender,
        })
    for pid in (10, 11, 12):
        report = {
            "header": {"status": 0, "abi_version": 1},
            "process": {"pid": pid, "parent_pid": 1, "start_monotonic_ns": pid * 1000},
            "context": {**session, "daemon": f"d{pid}"},
            "target": {"returncode": 0, "signal": None},
            "collector": {"ok": True, "status": "complete", "partial": False},
            "crashes": [],
        }
        if per_pid[pid]:
            report["context"]["ipc_events"] = per_pid[pid]
        path = write_artifact(report, work / "artifacts", pid)
        paths.append(path)
        reports.append(read_artifact(path))
    grouped = collect_artifacts(paths, trace_id=session["trace_id"])
    timeline = build_timeline(reports)
    relation_pairs = {(row["from_pid"], row["to_pid"]) for row in timeline["relations"]}
    expected_pairs = {(10, 11), (11, 12)}
    if grouped["count"] != 3 or len(grouped["groups"].get(session["trace_id"], [])) != 3:
        return result("multi_daemon_session", "FAIL", "session filter/grouping lost a daemon artifact", count=grouped["count"], groups=grouped["groups"])
    if relation_pairs != expected_pairs or len(timeline["relations"]) != 2:
        return result("multi_daemon_session", "FAIL", "explicit daemon IPC chain did not match independent expectation", relations=timeline["relations"], diagnostics=timeline["diagnostics"])
    # Context and PID proximity must not create a causal edge for a daemon
    # with no explicit send/receive record.
    isolated = dict(reports[2])
    isolated["context"] = {"trace_id": session["trace_id"], "correlation_id": session["correlation_id"]}
    isolated_timeline = build_timeline([reports[0], isolated])
    if isolated_timeline["relations"]:
        return result("multi_daemon_session", "FAIL", "shared context was incorrectly promoted to a causal edge")
    return result("multi_daemon_session", "PASS", "three daemon artifacts grouped and two explicit IPC edges joined", artifacts=3, relations=2)


def _native_multi_daemon_session(work: pathlib.Path, build_dir: pathlib.Path | None) -> dict[str, Any]:
    """Run three real instrumented targets and verify session grouping."""
    if build_dir is None:
        return result("native_multi_daemon_session", "NOT RUN", "--build-dir was not supplied")
    binary = build_dir / "test" / "fd_signals"
    if not binary.is_file():
        return result("native_multi_daemon_session", "NOT RUN", "fd_signals fixture is unavailable", binary=str(binary))
    try:
        from faultdebug.run import run_target
        reports = [run_target([str(binary), "11"], artifact_dir=work / f"native-{index}",
                              context={"trace_id": "v07-native-session", "correlation_id": "v07-correlation", "daemon": f"d{index}"})
                   for index in range(3)]
    except Exception as exc:
        return result("native_multi_daemon_session", "FAIL", f"native session execution failed: {exc}")
    if any(report.get("target", {}).get("signal") != 11 for report in reports):
        return result("native_multi_daemon_session", "FAIL", "native daemon signal expectation failed", targets=[report.get("target") for report in reports])
    artifacts = [pathlib.Path(report["artifact"]) for report in reports if report.get("artifact")]
    if len(artifacts) != 3:
        return result("native_multi_daemon_session", "FAIL", "native session did not produce one artifact per daemon", artifacts=[str(path) for path in artifacts])
    grouped = collect_artifacts(artifacts, trace_id="v07-native-session")
    timeline = build_timeline([read_artifact(path) for path in artifacts])
    if grouped["count"] != 3 or timeline["relations"]:
        return result("native_multi_daemon_session", "FAIL", "native session grouping or no-inference expectation failed", grouped=grouped, relations=timeline["relations"])
    return result("native_multi_daemon_session", "PASS", "three real fault runs retained shared session metadata without inferred causal edges", artifacts=3, relations=0)


def _collector_crash_recovery(work: pathlib.Path) -> dict[str, Any]:
    spool_root = work / "recovery-spool"
    spool = ArtifactSpool(spool_root, max_bytes=128 * 1024, max_files=8)
    stale = spool_root / ".faultdebug-crashed-process.tmp"
    stale.write_bytes(b"partial temporary write")
    valid_source = write_artifact({
        "header": {"status": 0}, "process": {"pid": 55},
        "collector": {"ok": True, "status": "complete"}, "crashes": [],
    }, work / "source", 55)
    valid = spool.ingest(valid_source)
    malformed = spool_root / "fault-malformed.fault"
    malformed.write_bytes(b"FDAR\x01\x00truncated")
    was_stale = stale.exists()
    restarted = ArtifactSpool(spool_root, max_bytes=128 * 1024, max_files=8)
    startup_removed = int(was_stale and not stale.exists())
    recovered = restarted.recover()
    discovery = inspect_spool(spool_root)
    malformed_rows = [row for row in discovery["artifacts"] if row["path"] == malformed.name]
    valid_rows = [row for row in discovery["artifacts"] if row["path"] == valid.name]
    if stale.exists() or not valid.exists():
        return result("collector_crash_recovery", "FAIL", "recovery did not preserve valid final and remove stale temporary", recovered=recovered)
    if len(malformed_rows) != 1 or malformed_rows[0]["status"] != "FAIL" or len(valid_rows) != 1:
        return result("collector_crash_recovery", "FAIL", "malformed final was not retained as explicit failure", discovery=discovery)
    return result("collector_crash_recovery", "PASS", "abandoned temporary removed; valid final retained; malformed final reported", removed_temps=startup_removed + int(recovered.get("removed_temps", 0)), invalid_files=recovered.get("invalid_files", []))


def _malformed_partial(work: pathlib.Path) -> dict[str, Any]:
    root = work / "malformed"
    source = write_artifact({
        "header": {"status": 1 << 9, "abi_version": 1},
        "process": {"pid": 77},
        "target": {"returncode": -9, "signal": 9},
        "collector": {"ok": True, "status": "partial", "partial": True},
        "crashes": [],
    }, root, 77)
    raw = source.read_bytes()
    truncated = root / "fault-truncated.fault"
    truncated.write_bytes(raw[:-1])
    checksum = root / "fault-checksum.fault"
    bad_checksum = bytearray(raw)
    bad_checksum[-1] ^= 0x01
    checksum.write_bytes(bad_checksum)
    version = root / "fault-version.fault"
    version.write_bytes(HEADER.pack(b"FDAR", 99, 0, len(raw) - HEADER.size, 77, raw[20:52]) + raw[HEADER.size:])
    rejected: list[str] = []
    for path in (truncated, checksum, version):
        try:
            read_artifact(path)
        except Exception:
            rejected.append(path.name)
    partial = read_artifact(source)
    report = incident_report([partial])
    discovered = inspect_spool(root)
    invalid = {row["path"] for row in discovered["artifacts"] if row["status"] == "FAIL"}
    expected_invalid = {truncated.name, checksum.name, version.name}
    if set(rejected) != expected_invalid or not expected_invalid <= invalid:
        return result("malformed_partial_artifact", "FAIL", "malformed FDAR cases were accepted or not surfaced", rejected=rejected, invalid=sorted(invalid))
    if partial.get("collector", {}).get("partial") is not True or report["status"] not in {"limited", "unresolved"}:
        return result("malformed_partial_artifact", "FAIL", "partial collector status was lost or promoted to complete", collector=partial.get("collector"), report_status=report["status"])
    return result("malformed_partial_artifact", "PASS", "truncated/checksum/version cases rejected and partial status retained", rejected=sorted(rejected), report_status=report["status"])


def _context_contract() -> dict[str, Any]:
    try:
        normalized = normalize_context({"trace_id": "t", "correlation_id": "c", "daemon": "worker"})
        decoded = context_from_env({"FAULTDEBUG_CONTEXT_JSON": '{"trace_id":"t"}', "FAULTDEBUG_CORRELATION_ID": "c"})
        try:
            context_from_env({"FAULTDEBUG_CONTEXT_JSON": '{"trace_id":"x"}', "FAULTDEBUG_TRACE_ID": "y"})
        except ContextError:
            conflict_rejected = True
        else:
            conflict_rejected = False
    except Exception as exc:
        return result("session_context_contract", "FAIL", f"context contract failed: {exc}")
    if normalized["trace_id"] != "t" or decoded != {"trace_id": "t", "correlation_id": "c"} or not conflict_rejected:
        return result("session_context_contract", "FAIL", "context propagation/Conflict expectation mismatch", normalized=normalized, decoded=decoded, conflict_rejected=conflict_rejected)
    return result("session_context_contract", "PASS", "bounded session context and conflicting IDs are handled explicitly")


def _collector_api_import() -> dict[str, Any]:
    """Ensure the collector registration surface is importable as shipped."""
    try:
        from faultdebug import collector
        required = ("CollectorRegistration", "register_process", "collect_registered")
        missing = [name for name in required if not hasattr(collector, name)]
    except Exception as exc:
        return result("collector_registration_api", "FAIL", f"collector module is not importable: {exc}")
    if missing:
        return result("collector_registration_api", "FAIL", "collector registration API is incomplete", missing=missing)
    return result("collector_registration_api", "PASS", "collector registration API imports with required symbols")


def _v06_regression(work: pathlib.Path, build_dir: pathlib.Path | None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name in ("rpc_analysis", "incident_report"):
        completed = subprocess.run([sys.executable, str(ROOT / "test" / f"{name}.py")], cwd=ROOT, text=True, capture_output=True, timeout=30)
        checks.append(result(f"v06_{name}", "PASS" if completed.returncode == 0 else "FAIL", f"{name} regression command completed", returncode=completed.returncode, stderr=completed.stderr[-1000:]))
    if build_dir is None:
        checks.append(result("v06_grpc_unary", "NOT RUN", "--grpc-build-dir was not supplied"))
        return checks
    binary = build_dir / "test" / "fd_grpc_async_proxy"
    if not binary.is_file():
        checks.append(result("v06_grpc_unary", "NOT RUN", "optional gRPC fixture binary is unavailable", binary=str(binary)))
        return checks
    report_dir = work / "grpc-regression"
    completed = subprocess.run([sys.executable, str(ROOT / "test" / "grpc_proxy_test.py"), "--build-dir", str(build_dir), "--output", str(report_dir)], cwd=ROOT, text=True, capture_output=True, timeout=180)
    report_path = report_dir / "report.json"
    if not report_path.is_file():
        checks.append(result("v06_grpc_unary", "FAIL", "gRPC regression did not emit report", returncode=completed.returncode))
        return checks
    report = json.loads(report_path.read_text())
    status = report.get("status", "FAIL")
    checks.append(result("v06_grpc_unary", status if status in {"PASS", "FAIL", "NOT RUN"} else "FAIL", "existing v0.6 gRPC gate replayed", returncode=completed.returncode, checks=report.get("checks", [])))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="independent v0.7 validation")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--grpc-build-dir", type=pathlib.Path)
    parser.add_argument("--build-dir", type=pathlib.Path,
                        help="native fixture build directory for the optional real session check")
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="faultdebug-v07-") as raw:
        work = pathlib.Path(raw)
        checks = [_context_contract(), _collector_api_import(), _multi_daemon_session(work),
                  _native_multi_daemon_session(work, ns.build_dir),
                  _collector_crash_recovery(work), _malformed_partial(work)]
        checks.extend(_v06_regression(work, ns.grpc_build_dir))
    statuses = [item["status"] for item in checks]
    overall = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "version": "0.7.0", "status": overall, "checks": checks}
    path = ns.output / "report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": overall, "checks": {state: statuses.count(state) for state in ("PASS", "FAIL", "NOT RUN")}, "report": str(path)}, sort_keys=True))
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
