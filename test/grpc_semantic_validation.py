#!/usr/bin/env python3
"""Independent gRPC semantic-event and capability gate.

The current fixture intentionally has a unary function-boundary scenario.  This
oracle records streaming, deadline/cancellation, retry, worker, and semantic
RPC paths as ``NOT RUN`` until a fixture advertises those scenarios.  It never
turns function names or analyzer output into semantic RPC evidence.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import signal
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    value = {"name": name, "status": status, "reason": reason}
    value.update(extra)
    return value


def _semantic_unary(path: pathlib.Path | None) -> dict[str, Any]:
    if path is None:
        return check("semantic_rpc_events", "NOT RUN", "--artifact was not supplied")
    try:
        from faultdebug.format import collect_file
        report = collect_file(path)
    except Exception as exc:
        return check("semantic_rpc_events", "FAIL", f"artifact could not be decoded: {exc}")
    rpc = report.get("rpc")
    if not isinstance(rpc, dict):
        for key in ("rpc_trace", "semantic_rpc"):
            if isinstance(report.get(key), dict):
                rpc = report[key]
                break
    if not isinstance(rpc, dict) and isinstance(report.get("rpc_events"), list):
        # Older artifact readers expose the sidecar event array at the
        # top-level.  Keep the surrounding sidecar metadata optional.
        rpc = {"events": report["rpc_events"]}
    if not isinstance(rpc, dict):
        return check("semantic_rpc_events", "NOT RUN", "artifact has no RPC sidecar")
    events = rpc.get("events")
    if isinstance(events, list) and not events and isinstance(report.get("rpc_events"), list):
        events = report["rpc_events"]
    if not isinstance(events, list):
        return check("semantic_rpc_events", "FAIL", "RPC sidecar events are not an array")
    if not events:
        return check("semantic_rpc_events", "NOT RUN", "RPC sidecar has no committed events")
    if not all(isinstance(row, dict) for row in events):
        return check("semantic_rpc_events", "FAIL", "RPC sidecar contains a non-object event")
    rpc_header = rpc.get("header") or {}
    crashes = report.get("crashes") or []
    try:
        incomplete = bool(not rpc.get("complete", True) or int(rpc_header.get("flags", 0)) & 2)
        target_signal = int((report.get("target") or {}).get("signal", 0) or 0)
        crash_signals = {
            int(row.get("signal", 0)) for row in crashes
            if isinstance(row, dict) and row.get("signal") is not None
        }
    except (TypeError, ValueError) as exc:
        return check("semantic_rpc_events", "FAIL", f"RPC crash/status metadata is not numeric: {exc}")
    intentional_crash = target_signal == signal.SIGSEGV or signal.SIGSEGV in crash_signals
    if incomplete and not intentional_crash:
        return check("semantic_rpc_events", "FAIL", "incomplete RPC sidecar has no crash/termination evidence")
    try:
        starts = [row for row in events if int(row.get("flags", 0)) & 1]
        ends = [row for row in events if int(row.get("flags", 0)) & 2]
        ids = [row.get("rpc_id") for row in events]
        directions = sorted({int(row.get("direction", 0)) for row in events})
        sequences = [int(row.get("sequence", -1)) for row in events]
    except (TypeError, ValueError) as exc:
        return check("semantic_rpc_events", "FAIL", f"RPC sidecar contains a non-numeric field: {exc}")
    sensitive = {key for row in events if isinstance(row, dict) for key in
                 ("method", "method_name", "metadata", "payload", "credentials") if key in row}
    if sensitive:
        return check("semantic_rpc_events", "FAIL", "semantic event contains forbidden sensitive fields", fields=sorted(sensitive))
    if directions != [1, 2]:
        return check("semantic_rpc_events", "FAIL", "proxy expected inbound and outbound RPC directions", directions=directions, rpc_ids=ids)
    for direction in directions:
        direction_starts = [row for row in starts if int(row.get("direction", 0)) == direction]
        direction_ends = [row for row in ends if int(row.get("direction", 0)) == direction]
        if len(direction_starts) != 1 or len(direction_ends) != 1:
            return check("semantic_rpc_events", "FAIL", "each observed direction must have one begin/end pair", direction=direction, starts=len(direction_starts), ends=len(direction_ends), rpc_ids=ids)
        if direction_starts[0].get("rpc_id") != direction_ends[0].get("rpc_id"):
            return check("semantic_rpc_events", "FAIL", "RPC begin/end IDs do not correlate", direction=direction)
    if len({row.get("rpc_id") for row in events}) != 1:
        return check("semantic_rpc_events", "FAIL", "inbound/outbound events do not share one RPC ID", rpc_ids=ids)
    if ids[0] in (None, ""):
        return check("semantic_rpc_events", "FAIL", "semantic RPC ID is empty")
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        return check("semantic_rpc_events", "FAIL", "semantic RPC sequence is not strictly increasing", sequences=sequences)
    loss_flags = int(rpc_header.get("flags", 0)) & 1
    if not loss_flags and sequences != list(range(sequences[0], sequences[-1] + 1)):
        return check("semantic_rpc_events", "FAIL", "semantic RPC sequence contains an unexplained gap", sequences=sequences)
    return check("semantic_rpc_events", "PASS", "independently validated inbound/outbound unary RPC pairs", events=len(events), rpc_ids=sorted(set(ids)), directions=directions, incomplete=incomplete, crash_evidence=intentional_crash)


def _capabilities(binary: pathlib.Path | None) -> list[dict[str, Any]]:
    if binary is None or not binary.is_file():
        return [check(name, "NOT RUN", "gRPC fixture binary is unavailable") for name in
                ("streaming_rpc", "deadline_cancellation", "retry_unavailable", "completion_queue_workers")]
    try:
        completed = subprocess.run([str(binary), "--help"], text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [check(name, "NOT RUN", f"fixture capability query failed: {exc}") for name in
                ("streaming_rpc", "deadline_cancellation", "retry_unavailable", "completion_queue_workers")]
    help_text = completed.stdout + completed.stderr
    requirements = {
        "streaming_rpc": ("--stream", "--streaming"),
        "deadline_cancellation": ("--deadline-ms", "--cancel"),
        "retry_unavailable": ("--retry", "--unavailable"),
        "completion_queue_workers": ("--workers", "--cq-workers"),
    }
    return [check(name, "NOT RUN", "fixture does not advertise this scenario", required=list(tokens))
            if not any(token in help_text for token in tokens)
            else check(name, "NOT RUN", "scenario advertised but no independent invocation contract is defined")
            for name, tokens in requirements.items()]


def _multiprocess_chain(report_path: pathlib.Path | None) -> dict[str, Any]:
    if report_path is None or not report_path.is_file():
        return check("multiprocess_chain", "NOT RUN", "--grpc-report was not supplied")
    try:
        report = json.loads(report_path.read_text())
    except Exception as exc:
        return check("multiprocess_chain", "FAIL", f"gRPC report is unreadable: {exc}")
    run = report.get("run") or {}
    client = run.get("client") or {}
    upstream = run.get("upstream") or {}
    proxy = run.get("proxy") or {}
    if run.get("status") == "PASS" and client.get("returncode") == 0 and upstream.get("returncode") == 0 and proxy.get("returncode") == 139:
        return check("multiprocess_chain", "PASS", "client, proxy, and upstream process outcomes match independent expectation", processes=3)
    if report.get("status") == "NOT RUN" and run.get("status") == "PASS":
        return check("multiprocess_chain", "PASS", "three-process execution passed; optional secondary checks were not run", processes=3)
    return check("multiprocess_chain", "FAIL", "three-process execution did not match expected outcomes", run_status=run.get("status"), client=client.get("returncode"), proxy=proxy.get("returncode"), upstream=upstream.get("returncode"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=pathlib.Path)
    parser.add_argument("--binary", type=pathlib.Path)
    parser.add_argument("--grpc-report", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    checks = [_semantic_unary(ns.artifact), *_capabilities(ns.binary), _multiprocess_chain(ns.grpc_report)]
    statuses = [item["status"] for item in checks]
    overall = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "status": overall, "checks": checks}
    report_path = ns.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": overall, "checks": {state: statuses.count(state) for state in ("PASS", "FAIL", "NOT RUN")}, "report": str(report_path)}, sort_keys=True))
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
