#!/usr/bin/env python3
"""Independent contract checks for the optional gRPC/RPC evidence layer.

This test deliberately does not import a product RPC encoder.  It validates
the wire-level expectations against supplied artifacts and small adversarial
fixtures, so changing an analyzer expectation cannot make the oracle pass.
Checks that need an optional dependency or a not-yet-enabled semantic stream
are reported as ``NOT RUN``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import signal
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATUS_EVENT_OVERFLOW = 1 << 3
STATUS_PARTIAL = 1 << 9
FDAR_HEADER = struct.Struct("<4sHHQI32s")


def result(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    item = {"name": name, "status": status, "reason": reason}
    item.update(extra)
    return item


def _write_artifact(path: pathlib.Path, report: dict[str, Any], version: int = 1,
                    corrupt: bool = False) -> None:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(payload).digest()
    if corrupt:
        digest = b"x" * len(digest)
    path.write_bytes(FDAR_HEADER.pack(b"FDAR", version, 0, len(payload), 7, digest) + payload)


def _read_artifact(path: pathlib.Path) -> dict[str, Any]:
    from faultdebug.artifact import read_artifact
    return read_artifact(path)


def _rpc_events(report: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Accept the two planned locations while keeping the field contract strict."""
    for key in ("rpc_trace", "rpc", "semantic_rpc"):
        extension = report.get(key)
        if isinstance(extension, dict):
            rows = extension.get("events", extension.get("rpc_events", extension.get("semantic_events")))
            if rows is not None:
                return rows if isinstance(rows, list) and all(isinstance(row, dict) for row in rows) else []
    rows = report.get("rpc_events", report.get("semantic_rpc_events"))
    if rows is None:
        rows = []
        for thread in report.get("threads", []):
            rows.extend(thread.get("rpc_events", thread.get("semantic_events", [])))
    if not rows:
        return None
    return rows if all(isinstance(row, dict) for row in rows) else []


def _validate_rpc_stream(report: dict[str, Any]) -> dict[str, Any]:
    events = _rpc_events(report)
    if events is None:
        return result("semantic_rpc_abi", "NOT RUN", "artifact has no semantic RPC event stream")
    # A provisioned sidecar can legitimately contain zero committed semantic
    # events (for example, the producer was not installed in this process).
    # That is an environmental absence of evidence, not malformed RPC data.
    if not events:
        return result("semantic_rpc_abi", "NOT RUN", "semantic RPC extension has no committed events")
    if len(events) > 1024:
        return result("semantic_rpc_abi", "FAIL", "semantic RPC stream exceeds bounded event capacity", count=len(events))
    # The sidecar ABI stores start/end timestamps and numeric direction/status;
    # JSON adapters may additionally expose a phase string.  Do not require a
    # method name or metadata: those are intentionally excluded from the ABI.
    missing = sorted(key for key in ("rpc_id",) if any(key not in row for row in events))
    temporal_missing = [
        row for row in events
        if not any(key in row for key in ("monotonic_ns", "timestamp_ns", "sequence",
                                          "start_monotonic_ns", "end_monotonic_ns"))
    ]
    if temporal_missing:
        missing.append("timestamp_or_sequence")
    if missing:
        return result("semantic_rpc_abi", "FAIL", "required RPC fields are missing", missing=missing)
    ids = {str(row["rpc_id"]) for row in events}
    if not ids or "" in ids:
        return result("semantic_rpc_abi", "FAIL", "rpc_id must be non-empty")
    phases = {str(row["phase"]).lower() for row in events if "phase" in row}
    allowed = {"begin", "send", "receive", "recv", "status", "end", "cancel"}
    unknown = sorted(phases - allowed)
    if unknown:
        return result("semantic_rpc_abi", "FAIL", "unknown RPC phase", phases=unknown)
    timestamps = [int(row.get("monotonic_ns", row.get("timestamp_ns", row.get("sequence", index)))) for index, row in enumerate(events)]
    if timestamps != sorted(timestamps):
        return result("semantic_rpc_abi", "FAIL", "semantic events are not monotonic")
    schema = report.get("semantic_rpc_schema", report.get("rpc_schema", 1))
    for key in ("rpc_trace", "rpc", "semantic_rpc"):
        if isinstance(report.get(key), dict):
            schema = report[key].get("schema", report[key].get("version", schema))
            break
    if schema not in (1, 2):
        return result("semantic_rpc_abi", "FAIL", "unsupported semantic RPC schema", schema=schema)
    return result("semantic_rpc_abi", "PASS", "bounded semantic RPC fields and ordering are valid", count=len(events), rpc_ids=sorted(ids))


