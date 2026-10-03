#!/usr/bin/env python3
"""Independent v0.9 MCP, source-evidence, and gRPC semantic acceptance gate.

Expected event counts and status values are computed from this fixture's input
and the documented gRPC protocol, never from analyzer output. Optional
streaming/retry scenarios remain NOT RUN while the fixture exposes unary RPC
only; deadline and CompletionQueue worker paths are executed when the fixture
binary is available.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import select
import signal
import struct
import subprocess
import sys
import tempfile
import threading
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.artifact import write_artifact  # noqa: E402
from faultdebug.bundle import BundleError, create_bundle, load_bundle  # noqa: E402
from faultdebug.evidence_store import EvidenceStore  # noqa: E402

FDAR_HEADER = struct.Struct("<4sHHQI32s")
RPC_END = 1 << 1
DEADLINE_EXCEEDED = 4


def result(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    if status not in {"PASS", "FAIL", "NOT RUN"}:
        raise ValueError(status)
    value = {"name": name, "status": status, "reason": reason}
    value.update(extra)
    return value


def status_exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[status]


def _mcp_python() -> pathlib.Path | None:
    candidates = [pathlib.Path(os.environ["FAULTDEBUG_MCP_PYTHON"])] if os.environ.get("FAULTDEBUG_MCP_PYTHON") else []
    candidates.extend([pathlib.Path(sys.executable), ROOT / ".venv" / "bin" / "python"])
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.absolute()
        if str(candidate) in seen or not candidate.is_file():
            continue
        seen.add(str(candidate))
        probe = subprocess.run([str(candidate), "-c", "import mcp"], cwd=ROOT,
                               capture_output=True, text=True, timeout=15)
        if probe.returncode == 0:
            return candidate
    return None


def _make_mcp_fixture(work: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, str, dict[str, str]]:
    """Create a bounded incident fixture and a hash-addressed source bundle."""
    events: list[dict[str, Any]] = []
    for index in range(1, 501):
        pair = (index + 1) // 2
        begin = index % 2 == 1
        event: dict[str, Any] = {
            "sequence": index,
            "rpc_id": f"rpc-{pair}",
            "phase": "begin" if begin else "end",
            "direction": 2 if begin else 1,
            "monotonic_ns": index,
            "method_id": 9,
            "status": 0,
        }
        if begin:
            event.update({"deadline_ns": 1000, "retry_count": 0, "stream": "unary", "streaming": False})
        events.append(event)
    report = {
        "header": {"status": 0, "abi_version": 1},
        "process": {"pid": 9001, "parent_pid": 1, "start_monotonic_ns": 1},
        "target": {"returncode": 0, "signal": None},
        "collector": {"ok": True, "status": "partial", "partial": True,
                      "incident_id": "incident-v09", "trigger_process_id": "proc-v09",
                      "trigger_signal": signal.SIGSEGV, "phase": "incident_snapshot"},
        "evidence_class": "observed",
        "source_evidence": [{"function_id": "fn:v09"}],
        "rpc_trace": {
            "schema": 1, "complete": False, "events": events,
            "static_candidates": [{"kind": "possible_rpc", "function_id": "fn:v09"}],
        },
        "static_candidates": [{"kind": "possible_call", "function_id": "fn:v09"}],
        "crashes": [],
    }
    artifact = write_artifact(report, work, 9001, artifact_stem="fault-mcp")
    source_root = work / "source-root"
    source_root.mkdir()
    source = source_root / "main.c"
    source.write_text("/* v0.9 source fixture */\nint demo(void) {\n  return 42;\n}\n")
    index = work / "function-index.json"
    index.write_text(json.dumps({"version": 1, "functions": [{
        "id": "fn:v09", "name": "demo", "linkage_name": "demo",
        "file": str(source), "line": 2, "is_definition": True,
        "source_range": {"start": 2, "end": 4}, "edges": [],
        "unresolved_edges": []}], "coverage_failures": []}, sort_keys=True))
    bundle = create_bundle(source_root, work / "bundle", index=index)
    with EvidenceStore(work / "evidence.sqlite3") as store:
        stored = store.ingest(artifact)
        if stored.get("status") != "ingested":
            raise RuntimeError(f"could not seed v0.9 incident store: {stored}")
    manifest_hashes = {row["path"]: row["sha256"] for row in bundle.manifest["files"]}
    return artifact, bundle.root, "fn:v09", manifest_hashes


def _fdar(path: pathlib.Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) < FDAR_HEADER.size:
        raise ValueError("FDAR header is truncated")
    magic, version, _flags, length, _pid, digest = FDAR_HEADER.unpack_from(raw)
    payload = raw[FDAR_HEADER.size:]
    if magic != b"FDAR" or version != 1 or length != len(payload) or hashlib.sha256(payload).digest() != digest:
        raise ValueError("FDAR checksum or version mismatch")
    report = json.loads(payload)
    if not isinstance(report, dict):
        raise ValueError("FDAR payload is not an object")
    return report


def _mcp_value(message: dict[str, Any]) -> Any:
    if "error" in message:
        raise RuntimeError(str(message["error"]))
    value = message.get("result", {})
    if isinstance(value, dict) and "structuredContent" in value:
        return value["structuredContent"]
    content = value.get("content") if isinstance(value, dict) else None
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    return json.loads(item.get("text", ""))
                except json.JSONDecodeError:
                    return item.get("text")
    return value


def _read_json_response(stream: Any, deadline: float,
                        noise: list[str] | None = None) -> dict[str, Any] | None:
    while time_remaining := deadline - __import__("time").monotonic():
        ready, _, _ = select.select([stream], [], [], max(0.0, time_remaining))
        if not ready:
            return None
        line = stream.readline()
        if not line:
            return None
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            if noise is not None:
                noise.append(line)
            continue
        if isinstance(value, dict) and "id" in value:
            return value
        if noise is not None:
            noise.append(line)
    return None


def _drain_stderr(stream: Any, chunks: list[str]) -> None:
    for line in stream:
        chunks.append(line)
        if sum(map(len, chunks)) > 8192:
            chunks[:] = ["".join(chunks)[-8192:]]


def _mcp_stdio(work: pathlib.Path, artifact: pathlib.Path, bundle: pathlib.Path,
               function_id: str, expected_hashes: dict[str, str]) -> dict[str, Any]:
    interpreter = _mcp_python()
    if interpreter is None:
        return result("mcp_stdio_protocol", "NOT RUN", "official mcp Python SDK is unavailable")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    process = subprocess.Popen(
        [str(interpreter), "-m", "faultdebug.cli", "mcp", "--root", str(work)],
        cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="backslashreplace",
        bufsize=1,
    )
    responses: dict[int, dict[str, Any]] = {}
    stderr_chunks: list[str] = []
    stdout_noise: list[str] = []
    stderr_reader = threading.Thread(target=_drain_stderr,
                                     args=(process.stderr, stderr_chunks), daemon=True)
    stderr_reader.start()
    exchange_result: dict[str, Any] | None = None

    def finish(row: dict[str, Any]) -> dict[str, Any]:
        nonlocal exchange_result
        exchange_result = row
        return row
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "faultdebug-v09", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "open_fault", "arguments": {"name": artifact.name, "bundle": bundle.name}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "get_incident_report", "arguments": {"names": [artifact.name], "page": 2}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "get_function_source", "arguments": {"name": artifact.name,
            "function_id": function_id, "bundle": bundle.name}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "list_incidents", "arguments": {"db": "evidence.sqlite3", "page": 0}}},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "get_incident_slice", "arguments": {"incident_id": "incident-v09",
            "db": "evidence.sqlite3", "page": 0}}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": "get_source_evidence", "arguments": {"incident_id": "incident-v09",
            "db": "evidence.sqlite3", "bundle": bundle.name, "function_ids": [function_id]}}},
    ]
    try:
        assert process.stdin is not None and process.stdout is not None
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            if "id" not in request:
                continue
            deadline = __import__("time").monotonic() + 30.0
            message = _read_json_response(process.stdout, deadline, stdout_noise)
            if message is None:
                break
            responses[int(message["id"])] = message
        missing = sorted({1, 2, 3, 4, 5, 6, 7, 8} - set(responses))
        if missing:
            return finish(result("mcp_stdio_protocol", "FAIL", "initialize/tools/call responses missing", missing=missing))
        tools = _mcp_value(responses[2])
        tool_names = {row.get("name") for row in (tools.get("tools", []) if isinstance(tools, dict) else [])}
        required = {"open_fault", "get_incident_report", "get_function_source",
                    "list_incidents", "get_incident_slice", "get_source_evidence"}
        if not required <= tool_names:
            return finish(result("mcp_stdio_protocol", "FAIL", "required MCP tools are missing",
                                 missing=sorted(required - tool_names)))
        incident = _mcp_value(responses[4])
        if not isinstance(incident, dict):
            return finish(result("mcp_stdio_protocol", "FAIL", "incident result is not an object"))
        observed = incident.get("observed", {}).get("rpc_events", [])
        if incident.get("total_rpc_events") != 500 or len(observed) != 100:
            return finish(result("mcp_stdio_protocol", "FAIL", "incident slice exceeded or lost its bounded page",
                                 total=incident.get("total_rpc_events"), page_items=len(observed)))
        if not incident.get("static_candidates") or not incident.get("unresolved"):
            return finish(result("mcp_stdio_protocol", "FAIL", "evidence classes were merged or omitted",
                                 keys=sorted(incident)))
        listed = _mcp_value(responses[6])
        slice_result = _mcp_value(responses[7])
        source_evidence = _mcp_value(responses[8])
        if not isinstance(listed, dict) or listed.get("total") != 1:
            return finish(result("mcp_stdio_protocol", "FAIL", "incident listing did not retain one declared incident",
                                 listed=listed))
        slice_events = slice_result.get("observed", {}).get("rpc_events", []) if isinstance(slice_result, dict) else []
        slice_total = slice_result.get("event_total") if isinstance(slice_result, dict) else None
        slice_truncated = slice_result.get("event_truncated") if isinstance(slice_result, dict) else None
        if (not isinstance(slice_result, dict)
                or slice_result.get("incident", {}).get("incident_id") != "incident-v09"
                or not isinstance(slice_total, int) or not 500 <= slice_total <= 1000
                or slice_truncated is not False or len(slice_events) != 500
                or not slice_result.get("static_candidates")
                or not slice_result.get("unresolved")):
            return finish(result("mcp_stdio_protocol", "FAIL", "incident slice was not bounded or lost events",
                                 event_total=slice_total, event_truncated=slice_truncated,
                                 returned=len(slice_events)))
        if not isinstance(source_evidence, dict) or source_evidence.get("resolved") is not True:
            return finish(result("mcp_stdio_protocol", "FAIL", "incident source evidence did not resolve",
                                 source_evidence=source_evidence))
        source = _mcp_value(responses[5])
        if not isinstance(source, dict) or source.get("resolved") is not True:
            return finish(result("mcp_stdio_protocol", "FAIL", "source citation was not resolved", source=source))
        citation = (source_evidence.get("citations") or [{}])[0]
        source_path = bundle / citation.get("file", "")
        rel = next((key for key in expected_hashes if key.endswith(source_path.name)), None)
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest() if source_path.is_file() else None
        if (rel is None or digest != expected_hashes[rel] or citation.get("sha256") != digest
                or citation.get("manifest_sha256") != digest):
            return finish(result("mcp_stdio_protocol", "FAIL", "source citation hash does not match bundle manifest",
                                 file=str(source_path), digest=digest, citation=citation))
        if int(source.get("start_line", 0)) != 2 or int(source.get("end_line", 0)) != 4:
            return finish(result("mcp_stdio_protocol", "FAIL", "source citation line range is incorrect", source=source))
        return finish(result("mcp_stdio_protocol", "PASS",
                             "initialize, tools/list, bounded incident slice, evidence classes, and source citation passed",
                             tool_count=len(tool_names), incident_total=incident.get("total_rpc_events"),
                             incident_page_items=len(observed), incident_slice_events=len(slice_events),
                             incident_slice_total=slice_total,
                             source_sha256=digest))
    except (AssertionError, OSError, RuntimeError, ValueError, TypeError) as exc:
        return finish(result("mcp_stdio_protocol", "FAIL", f"MCP stdio exchange failed: {exc}"))
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)
        stderr_reader.join(timeout=1)
        if exchange_result is not None and exchange_result["status"] != "PASS":
            exchange_result["mcp_exchange"] = {
                "responses": responses,
                "stdout_unparsed": "".join(stdout_noise)[-4000:],
                "stderr": "".join(stderr_chunks)[-4000:],
            }


def _grpc_semantic(path: pathlib.Path, scenario: str) -> dict[str, Any]:
    report = _fdar(path)
    extension = report.get("rpc") or report.get("rpc_trace") or report.get("semantic_rpc")
    if not isinstance(extension, dict) or not isinstance(extension.get("events"), list):
        return result(f"grpc_{scenario}_semantic", "FAIL", "artifact has no semantic RPC event stream")
    events = extension["events"]
    if not events:
        return result(f"grpc_{scenario}_semantic", "FAIL", "semantic RPC stream has no committed events")
    if any(any(key in event for key in ("method", "metadata", "payload", "credentials")) for event in events):
        return result(f"grpc_{scenario}_semantic", "FAIL", "semantic event contains sensitive fields")
    sequences = [int(event.get("sequence", -1)) for event in events]
    directions = sorted({int(event.get("direction", 0)) for event in events})
    rpc_ids = {event.get("rpc_id") for event in events}
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        return result(f"grpc_{scenario}_semantic", "FAIL", "semantic sequence is not strictly increasing", sequences=sequences)
    if directions != [1, 2] or len(rpc_ids) != 1 or None in rpc_ids:
        return result(f"grpc_{scenario}_semantic", "FAIL", "inbound/outbound semantic correlation is incomplete",
                      directions=directions, rpc_ids=sorted(str(value) for value in rpc_ids))
    for direction in directions:
        rows = [event for event in events if int(event.get("direction", 0)) == direction]
        if sum(bool(int(event.get("flags", 0)) & 1) for event in rows) != 1 or sum(bool(int(event.get("flags", 0)) & RPC_END) for event in rows) != 1:
            return result(f"grpc_{scenario}_semantic", "FAIL", "each direction lacks one begin/end pair", direction=direction)
    if scenario == "deadline":
        outbound_ends = [event for event in events if int(event.get("direction", 0)) == 2 and int(event.get("flags", 0)) & RPC_END]
        if not outbound_ends or int(outbound_ends[0].get("status", -1)) != DEADLINE_EXCEEDED:
            return result("grpc_deadline_semantic", "FAIL", "deadline scenario did not retain DEADLINE_EXCEEDED", outbound_ends=outbound_ends)
    return result(f"grpc_{scenario}_semantic", "PASS", "independent semantic event oracle passed",
                  events=len(events), directions=directions, incomplete=extension.get("complete") is False)


def _grpc_scenarios(build_dir: pathlib.Path | None, work: pathlib.Path) -> list[dict[str, Any]]:
    names = ("grpc_streaming", "grpc_retry", "grpc_deadline", "grpc_workers")
    if build_dir is None:
        return [result(name, "NOT RUN", "--grpc-build-dir was not supplied") for name in names]
    binary = (build_dir / "test" / "fd_grpc_async_proxy").resolve()
    if not binary.is_file():
        return [result(name, "NOT RUN", "fd_grpc_async_proxy is unavailable", binary=str(binary)) for name in names]
    help_result = subprocess.run([str(binary), "--help"], cwd=ROOT, capture_output=True, text=True, timeout=15)
    help_text = help_result.stdout + help_result.stderr
    checks: list[dict[str, Any]] = []
    scenario_dir = work / "grpc-v09-scenarios"
    scenario_command = [sys.executable, str(ROOT / "test" / "grpc_v09_scenarios.py"),
                        "--binary", str(binary), "--output", str(scenario_dir)]
    scenario_run = subprocess.run(scenario_command, cwd=ROOT, text=True,
                                  capture_output=True, timeout=300)
    scenario_report_path = scenario_dir / "report.json"
    if not scenario_report_path.is_file():
        checks.extend([result("grpc_streaming", "FAIL", "v0.9 scenario gate did not emit a report"),
                       result("grpc_retry", "FAIL", "v0.9 scenario gate did not emit a report")])
    else:
        scenario_report = json.loads(scenario_report_path.read_text())
        scenario_checks = scenario_report.get("checks", {})
        for source_name, target_name in (("streaming_rpc", "grpc_streaming"),
                                         ("retry_unavailable", "grpc_retry")):
            row = scenario_checks.get(source_name)
            if not isinstance(row, dict) or row.get("status") not in {"PASS", "FAIL", "NOT RUN"}:
                checks.append(result(target_name, "FAIL", "v0.9 scenario result is malformed",
                                     scenario_returncode=scenario_run.returncode))
            else:
                checks.append(result(target_name, row["status"],
                                     "independent grpc_v09_scenarios.py result",
                                     scenario=row))
    previous_runtime = os.environ.get("FAULTDEBUG_RUNTIME_DIR")
    os.environ["FAULTDEBUG_RUNTIME_DIR"] = str(build_dir.resolve())
    try:
        import importlib.util
        helper_spec = importlib.util.spec_from_file_location("grpc_proxy_test_v09", ROOT / "test" / "grpc_proxy_test.py")
        if helper_spec is None or helper_spec.loader is None:
            raise ImportError("grpc_proxy_test helper could not be loaded")
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        _orchestrated_run = helper._orchestrated_run
        worker_dir = work / "grpc-workers"
        worker = _orchestrated_run(binary, worker_dir, 90.0, work,
                                   proxy_options=["--workers=2"],
                                   upstream_options=["--workers=2"], port_offset=20)
        worker_artifacts = sorted(worker_dir.glob("fault-*.fault"))
        if worker.get("status") != "PASS" or len(worker_artifacts) != 1:
            checks.append(result("grpc_workers", "FAIL", "worker scenario execution failed",
                                 run=worker, artifacts=len(worker_artifacts)))
        else:
            semantic = _grpc_semantic(worker_artifacts[0], "workers")
            checks.append(result("grpc_workers", "PASS", "two CompletionQueue workers executed and semantic trace passed",
                                 run_status=worker.get("status"), semantic=semantic)
                              if semantic["status"] == "PASS" else semantic)

        deadline_dir = work / "grpc-deadline"
        deadline = _orchestrated_run(binary, deadline_dir, 90.0, work,
                                     proxy_options=["--deadline-ms=10"],
                                     upstream_options=["--response-delay-ms=250"],
                                     expected_client_returncode=2, port_offset=40)
        deadline_artifacts = sorted(deadline_dir.glob("fault-*.fault"))
        if deadline.get("status") != "PASS" or len(deadline_artifacts) != 1:
            checks.append(result("grpc_deadline", "FAIL", "deadline scenario execution failed",
                                 run=deadline, artifacts=len(deadline_artifacts)))
        else:
            semantic = _grpc_semantic(deadline_artifacts[0], "deadline")
            checks.append(result("grpc_deadline", "PASS", "deadline cancellation retained explicit status 4",
                                 run_status=deadline.get("status"), semantic=semantic)
                              if semantic["status"] == "PASS" else semantic)
    except (ImportError, OSError, subprocess.SubprocessError, TimeoutError, ValueError) as exc:
        checks.extend([result("grpc_workers", "FAIL", f"worker scenario could not run: {exc}"),
                       result("grpc_deadline", "FAIL", f"deadline scenario could not run: {exc}")])
    finally:
        if previous_runtime is None:
            os.environ.pop("FAULTDEBUG_RUNTIME_DIR", None)
        else:
            os.environ["FAULTDEBUG_RUNTIME_DIR"] = previous_runtime
    return checks


def _v08_regression(build_dir: pathlib.Path | None, grpc_build_dir: pathlib.Path | None,
                    work: pathlib.Path) -> dict[str, Any]:
    output = work / "v08-regression"
    command = [sys.executable, str(ROOT / "test" / "v08_validation.py"),
               "--output", str(output)]
    if build_dir is not None:
        command.extend(["--build-dir", str(build_dir)])
    if grpc_build_dir is not None:
        command.extend(["--grpc-build-dir", str(grpc_build_dir)])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=300)
    report_path = output / "report.json"
    if not report_path.is_file():
        return result("v08_regression", "FAIL", "v0.8 regression did not emit report",
                      returncode=completed.returncode, stderr=completed.stderr[-1000:])
    report = json.loads(report_path.read_text())
    status = report.get("status")
    if status not in {"PASS", "FAIL", "NOT RUN"}:
        status = "FAIL"
    return result("v08_regression", status,
                  "v0.8 independent gate replayed without changing expectations",
                  returncode=completed.returncode, checks=report.get("checks", []))


def main() -> int:
    parser = argparse.ArgumentParser(description="independent v0.9 validation")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--build-dir", type=pathlib.Path)
    parser.add_argument("--grpc-build-dir", type=pathlib.Path)
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="faultdebug-v09-") as raw:
        work = pathlib.Path(raw)
        artifact, bundle, function_id, hashes = _make_mcp_fixture(work)
        checks = [_mcp_stdio(work, artifact, bundle, function_id, hashes)]
        checks.extend(_grpc_scenarios(ns.grpc_build_dir, work))
        checks.append(_v08_regression(ns.build_dir, ns.grpc_build_dir, work))
    statuses = [item["status"] for item in checks]
    overall = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "version": "0.9.0", "status": overall, "checks": checks}
    path = ns.output / "report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": overall, "checks": {state: statuses.count(state) for state in ("PASS", "FAIL", "NOT RUN")}, "report": str(path)}, sort_keys=True))
    return status_exit_code(overall)


if __name__ == "__main__":
    raise SystemExit(main())
