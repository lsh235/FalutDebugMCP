#!/usr/bin/env python3
"""Independent v1.1 install, capability, store, and regression gate.

The expected consumer results are defined by the fixture sources: the normal
path returns zero and the fault path performs a real null store.  The runner
does not use analyzer output as its oracle.  Optional gRPC coverage is handed
to the v0.9 gate and retains its PASS/FAIL/NOT RUN result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.artifact import read_artifact, write_artifact  # noqa: E402
from faultdebug.bundle import create_bundle, load_bundle  # noqa: E402
from faultdebug.evidence_store import EvidenceStore, SCHEMA_VERSION  # noqa: E402
from faultdebug.aggregate import ArtifactIndex  # noqa: E402
from faultdebug import __version__ as PACKAGE_VERSION  # noqa: E402


def result(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    if status not in {"PASS", "FAIL", "NOT RUN"}:
        raise ValueError(status)
    row = {"name": name, "status": status, "reason": reason}
    row.update(extra)
    return row


def status_exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[status]


def _run(command: list[str], *, cwd: pathlib.Path = ROOT, env: dict[str, str] | None = None,
         timeout: float = 120.0) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=cwd, env=env, text=True,
                                   capture_output=True, timeout=timeout, check=False)
        return {"command": command, "returncode": completed.returncode,
                "stdout": completed.stdout[-8000:], "stderr": completed.stderr[-8000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "returncode": None, "stdout": "",
                "stderr": str(exc)}


def _json_stdout(run: dict[str, Any]) -> dict[str, Any] | None:
    for line in reversed(str(run.get("stdout", "")).splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _versions() -> dict[str, Any]:
    versions: dict[str, Any] = {"python": sys.version}
    for name in ("cmake", "ctest", "clang", "clang++"):
        run = _run([name, "--version"], timeout=15)
        versions[name] = {"returncode": run["returncode"],
                          "version": str(run["stdout"]).splitlines()[:2],
                          "stderr": run["stderr"][-500:]}
    return versions


def _feature_names(payload: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for key in ("capabilities", "features", "tools"):
        value = payload.get(key)
        if isinstance(value, dict):
            values.extend(value.keys())
            values.extend(value.values())
        elif isinstance(value, list):
            values.extend(value)
    names: set[str] = set()
    for value in values:
        if isinstance(value, str):
            names.add(value.lower().replace("-", "_").replace(".", "_"))
        elif isinstance(value, dict):
            for key in ("name", "id", "feature"):
                if isinstance(value.get(key), str):
                    names.add(value[key].lower().replace("-", "_").replace(".", "_"))
    return names | {str(payload.get("version", "")).lower()}


def _store_report(session_id: str = "v10-store", process_id: str = "v10-process") -> dict[str, Any]:
    return {
        "session": {"schema": 1, "session_id": session_id, "participant_id": process_id},
        "process": {"pid": 7100, "parent_pid": 1, "start_monotonic_ns": 7100,
                    "identity": {"schema": 1, "session_id": session_id,
                                  "process_id": process_id, "process_generation": 1}},
        "target": {"returncode": 0, "signal": None},
        "collector": {"ok": True, "status": 0, "phase": "complete", "partial": False},
        "rpc_trace": {"schema": 1, "complete": True, "events": [
            {"sequence": 1, "rpc_id": "v10-rpc", "phase": "begin", "direction": 1,
             "method_id": 1, "monotonic_ns": 7101}]},
        "static_candidates": [{"kind": "possible_call", "function_id": "fn-v10"}],
        "evidence_class": "observed",
    }


def _make_store_fixture(work: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    artifact_dir = work / "store-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact = write_artifact(_store_report(), artifact_dir, 7100)
    db = work / "evidence.sqlite3"
    with EvidenceStore(db) as store:
        stored = store.ingest(artifact)
        if stored.get("status") != "ingested":
            raise RuntimeError(f"store fixture ingest failed: {stored}")
    malformed = work / "malformed.fault"
    malformed.write_bytes(artifact.read_bytes()[:-1])
    return artifact, db, malformed


def _old_store(work: pathlib.Path, artifact: pathlib.Path) -> pathlib.Path:
    old = work / "old-v06.sqlite3"
    report = read_artifact(artifact)
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE artifacts (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, pid INTEGER, trace_id TEXT, correlation_id TEXT, parent_pid INTEGER, start_ns INTEGER, payload TEXT NOT NULL, updated_ns INTEGER NOT NULL)")
    conn.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                 ("legacy.fault", _sha256(artifact), 7100, None, None, 1, 7100,
                  json.dumps(report, sort_keys=True), 1))
    conn.commit(); conn.close()
    return old


def _install_consumer(ns: argparse.Namespace, work: pathlib.Path) -> dict[str, Any]:
    prefix = ns.install_prefix.resolve()
    source = ROOT / "test" / "programs" / "install_consumer"
    if not source.is_dir():
        return result("install_consumer", "FAIL", "consumer fixture is missing")
    if not ns.build_dir.is_dir():
        return result("install_consumer", "NOT RUN", "--build-dir does not exist", build_dir=str(ns.build_dir))
    install_run = _run(["cmake", "--install", str(ns.build_dir), "--prefix", str(prefix)], timeout=180)
    runtime = next((prefix / candidate for candidate in ("lib", "lib64")
                    if (prefix / candidate / "libfaultdebug_runtime.so").is_file()), None)
    cmake_dir = prefix / "share" / "faultdebug" / "cmake"
    if install_run["returncode"] != 0 or runtime is None or not (cmake_dir / "FaultDebugLegacy.cmake").is_file():
        return result("install_consumer", "FAIL", "project install did not expose runtime and CMake integration",
                      install=install_run, prefix=str(prefix), runtime=str(runtime) if runtime else None)
    consumer_build = work / "consumer-build"
    configure = _run(["cmake", "-S", str(source), "-B", str(consumer_build),
                      "-DFAULTDEBUG_CMAKE_DIR=" + str(cmake_dir),
                      "-DFAULTDEBUG_RUNTIME_DIR=" + str(runtime),
                      "-DCMAKE_BUILD_TYPE=Debug"], timeout=180)
    build = _run(["cmake", "--build", str(consumer_build), "--parallel", "2"], timeout=180)
    c_binary = consumer_build / "fd_install_c"
    cpp_binary = consumer_build / "fd_install_cpp"
    if configure["returncode"] != 0 or build["returncode"] != 0 or not c_binary.is_file() or not cpp_binary.is_file():
        return result("install_consumer", "FAIL", "installed CMake consumer did not configure/build",
                      configure=configure, build=build)
    env = dict(os.environ)
    env["FAULTDEBUG_RUNTIME_DIR"] = str(runtime)
    normal: dict[str, Any] = {}
    faults: dict[str, Any] = {}
    artifact_hashes: dict[str, str] = {}
    for label, binary in (("c", c_binary), ("cpp", cpp_binary)):
        clean = _run([str(binary)], env=env, timeout=30)
        normal[label] = clean
        artifact_dir = work / ("artifacts-" + label)
        launch = [str(ns.python), "-m", "faultdebug.cli", "run", "--artifact-dir", str(artifact_dir),
                  "--session-id", "v10-install", "--process-id", "consumer-" + label,
                  "--process-role", label, "--", str(binary), "--fault"]
        fault = _run(launch, env={**env, "PYTHONPATH": str(ROOT)}, timeout=45)
        paths = sorted(artifact_dir.glob("fault-*.fault"))
        faults[label] = {"run": fault, "artifacts": [str(path) for path in paths]}
        if len(paths) == 1:
            artifact_hashes[label] = _sha256(paths[0])
            report = read_artifact(paths[0])
            faults[label]["signal"] = (report.get("target") or {}).get("signal")
            faults[label]["crashes"] = report.get("crashes", [])
            faults[label]["events"] = sum(len(row.get("events", [])) for row in report.get("threads", []))
    clean_ok = all(row.get("returncode") == 0 for row in normal.values())
    fault_ok = all(len(row.get("artifacts", [])) == 1 and row.get("signal") == signal.SIGSEGV
                   and row.get("crashes") and row.get("events", 0) > 0
                   for row in faults.values())
    if not clean_ok or not fault_ok:
        return result("install_consumer", "FAIL", "installed consumer clean/fault semantics did not match fixture contract",
                      configure=configure, build=build, normal=normal, faults=faults,
                      artifact_sha256=artifact_hashes)

    # Build an immutable source/index/binary bundle and independently check a
    # known fixture function's exact source range and manifest hash.
    index = work / "consumer-index.json"
    indexed = _run([str(ns.python), "-m", "faultdebug.cli", "index",
                    str(consumer_build / "compile_commands.json"), "-o", str(index)], env={"PYTHONPATH": str(ROOT), **env}, timeout=120)
    bundle_dir = work / "consumer-bundle"
    bundled = _run([str(ns.python), "-m", "faultdebug.cli", "bundle", "--source-root", str(source),
                    "--index", str(index), "--binary", str(c_binary), "--binary", str(cpp_binary),
                    "--output", str(bundle_dir)], env={"PYTHONPATH": str(ROOT), **env}, timeout=120)
    citations: list[dict[str, Any]] = []
    if indexed["returncode"] == 0 and bundled["returncode"] == 0:
        bundle = load_bundle(bundle_dir)
        rows = bundle.index_rows()
        selected = [row for row in rows if row.get("name") in {"c_entry", "cpp_entry"} and row.get("is_definition")]
        for row in selected:
            source_path = bundle.source_path(row.get("file", ""))
            if source_path is None:
                continue
            entry = next((item for item in bundle.manifest["files"] if item["path"] == "source/" + source_path.relative_to(bundle_dir / "source").as_posix()), None)
            citations.append({"function_id": row["id"], "name": row["name"],
                              "file": str(source_path.relative_to(bundle_dir)),
                              "start_line": row["source_range"]["start"],
                              "end_line": row["source_range"]["end"],
                              "sha256": _sha256(source_path),
                              "manifest_sha256": entry.get("sha256") if entry else None})
    source_ok = len(citations) >= 2 and all(row["sha256"] == row["manifest_sha256"] and row["start_line"] <= row["end_line"] for row in citations)
    if not source_ok:
        return result("install_consumer", "FAIL", "consumer source citation/hash verification failed",
                      configure=configure, build=build, normal=normal, faults=faults,
                      artifact_sha256=artifact_hashes, index=indexed, bundle=bundled, citations=citations)
    return result("install_consumer", "PASS", "installed C/C++ consumer configured, built, cleanly terminated, faulted, and resolved source evidence",
                  configure=configure, build=build, normal=normal, faults=faults,
                  artifact_sha256=artifact_hashes, citations=citations,
                  runtime=str(runtime), prefix=str(prefix))


def _capability_cli(ns: argparse.Namespace, work: pathlib.Path, db: pathlib.Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    capabilities = _run([str(ns.python), "-m", "faultdebug.cli", "capabilities"], env=env, timeout=30)
    payload = _json_stdout(capabilities)
    names = _feature_names(payload) if payload else set()
    required_tools = {"open_fault", "get_thread_trace", "resolve_addresses", "get_function_source", "get_call_relations"}
    advertised_tools = set(payload.get("required_tools", [])) if isinstance(payload, dict) and isinstance(payload.get("required_tools"), list) else set()
    cap_ok = (capabilities["returncode"] == 0 and isinstance(payload, dict)
              and payload.get("contract_version") == "1.0" and required_tools <= advertised_tools)
    check = _run([str(ns.python), "-m", "faultdebug.cli", "evidence-health", "--db", str(db)], env=env, timeout=30)
    check_payload = _json_stdout(check)
    compatible = bool(check_payload and str(check_payload.get("status", "")).lower() in
                      {"healthy", "compatible_additive_upgrade"})
    if not cap_ok or check["returncode"] != 0 or not compatible:
        return result("capability_cli", "FAIL", "capability or store compatibility CLI contract failed",
                      capabilities=capabilities, capability_payload=payload,
                      check_store=check, check_store_payload=check_payload)
    return result("capability_cli", "PASS", "capabilities and current store compatibility were reported as structured JSON",
                  capability_payload=payload, feature_names=sorted(names), check_store=check_payload,
                  commands=[capabilities["command"], check["command"]])


def _mcp_response(stream: Any, deadline: float = 30.0,
                  noise: list[str] | None = None) -> dict[str, Any] | None:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        ready, _, _ = select.select([stream], [], [], max(0.0, end - time.monotonic()))
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


def _drain_mcp_stderr(stream: Any, chunks: list[str]) -> None:
    for line in stream:
        chunks.append(line)
        if sum(map(len, chunks)) > 8192:
            chunks[:] = ["".join(chunks)[-8192:]]


def _mcp_value(message: dict[str, Any]) -> Any:
    if "error" in message:
        raise RuntimeError(str(message["error"]))
    result_value = message.get("result", {})
    if isinstance(result_value, dict) and "structuredContent" in result_value:
        return result_value["structuredContent"]
    content = result_value.get("content") if isinstance(result_value, dict) else None
    for item in content or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                return json.loads(item.get("text", ""))
            except json.JSONDecodeError:
                return item.get("text")
    return result_value


def _mcp_capabilities(ns: argparse.Namespace, work: pathlib.Path, db: pathlib.Path) -> dict[str, Any]:
    probe = _run([str(ns.python), "-c", "import mcp"], timeout=15)
    if probe["returncode"] != 0:
        return result("mcp_capabilities_store", "NOT RUN", "official MCP Python SDK is unavailable")
    root = db.parent
    process = subprocess.Popen([str(ns.python), "-m", "faultdebug.cli", "mcp", "--root", str(root)],
                               cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="backslashreplace",
                               bufsize=1)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "faultdebug-v10", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_capabilities", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "check_store", "arguments": {"db": db.name}}},
    ]
    responses: dict[int, dict[str, Any]] = {}
    stderr_chunks: list[str] = []
    stdout_noise: list[str] = []
    stderr_reader = threading.Thread(target=_drain_mcp_stderr,
                                     args=(process.stderr, stderr_chunks), daemon=True)
    stderr_reader.start()
    exchange_result: dict[str, Any] | None = None

    def finish(row: dict[str, Any]) -> dict[str, Any]:
        nonlocal exchange_result
        exchange_result = row
        return row

    try:
        assert process.stdin is not None and process.stdout is not None
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n"); process.stdin.flush()
            if "id" in request:
                response = _mcp_response(process.stdout, noise=stdout_noise)
                if response is None:
                    break
                responses[int(response["id"])] = response
        missing = sorted({1, 2, 3, 4} - set(responses))
        if missing:
            return finish(result("mcp_capabilities_store", "FAIL", "MCP initialize/tools/call response missing", missing=missing))
        tools = _mcp_value(responses[2]); tool_names = {row.get("name") for row in (tools.get("tools", []) if isinstance(tools, dict) else [])}
        required = {"get_capabilities", "check_store"}
        capabilities = _mcp_value(responses[3]); checked = _mcp_value(responses[4])
        names = _feature_names(capabilities) if isinstance(capabilities, dict) else set()
        required_tools = {"open_fault", "get_thread_trace", "resolve_addresses", "get_function_source", "get_call_relations"}
        advertised_tools = set(capabilities.get("required_tools", [])) if isinstance(capabilities, dict) and isinstance(capabilities.get("required_tools"), list) else set()
        compatible = isinstance(checked, dict) and str(checked.get("status", "")).lower() in {"healthy", "compatible_additive_upgrade"}
        if (not required <= tool_names or not isinstance(capabilities, dict)
                or capabilities.get("contract_version") != "1.0"
                or not required_tools <= advertised_tools or not compatible):
            return finish(result("mcp_capabilities_store", "FAIL", "MCP capability/store contract failed",
                                 tools=sorted(tool_names), capabilities=capabilities, check_store=checked))
        return finish(result("mcp_capabilities_store", "PASS", "MCP initialize, tools/list, get_capabilities, and check_store passed",
                             tools=sorted(tool_names), feature_names=sorted(names), capabilities=capabilities, check_store=checked))
    except (AssertionError, OSError, RuntimeError, ValueError, TypeError) as exc:
        return finish(result("mcp_capabilities_store", "FAIL", f"MCP capability exchange failed: {exc}"))
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


def _store_compatibility(work: pathlib.Path, artifact: pathlib.Path, db: pathlib.Path, malformed: pathlib.Path) -> dict[str, Any]:
    legacy = _old_store(work, artifact)
    try:
        with EvidenceStore(legacy) as migrated:
            old_ok = int(migrated.db.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION and migrated.list_sessions()["total"] == 1
        with EvidenceStore(db) as store:
            bad = store.ingest(malformed)
            quarantine = store.quarantine_rows()
        if not old_ok or bad.get("status") != "quarantined" or quarantine.get("total", 0) < 1:
            return result("store_compatibility", "FAIL", "old schema migration or malformed quarantine failed",
                          old_schema=old_ok, malformed=bad, quarantine=quarantine)
        return result("store_compatibility", "PASS", "legacy store migrated and malformed artifact was quarantined",
                      old_schema_version=SCHEMA_VERSION, malformed=bad, quarantine=quarantine)
    except Exception as exc:
        return result("store_compatibility", "FAIL", f"store compatibility check failed: {exc}")


def _ctest(ns: argparse.Namespace) -> dict[str, Any]:
    if not ns.ctest_dir.is_dir() or not (ns.ctest_dir / "CTestTestfile.cmake").is_file():
        return result("native_ctest", "NOT RUN", "CTest build directory is unavailable", ctest_dir=str(ns.ctest_dir))
    run = _run(["ctest", "--test-dir", str(ns.ctest_dir), "--output-on-failure"], timeout=600)
    return result("native_ctest", "PASS" if run["returncode"] == 0 else "FAIL",
                  "native CTest suite completed" if run["returncode"] == 0 else "native CTest suite failed",
                  run=run)


def _package_metadata() -> dict[str, Any]:
    metadata_path = ROOT / "pyproject.toml"
    try:
        document = tomllib.loads(metadata_path.read_text())
        project = document["project"]
        version = str(project.get("version", ""))
        scripts = project.get("scripts", {})
        expected_scripts = {"faultdebug", "fault-debug", "faultdebug-collector", "faultdebug-agent"}
        valid = (version == PACKAGE_VERSION and project.get("requires-python") == ">=3.12,<3.13"
                 and expected_scripts <= set(scripts))
        return result("package_metadata", "PASS" if valid else "FAIL",
                      "package metadata matches the source version and required contract" if valid else "package metadata is inconsistent",
                      version=version, requires_python=project.get("requires-python"),
                      scripts=sorted(scripts), metadata=str(metadata_path))
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        return result("package_metadata", "FAIL", f"package metadata could not be read: {exc}", metadata=str(metadata_path))


def _v09(ns: argparse.Namespace, work: pathlib.Path) -> dict[str, Any]:
    output = work / "v09"
    command = [str(ns.python), str(ROOT / "test" / "v09_validation.py"),
               "--output", str(output), "--build-dir", str(ns.build_dir)]
    if ns.grpc_build_dir is not None:
        command.extend(["--grpc-build-dir", str(ns.grpc_build_dir)])
    run = _run(command, timeout=900)
    path = output / "report.json"
    if not path.is_file():
        return result("v09_regression", "FAIL", "v0.9 report was not emitted", run=run)
    report = json.loads(path.read_text())
    return result("v09_regression", report.get("status", "FAIL") if report.get("status") in {"PASS", "FAIL", "NOT RUN"} else "FAIL",
                  "v0.9 independent acceptance replayed", run=run, report=report)


def main() -> int:
    parser = argparse.ArgumentParser(description="independent v1.1 acceptance")
    parser.add_argument("--build-dir", type=pathlib.Path, required=True)
    parser.add_argument("--install-prefix", type=pathlib.Path, required=True)
    parser.add_argument("--ctest-dir", type=pathlib.Path)
    parser.add_argument("--grpc-build-dir", type=pathlib.Path)
    parser.add_argument("--python", type=pathlib.Path, default=pathlib.Path(sys.executable))
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    ns.build_dir = ns.build_dir.resolve(); ns.install_prefix = ns.install_prefix.resolve()
    ns.ctest_dir = (ns.ctest_dir or ns.build_dir).resolve()
    # Preserve a virtualenv interpreter symlink.  Resolving it to the system
    # Python silently drops libclang/MCP dependencies from the acceptance env.
    ns.python = ns.python.absolute()
    ns.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="faultdebug-v10-") as raw:
        work = pathlib.Path(raw)
        artifact, db, malformed = _make_store_fixture(work)
        checks = [
            _install_consumer(ns, work),
            _capability_cli(ns, work, db),
            _mcp_capabilities(ns, work, db),
            _store_compatibility(work, artifact, db, malformed),
            _ctest(ns),
            _package_metadata(),
            _v09(ns, work),
        ]
        hashes = {"fixture_artifact": _sha256(artifact), "malformed_fixture": _sha256(malformed)}
    statuses = [row["status"] for row in checks]
    overall = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "version": PACKAGE_VERSION, "status": overall,
              "tool_versions": _versions(),
              "configuration": {"build_dir": str(ns.build_dir), "install_prefix": str(ns.install_prefix),
                                "ctest_dir": str(ns.ctest_dir), "grpc_build_dir": str(ns.grpc_build_dir) if ns.grpc_build_dir else None,
                                "python": str(ns.python)},
              "artifact_hashes": hashes, "checks": checks}
    path = ns.output / "report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": overall, "checks": {state: statuses.count(state) for state in ("PASS", "FAIL", "NOT RUN")}, "report": str(path)}, sort_keys=True))
    return status_exit_code(overall)


if __name__ == "__main__":
    raise SystemExit(main())