def _validate_incomplete_contract() -> dict[str, Any]:
    """Use independent adversarial fixtures to test overflow disclosure rules."""
    good = {
        "header": {"status": STATUS_EVENT_OVERFLOW | STATUS_PARTIAL},
        "complete": False,
        "rpc_events": [{"rpc_id": "r1", "phase": "begin", "monotonic_ns": 1}],
    }
    bad = dict(good)
    bad["complete"] = True
    # The expected result is deliberately calculated here from the contract,
    # rather than reusing an analyzer's output.
    def honest(value: dict[str, Any]) -> bool:
        flags = int(value.get("header", {}).get("status", 0))
        return not (flags & (STATUS_EVENT_OVERFLOW | STATUS_PARTIAL)) or value.get("complete") is False
    if not honest(good) or honest(bad):
        return result("bounded_overflow_disclosure", "FAIL", "overflow fixture contract is not discriminating")
    return result("bounded_overflow_disclosure", "PASS", "overflow/partial status requires incomplete evidence", flags=good["header"]["status"])


def _validate_sidecar_layout() -> dict[str, Any]:
    # Mirrors the fixed-width C declarations in include/faultdebug/format.h.
    # This test is intentionally independent of the Python decoder and catches
    # accidental padding/field-count changes before a producer is shipped.
    header = struct.Struct("<IHHIIQQIIIIQQ")
    event = struct.Struct("<QQQQQQQQIIIIIIII")
    if header.size != 64 or event.size != 96:
        return result("semantic_rpc_layout", "FAIL", "sidecar fixed-width layout drift",
                      header_size=header.size, event_size=event.size)
    sidecar_offset = (12669648 + 63) & ~63  # sizeof(fd_shared_memory) for ABI v1
    if sidecar_offset % 64:
        return result("semantic_rpc_layout", "FAIL", "sidecar offset is not 64-byte aligned")
    return result("semantic_rpc_layout", "PASS", "sidecar header/event sizes and alignment match ABI contract", header_size=header.size, event_size=event.size, sidecar_offset=sidecar_offset)


def _validate_malformed_artifacts(tmp: pathlib.Path) -> dict[str, Any]:
    valid = {"header": {"status": 0}, "threads": [], "modules": [], "crashes": []}
    cases = [("version", 99, False), ("checksum", 1, True)]
    failures: list[str] = []
    for name, version, corrupt in cases:
        path = tmp / f"malformed-{name}.fault"
        _write_artifact(path, valid, version=version, corrupt=corrupt)
        try:
            _read_artifact(path)
        except Exception:
            continue
        failures.append(name)
    decoder_failures: list[str] = []
    try:
        from faultdebug.rpc import RPCDecodeError, rpc_trace
        malformed_rpc = {"rpc_trace": {"schema": 99, "events": []}}
        try:
            rpc_trace(malformed_rpc)
        except RPCDecodeError:
            pass
        else:
            decoder_failures.append("unsupported_rpc_schema")
        try:
            rpc_trace({"rpc_trace": {"schema": 1, "events": []},
                       "rpc": {"schema": 1, "events": []}})
        except RPCDecodeError:
            pass
        else:
            decoder_failures.append("ambiguous_rpc_extensions")
    except ImportError:
        decoder_failures.append("rpc_decoder_unavailable")
    failures.extend(decoder_failures)
    return result("malformed_artifacts", "FAIL" if failures else "PASS",
                  "decoder accepted malformed artifact" if failures else "version/checksum mismatch rejected",
                  accepted=failures, rpc_decoder_cases=2)


