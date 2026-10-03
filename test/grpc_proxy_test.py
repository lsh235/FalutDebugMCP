#!/usr/bin/env python3
"""Build and exercise the asynchronous gRPC proxy fixture.

This is an integration gate for the C++ fixture, rather than a unit test of
the Python decoder.  It launches the fixture through ``faultdebug run`` and
uses a small independent FDAR reader to validate the captured evidence.  The
product's inspect/symbolization output is recorded as a secondary result; it
is never used to decide whether the event sequence or crash metadata is
correct.

The fixture is intentionally discovered instead of hard-coded to one build
tree.  This keeps the gate useful for a normal CMake build and for a clean
external build directory:

    python3 test/grpc_proxy_test.py --build-dir build \
        --output test-results/grpc-proxy

Use ``--target-arg`` to select another fixture scenario.  The default
argument ``fault`` is the scenario contract for the asynchronous proxy
fixture.  If the gRPC toolchain or fixture is not available, the report is
``NOT RUN`` and the command exits successfully, matching the external-project
test contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import resource
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
FDAR_HEADER = struct.Struct("<4sHHQI32s")
ENTER, EXIT = 1, 2
CRASHED, PARTIAL = 1 << 1, 1 << 9


def _status(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"name": name, "status": status, "reason": reason}
    value.update(extra)
    return value


def _run(command: list[str], *, cwd: pathlib.Path | None = None,
         timeout: float = 120.0, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=cwd, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-8000:],
            "stderr": completed.stderr[-8000:],
            "seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": (exc.stdout or "")[-8000:],
            "stderr": "timeout",
            "seconds": round(time.monotonic() - started, 3),
        }
    except OSError as exc:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "seconds": round(time.monotonic() - started, 3),
        }


def _tool_version(name: str) -> str | None:
    executable = shutil.which(name)
    if not executable:
        return None
    result = _run([executable, "--version"], timeout=10)
    text = (result.get("stdout") or result.get("stderr") or "").strip()
    return text.splitlines()[0] if text else "available"


def _find_binary(build_dir: pathlib.Path, explicit: pathlib.Path | None) -> pathlib.Path | None:
    candidates: list[pathlib.Path] = []
    if explicit:
        candidates.append(explicit)
    configured = os.environ.get("FAULTDEBUG_GRPC_PROXY_BINARY")
    if configured:
        candidates.append(pathlib.Path(configured))
    names = (
        "fd_grpc_async_proxy", "fd_grpc_proxy", "grpc_async_proxy",
        "grpc_proxy_async", "faultdebug_grpc_proxy",
    )
    for name in names:
        candidates.extend((build_dir / name, build_dir / "test" / name))
    for path in candidates:
        path = path.expanduser().resolve()
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def _build_proxy(build_dir: pathlib.Path, target: str, explicit: str | None) -> dict[str, Any]:
    if explicit:
        return _run(shlex.split(explicit), cwd=ROOT, timeout=900.0)
    if not (build_dir / "CMakeCache.txt").is_file():
        return {"command": [], "returncode": None, "stdout": "", "stderr":
                "build directory has no CMakeCache.txt", "seconds": 0.0}
    # CMake intentionally configures the gRPC fixture as optional.  A build
    # tree created without its package therefore means NOT RUN, whereas a
    # declared target that fails to compile is a real FAIL.
    targets = _run(["cmake", "--build", str(build_dir), "--target", "help"], timeout=60.0)
    target_text = (targets.get("stdout", "") + "\n" + targets.get("stderr", ""))
    if targets.get("returncode") != 0 or not re.search(rf"(?:^|[\s/]){re.escape(target)}(?:$|[\s/:])", target_text, re.MULTILINE):
        return {"command": ["cmake", "--build", str(build_dir), "--target", target],
                "returncode": None, "stdout": target_text[-8000:],
                "stderr": f"optional gRPC target {target!r} is not configured",
                "seconds": targets.get("seconds", 0.0)}
    return _run(["cmake", "--build", str(build_dir), "--target", target, "-j2"], timeout=900.0)


def _read_fdar(path: pathlib.Path) -> dict[str, Any]:
    """Read FDAR without importing faultdebug.format or artifact.py."""
    raw = path.read_bytes()
    if len(raw) < FDAR_HEADER.size:
        raise ValueError("artifact is shorter than FDAR header")
    magic, version, flags, length, pid, digest = FDAR_HEADER.unpack_from(raw)
    payload = raw[FDAR_HEADER.size:]
    if magic != b"FDAR" or version != 1:
        raise ValueError("unsupported FDAR magic/version")
    if length != len(payload) or hashlib.sha256(payload).digest() != digest:
        raise ValueError("artifact length/checksum mismatch")
    report = json.loads(payload)
    if not isinstance(report, dict):
        raise ValueError("artifact payload is not an object")
    report["_fdar"] = {"flags": flags, "pid": pid, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()}
    return report


def _independent_checks(report: dict[str, Any], binary: pathlib.Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    header = report.get("header", {})
    status = int(header.get("status", 0))
    checks.append(_status("crash_status", "PASS" if status & (CRASHED | PARTIAL) else "FAIL",
                          f"header.status={status}"))
    crashes = report.get("crashes", [])
    crash = crashes[0] if crashes else {}
    signal_ok = int(crash.get("signal", 0)) == signal.SIGSEGV
    pc_ok = int(crash.get("pc", 0)) != 0
    code_ok = int(crash.get("si_code", 0)) == 1  # SEGV_MAPERR
    address_ok = int(crash.get("fault_address", -1)) == 0
    checks.append(_status("segv_metadata", "PASS" if signal_ok and pc_ok else "FAIL",
                          f"signal={crash.get('signal')}, pc={crash.get('pc')}, "
                          f"si_code={crash.get('si_code')}, fault_address={crash.get('fault_address')}"))
    checks.append(_status("segv_origin", "PASS" if code_ok and address_ok else "FAIL",
                          "SEGV_MAPERR at the intentional null address" if code_ok and address_ok
                          else f"si_code={crash.get('si_code')}, fault_address={crash.get('fault_address')}"))

    modules = report.get("modules", [])
    ranges = [(int(row.get("text_start", 0)), int(row.get("text_end", 0)))
              for row in modules]
    module_match = any(pathlib.Path(str(row.get("path", ""))).name == binary.name
                       for row in modules)
    # The runtime's main executable mapping can legitimately have an empty
    # pathname in /proc/self/maps.  The crash PC being inside that anonymous
    # first text mapping is independent evidence for the target module.
    if not module_match and int(crash.get("pc", 0)):
        module_match = any(not row.get("path") and int(row.get("text_start", 0)) <= int(crash.get("pc", 0)) < int(row.get("text_end", 0))
                           for row in modules)
    checks.append(_status("proxy_module", "PASS" if module_match else "FAIL",
                          f"captured modules={len(modules)}"))

    all_events: list[dict[str, Any]] = []
    nesting_ok = True
    incomplete_threads = False
    sequence_ok = True
    containment_ok = True
    for thread in report.get("threads", []):
        generation = thread.get("generation")
        incomplete_threads = incomplete_threads or int(thread.get("dropped_count", 0)) > 0
        events = sorted(thread.get("events", []), key=lambda row: int(row.get("sequence", -1)))
        previous = None
        stack: list[int] = []
        for event in events:
            all_events.append(event)
            sequence = int(event.get("sequence", -1))
            if previous is not None and sequence <= previous:
                sequence_ok = False
            previous = sequence
            if event.get("generation") != generation:
                sequence_ok = False
            event_type = int(event.get("type", 0))
            function = int(event.get("function", 0))
            if event_type == ENTER:
                stack.append(function)
            elif event_type == EXIT:
                if not stack or stack.pop() != function:
                    nesting_ok = False
            elif event_type not in (3, 4, 5):
                nesting_ok = False
            if event_type in (ENTER, EXIT) and not any(lo <= function < hi for lo, hi in ranges):
                containment_ok = False
        # A crash can interrupt a non-empty stack.  We require valid prefixes,
        # but do not claim a complete stack from an intentionally interrupted RPC.
    checks.append(_status("event_sequences", "PASS" if sequence_ok else "FAIL",
                          f"events={len(all_events)}"))
    nesting_reason = ("enter/exit records preserve valid prefixes"
                      if not incomplete_threads else
                      "ring overflow detected; retained enter/exit records are not claimed as a complete stack")
    checks.append(_status("event_nesting_prefix", "PASS" if nesting_ok else
                          ("PASS" if incomplete_threads else "FAIL"), nesting_reason))
    checks.append(_status("event_module_containment", "PASS" if containment_ok else "FAIL",
                          "function addresses are inside captured module ranges"))
    has_enter = any(int(row.get("type", 0)) == ENTER for row in all_events)
    checks.append(_status("trace_present", "PASS" if has_enter else "FAIL",
                          f"retained events={len(all_events)}"))
    return checks


def _independent_symbolize(report: dict[str, Any], binary: pathlib.Path) -> dict[str, Any]:
    expected_function = "fd_grpc_trace_proxy_fault_after_response"
    expected_file = "trace.cc"
    expected_line = 26
    crash = (report.get("crashes") or [{}])[0]
    pc = int(crash.get("pc", 0))
    module = next((row for row in report.get("modules", [])
                   if int(row.get("text_start", 0)) <= pc < int(row.get("text_end", 0))), None)
    if not module or not pc:
        return {"status": "FAIL", "reason": "crash PC has no unique captured module"}
    bias = int(module.get("load_bias", 0))
    relative = pc - bias
    local_tools = (
        ROOT / ".tools" / "bin" / "llvm-symbolizer",
        ROOT / ".tools" / "clang" / "usr" / "bin" / "llvm-symbolizer-18",
    )
    symbolizer = (os.environ.get("FAULTDEBUG_LLVM_SYMBOLIZER")
                  or next((str(path) for path in local_tools if path.is_file()), None)
                  or shutil.which("llvm-symbolizer-18")
                  or shutil.which("llvm-symbolizer"))
    if not symbolizer:
        return {"status": "NOT RUN", "reason": "llvm-symbolizer is unavailable", "pc": pc}
    result = _run([symbolizer, "--no-debuginfod", f"--obj={binary}",
                   "--functions=linkage", "--inlining", hex(relative)], timeout=10)
    lines = [line.strip() for line in result.get("stdout", "").splitlines() if line.strip()]
    location = next((line for line in lines if re.match(r"^.+:\d+(?::\d+)?$", line)), None)
    if not location:
        return {"status": "FAIL", "reason": "independent symbolizer returned no source location",
                "pc": pc, "relative": relative, "stdout": result.get("stdout", "")}
    match = re.match(r"^(.*?):(\d+)(?::(\d+))?$", location)
    function = lines[0] if lines else None
    file_name = match.group(1) if match else location
    line = int(match.group(2)) if match else None
    function_ok = function == expected_function
    file_ok = pathlib.Path(file_name).name == expected_file
    line_ok = line == expected_line
    return {"status": "PASS" if function_ok and file_ok and line_ok else "FAIL",
            "reason": "expected proxy fault boundary resolved" if function_ok and file_ok and line_ok
            else "resolved location does not match the intentional proxy fault",
            "expected": {"function": expected_function, "file": expected_file, "line": expected_line},
            "actual": {"function": function, "file": file_name, "line": line},
            "pc": pc, "relative": relative, "function": function, "file": file_name,
            "line": line, "symbolizer": symbolizer}


def _boundary_trace(report: dict[str, Any], binary: pathlib.Path) -> dict[str, Any]:
    """Independently verify the four application-owned RPC boundary markers."""
    expected = {
        "fd_grpc_trace_proxy_received",
        "fd_grpc_trace_proxy_forwarded",
        "fd_grpc_trace_proxy_response",
        "fd_grpc_trace_proxy_fault_after_response",
    }
    nm = shutil.which("nm")
    if not nm:
        return {"status": "NOT RUN", "reason": "nm is unavailable",
                "expected": sorted(expected)}
    try:
        nm_result = subprocess.run([nm, "-n", "--defined-only", str(binary)],
                                   text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=10,
                                   check=False)
        nm_output = nm_result.stdout
    except (OSError, subprocess.SubprocessError):
        nm_output = ""
    symbol_by_address: dict[int, str] = {}
    for line in nm_output.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) == 3:
            try:
                symbol_by_address[int(fields[0], 16)] = fields[2]
            except ValueError:
                pass
    observed: list[str] = []
    for thread in report.get("threads", []):
        for event in sorted(thread.get("events", []), key=lambda row: int(row.get("sequence", -1))):
            if int(event.get("type", 0)) != ENTER:
                continue
            function = int(event.get("function", 0))
            module = next((row for row in report.get("modules", [])
                           if int(row.get("text_start", 0)) <= function < int(row.get("text_end", 0))), None)
            if not module:
                continue
            relative = function - int(module.get("load_bias", 0))
            name = symbol_by_address.get(relative)
            if name:
                observed.append(name)
    observed_set = set(observed)
    missing = sorted(expected - observed_set)
    return {
        "status": "PASS" if not missing else "FAIL",
        "expected": sorted(expected),
        "observed": sorted(observed_set),
        "missing": missing,
        "reason": "all application-owned RPC boundaries were retained" if not missing
        else "one or more RPC boundary markers were not retained",
    }


def _wait_port(host: str, port: int, process: subprocess.Popen[str], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _no_core() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _stop_process_group(process: subprocess.Popen[str]) -> None:
    """Terminate a runner and its instrumented target without leaving orphans."""
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=2.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        process.kill()
    process.wait()


def _orchestrated_run(binary: pathlib.Path, artifact_dir: pathlib.Path,
                      timeout: float, output: pathlib.Path, *,
                      fault_after_response: bool = True,
                      port_offset: int = 0,
                      proxy_options: list[str] | None = None,
                      upstream_options: list[str] | None = None,
                      expected_client_returncode: int = 0) -> dict[str, Any]:
    """Run upstream, instrumented proxy, and client as three processes.

    Only the proxy is wrapped by faultdebug.  The upstream and client are
    deliberately ordinary processes so the resulting artifact demonstrates
    that the asynchronous proxy's own CompletionQueue path was retained.
    """
    # Each invocation owns exactly one artifact directory.  Remove only stale
    # fault files from that directory so a previous clean/fault run cannot
    # affect the current expectation; reports, logs, and artifacts elsewhere
    # remain untouched for diagnosis.
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for stale in artifact_dir.glob("fault-*.fault"):
        try:
            stale.unlink()
        except OSError:
            pass
    # Use per-run ports so an interrupted previous run cannot make readiness
    # appear successful for the wrong process.
    base = 43000 + (os.getpid() % 1000) * 2 + port_offset
    upstream_port, proxy_port = base, base + 1
    host = "127.0.0.1"
    upstream_addr, proxy_addr = f"{host}:{upstream_port}", f"{host}:{proxy_port}"
    common_env = dict(os.environ)
    common_env["PYTHONPATH"] = str(ROOT) + (os.pathsep + common_env["PYTHONPATH"] if common_env.get("PYTHONPATH") else "")
    command_base = [str(binary)]
    upstream_cmd = command_base + ["--mode=upstream", f"--listen={upstream_addr}", "--max-calls=1"] + list(upstream_options or [])
    proxy_target_cmd = command_base + ["--mode=proxy", f"--listen={proxy_addr}", f"--upstream={upstream_addr}"]
    proxy_target_cmd.append("--fault-after-response" if fault_after_response else "--max-calls=1")
    proxy_target_cmd.extend(proxy_options or [])
    client_cmd = command_base + ["--mode=client", f"--listen={proxy_addr}", "--message=faultdebug-grpc"]
    upstream = subprocess.Popen(upstream_cmd, cwd=ROOT, env=common_env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                preexec_fn=_no_core, start_new_session=True)
    proxy_runner_cmd = [sys.executable, "-m", "faultdebug.cli", "run",
                        "--artifact-dir", str(artifact_dir),
                        "--trace-id", "grpc-proxy-test",
                        "--correlation-id", "grpc-proxy-test",
                        "--", *proxy_target_cmd]
    proxy = subprocess.Popen(proxy_runner_cmd, cwd=ROOT, env=common_env, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             preexec_fn=_no_core, start_new_session=True)
    stages: dict[str, Any] = {"upstream": {"command": upstream_cmd},
                              "proxy": {"command": proxy_runner_cmd},
                              "client": {"command": client_cmd},
                              "addresses": {"upstream": upstream_addr, "proxy": proxy_addr}}
    try:
        upstream_ready = _wait_port(host, upstream_port, upstream, min(timeout, 20.0))
        stages["upstream"]["ready"] = upstream_ready
        proxy_ready = _wait_port(host, proxy_port, proxy, min(timeout, 20.0))
        stages["proxy"]["ready"] = proxy_ready
        if not upstream_ready or not proxy_ready:
            stages["client"] = {"status": "NOT RUN", "reason": "upstream/proxy did not become ready", "command": client_cmd}
        else:
            client_result = _run(client_cmd, cwd=ROOT, timeout=min(timeout, 30.0), env=common_env)
            stages["client"] = client_result
        try:
            proxy_out, proxy_err = proxy.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop_process_group(proxy)
            proxy_out, proxy_err = proxy.communicate()
            stages["proxy"]["timeout"] = True
        try:
            upstream_out, upstream_err = upstream.communicate(timeout=10.0)
        except subprocess.TimeoutExpired:
            _stop_process_group(upstream)
            upstream_out, upstream_err = upstream.communicate()
            stages["upstream"]["timeout"] = True
        stages["proxy"].update({"returncode": proxy.returncode, "stdout": proxy_out[-8000:], "stderr": proxy_err[-8000:]})
        stages["upstream"].update({"returncode": upstream.returncode, "stdout": upstream_out[-8000:], "stderr": upstream_err[-8000:]})
        client = stages["client"]
        expected_proxy = 128 + signal.SIGSEGV if fault_after_response else 0
        stages["status"] = "PASS" if (client.get("returncode") == expected_client_returncode and proxy.returncode == expected_proxy and upstream.returncode == 0) else "FAIL"
        stages["expected"] = {"client_returncode": expected_client_returncode, "proxy_returncode": expected_proxy, "upstream_returncode": 0}
        stages["fault_after_response"] = fault_after_response
        return stages
    finally:
        for process in (proxy, upstream):
            _stop_process_group(process)


def _product_evidence(artifact: pathlib.Path, build_dir: pathlib.Path,
                      output: pathlib.Path, binary: pathlib.Path) -> dict[str, Any]:
    """Collect inspect/bundle output as corroborating evidence only."""
    compdb = build_dir / "compile_commands.json"
    snapshot = build_dir / "faultdebug-source-snapshot" / "files"
    bundle = output / "bundle"
    index = output / "grpc-index.json"
    if not compdb.is_file() or not snapshot.is_dir():
        return {"status": "NOT RUN", "reason": "compile database or source snapshot unavailable"}
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    index_result = _run([sys.executable, "-m", "faultdebug.cli", "index", str(compdb), "-o", str(index)], cwd=ROOT, timeout=120, env=env)
    if index_result.get("returncode") != 0:
        if "libclang Python bindings are required" in index_result.get("stderr", ""):
            return {"status": "NOT RUN", "stage": "index", "reason": "libclang Python bindings are unavailable", "result": index_result}
        return {"status": "FAIL", "stage": "index", "result": index_result}
    bundle_result = _run([sys.executable, "-m", "faultdebug.cli", "bundle", "--source-root", str(snapshot), "--index", str(index), "--binary", str(binary), "--output", str(bundle)], cwd=ROOT, timeout=120, env=env)
    if bundle_result.get("returncode") != 0:
        return {"status": "FAIL", "stage": "bundle", "result": bundle_result}
    try:
        crash_pc = int((_read_fdar(artifact).get("crashes") or [{}])[0].get("pc", 0))
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
        crash_pc = 0
    inspect_command = [sys.executable, "-m", "faultdebug.cli", "inspect", str(artifact), "--bundle", str(bundle)]
    if crash_pc:
        inspect_command += ["--address", hex(crash_pc)]
    inspect_result = _run(inspect_command, cwd=ROOT, timeout=30, env=env)
    try:
        parsed = json.loads(inspect_result.get("stdout", ""))
    except json.JSONDecodeError:
        parsed = {"raw": inspect_result.get("stdout", "")}
    addresses = parsed.get("addresses", []) if isinstance(parsed, dict) else []
    source_ok = any(row.get("resolved") is True and row.get("source") for row in addresses)
    inspect_status = "PASS" if inspect_result.get("returncode") == 0 and source_ok else "FAIL"
    return {"status": inspect_status, "bundle": str(bundle), "inspect": parsed,
            "source_resolution": "PASS" if source_ok else "FAIL"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=pathlib.Path, default=ROOT / "build")
    parser.add_argument("--binary", type=pathlib.Path)
    parser.add_argument("--build-command", help="optional shell command used instead of cmake --build")
    parser.add_argument("--target", default=os.environ.get("FAULTDEBUG_GRPC_PROXY_TARGET", "fd_grpc_async_proxy"))
    parser.add_argument("--direct", action="store_true",
                        help="run the binary directly with --target-arg instead of the three-process proxy scenario")
    parser.add_argument("--target-arg", action="append", dest="target_args", default=None)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    build_dir = ns.build_dir.expanduser().resolve()
    binary = _find_binary(build_dir, ns.binary)
    report: dict[str, Any] = {
        "schema": 1, "fixture": "grpc_async_proxy", "started": time.time(),
        "toolchain": {name: _tool_version(name) for name in ("cmake", "protoc", "grpc_cpp_plugin")},
        "build_dir": str(build_dir), "target": ns.target,
        "checks": [], "limitations": [
            "The independent oracle validates FDAR integrity, crash metadata, event order, and module containment.",
            "This fixture proves application-owned RPC boundary functions; it does not claim a global cross-process order from function events alone.",
        ],
    }
    if binary is None:
        build = _build_proxy(build_dir, ns.target, ns.build_command)
        report["build"] = build
        binary = _find_binary(build_dir, ns.binary)
    else:
        report["build"] = {"status": "NOT RUN", "reason": "fixture binary already exists", "binary": str(binary)}
    if binary is None:
        # A missing CMake build tree/toolchain is an environmental NOT RUN;
        # a successful build that did not produce its declared target is a
        # failed integration gate.
        report["status"] = "NOT RUN" if report["build"].get("returncode") is None else "FAIL"
        report["reason"] = "asynchronous gRPC proxy fixture binary is unavailable"
        report["finished"] = time.time()
        ns.output.joinpath("report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": report["status"], "reason": report["reason"]}, sort_keys=True))
        return 0 if report["status"] == "NOT RUN" else 1

    binary = binary.resolve()
    report["binary"] = str(binary)
    artifact_dir = ns.output / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if ns.direct:
        args = ns.target_args if ns.target_args is not None else ["--mode=proxy", "--fault-after-response"]
        trace_id = "grpc-proxy-test"
        run_command = [sys.executable, "-m", "faultdebug.cli", "run", "--artifact-dir", str(artifact_dir),
                       "--trace-id", trace_id, "--correlation-id", "grpc-proxy-test", "--", str(binary), *args]
        run_result = _run(run_command, cwd=ROOT, timeout=ns.timeout)
    else:
        run_result = _orchestrated_run(binary, artifact_dir, ns.timeout, ns.output)
    report["run"] = run_result
    if not ns.direct:
        clean_artifact_dir = ns.output / "clean-artifacts"
        clean_artifact_dir.mkdir(parents=True, exist_ok=True)
        clean_run = _orchestrated_run(binary, clean_artifact_dir, ns.timeout,
                                      ns.output, fault_after_response=False,
                                      port_offset=4)
        clean_artifacts = sorted(clean_artifact_dir.glob("fault-*.fault"))
        report["clean_run"] = clean_run
        clean_ok = clean_run.get("status") == "PASS" and not clean_artifacts
        report["checks"].append(_status(
            "clean_shutdown_no_fault",
            "PASS" if clean_ok else "FAIL",
            "normal async proxy shutdown produced no fault artifact" if clean_ok
            else f"status={clean_run.get('status')}, artifacts={len(clean_artifacts)}"))
    artifacts = sorted(artifact_dir.glob("fault-*.fault"))
    if len(artifacts) != 1:
        report["checks"].append(_status("fault_artifact", "FAIL", f"expected one artifact, found {len(artifacts)}"))
        report["status"] = "FAIL"
        report["finished"] = time.time()
        ns.output.joinpath("report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": "FAIL", "reason": "fault artifact count mismatch"}, sort_keys=True))
        return 1
    artifact = artifacts[0]
    report["artifact"] = str(artifact)
    try:
        decoded = _read_fdar(artifact)
        report["independent"] = _independent_checks(decoded, binary)
        report["symbolization"] = _independent_symbolize(decoded, binary)
        report["boundary_trace"] = _boundary_trace(decoded, binary)
        report["product_evidence"] = _product_evidence(artifact, build_dir, ns.output, binary)
        report["checks"].extend(report["independent"])
        report["checks"].append(_status("independent_source", report["symbolization"]["status"], report["symbolization"].get("reason", "source location resolved")))
        report["checks"].append(_status("rpc_boundary_trace", report["boundary_trace"]["status"], report["boundary_trace"].get("reason", "boundary trace verified"), observed=report["boundary_trace"].get("observed", [])))
        report["checks"].append(_status("bundle_source_resolution", report["product_evidence"]["status"], report["product_evidence"].get("reason", "verified bundle source location resolved")))
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
        report["checks"].append(_status("fault_artifact", "FAIL", str(exc)))
    statuses = [item["status"] for item in report["checks"]]
    report["status"] = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report["finished"] = time.time()
    ns.output.joinpath("report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "artifact": str(artifact),
                      "checks": {s: statuses.count(s) for s in ("PASS", "FAIL", "NOT RUN")}}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