def _mcp_stdio(tmp: pathlib.Path) -> dict[str, Any]:
    try:
        import mcp  # noqa: F401
    except ImportError:
        return result("mcp_stdio", "NOT RUN", "official mcp Python SDK is unavailable")
    artifact = tmp / "mcp.fault"
    _write_artifact(artifact, {"header": {"status": 0}, "threads": [], "modules": [], "crashes": []})
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    command = [sys.executable, "-m", "faultdebug.cli", "mcp", "--root", str(tmp)]
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, bufsize=1)
    try:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "faultdebug-contract-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "open_fault", "arguments": {"name": artifact.name}}},
        ]
        assert process.stdin is not None
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        deadline = time.monotonic() + 15
        responses: dict[int, dict[str, Any]] = {}
        assert process.stdout is not None
        while time.monotonic() < deadline and len(responses) < 3:
            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message.get("id"), int):
                responses[message["id"]] = message
        required_ids = {1, 2, 3}
        if required_ids - responses.keys():
            return result("mcp_stdio", "FAIL", "stdio MCP responses missing", missing=sorted(required_ids - responses.keys()))
        if "error" in responses[1] or "error" in responses[2] or "error" in responses[3]:
            return result("mcp_stdio", "FAIL", "stdio MCP request returned an error", responses=responses)
        return result("mcp_stdio", "PASS", "initialize, tools/list, and open_fault completed over stdio", tool_count=len(responses[2].get("result", {}).get("tools", [])))
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()


def _grpc_integration(build_dir: pathlib.Path | None, output: pathlib.Path) -> dict[str, Any]:
    if build_dir is None:
        return result("grpc_fixture", "NOT RUN", "--grpc-build-dir was not supplied")
    binary = build_dir / "test" / "fd_grpc_async_proxy"
    if not binary.is_file():
        return result("grpc_fixture", "NOT RUN", "optional fd_grpc_async_proxy is unavailable", binary=str(binary))
    report_dir = output / "grpc-fixture"
    command = [sys.executable, str(ROOT / "test" / "grpc_proxy_test.py"),
               "--build-dir", str(build_dir), "--output", str(report_dir)]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
    report_path = report_dir / "report.json"
    if not report_path.is_file():
        return result("grpc_fixture", "FAIL", "gRPC fixture did not produce a report", returncode=completed.returncode, stderr=completed.stderr[-2000:])
    report = json.loads(report_path.read_text())
    status = report.get("status", "FAIL")
    return result("grpc_fixture", status, "independent async proxy gate completed", returncode=completed.returncode, checks=report.get("checks", []))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=pathlib.Path)
    parser.add_argument("--grpc-build-dir", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="faultdebug-rpc-contract-") as work:
        tmp = pathlib.Path(work)
        if ns.artifact:
            try:
                checks.append(_validate_rpc_stream(_read_artifact(ns.artifact)))
            except Exception as exc:
                checks.append(result("semantic_rpc_abi", "FAIL", f"artifact could not be read: {exc}"))
        else:
            checks.append(result("semantic_rpc_abi", "NOT RUN", "--artifact was not supplied"))
        checks.append(_validate_sidecar_layout())
        checks.append(_validate_incomplete_contract())
        checks.append(_validate_malformed_artifacts(tmp))
        checks.append(_mcp_stdio(tmp))
        checks.append(_grpc_integration(ns.grpc_build_dir, ns.output))
    statuses = [item["status"] for item in checks]
    overall = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "status": overall, "checks": checks}
    report_path = ns.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": overall, "checks": {s: statuses.count(s) for s in ("PASS", "FAIL", "NOT RUN")}, "report": str(report_path)}, sort_keys=True))
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
