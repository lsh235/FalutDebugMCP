#!/usr/bin/env python3
"""Build and evaluate pinned libuv v1.48.0 with FaultDebug.

The source tag is checked against its immutable commit. Original and
instrumented builds use separate directories, while all generated evidence is
written outside the repository. The expected SIGABRT and uv_* trace/source
checks are fixed independently of the observed report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))
UPSTREAM = "https://github.com/libuv/libuv.git"
TAG = "v1.48.0"
COMMIT = "e9f29cb984231524e3931aa0ae2c5dae1a32884e"
DRIVER = r'''#include <signal.h>
#include <uv.h>

static uv_loop_t loop;
static uv_timer_t timer;
static volatile int callback_seen;

static void on_timer(uv_timer_t *handle) {
  callback_seen = 1;
  uv_timer_stop(handle);
  uv_close((uv_handle_t *)handle, NULL);
  uv_stop(&loop);
}

int main(void) {
  if (uv_loop_init(&loop) != 0) return 10;
  if (uv_timer_init(&loop, &timer) != 0) return 11;
  if (uv_timer_start(&timer, on_timer, 0, 0) != 0) return 12;
  uv_run(&loop, UV_RUN_DEFAULT);
  if (!callback_seen) return 13;
  raise(SIGABRT);
  return 14;
}
'''


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_tree_sha256(root: Path) -> str:
    """Hash source/config files while excluding VCS, builds, tools and output."""
    excluded = {".git", ".venv", ".tools", "output", "test-results", "build"}
    digest = hashlib.sha256()
    for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if any(part in excluded for part in relative.parts) or any(part.startswith("build-") for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path | None = None,
        env: dict[str, str] | None = None, timeout: int = 600) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True,
                                capture_output=True, timeout=timeout, check=False)
        return {"command": command, "cwd": str(cwd) if cwd else None,
                "returncode": result.returncode,
                "duration_s": round(time.monotonic() - started, 3),
                "stdout": result.stdout[-5000:], "stderr": result.stderr[-5000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "cwd": str(cwd) if cwd else None,
                "returncode": None, "duration_s": round(time.monotonic() - started, 3),
                "error": str(exc)}


def version(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    result = run(command, timeout=15)
    value = result.get("stdout") or result.get("stderr") or ""
    return value.strip().splitlines()[0] if result.get("returncode") == 0 and value else None


def build_id(binary: Path) -> str | None:
    if shutil.which("readelf") is None:
        return None
    result = run(["readelf", "-n", str(binary)], timeout=15)
    match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", result.get("stdout", ""))
    return match.group(1).lower() if match else None


def write_report(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(path)}, sort_keys=True))


def _mcp_value(message: dict[str, Any]) -> Any:
    if "error" in message:
        raise RuntimeError(str(message["error"]))
    result = message.get("result", {})
    if not isinstance(result, dict):
        return result
    if result.get("isError"):
        raise RuntimeError("MCP tool returned isError")
    if "structuredContent" in result:
        return result["structuredContent"]
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            value = item.get("text", "")
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
    return result


def _mcp_stdio_check(root: Path, artifact: str, bundle: str,
                     function_id: str, address: int) -> dict[str, Any]:
    """Exercise the external evidence over the actual MCP stdio transport."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPOSITORY) + (os.pathsep + env.get("PYTHONPATH", ""))
    process = subprocess.Popen(
        [sys.executable, "-m", "faultdebug.cli", "mcp", "--root", str(root)],
        cwd=REPOSITORY, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "faultdebug-libuv-p2-03", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "open_fault", "arguments": {"name": artifact, "bundle": bundle}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "get_thread_trace", "arguments": {"name": artifact, "page": 0}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {
            "name": "resolve_addresses", "arguments": {"name": artifact,
            "addresses": [address], "bundle": bundle}}},
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "get_function_source", "arguments": {"name": artifact,
            "function_id": function_id, "bundle": bundle}}},
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {
            "name": "get_call_relations", "arguments": {"name": artifact,
            "function_id": function_id, "direction": "outbound", "bundle": bundle}}},
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {
            "name": "open_fault", "arguments": {"name": "../outside.fault"}}},
    ]
    responses: dict[int, dict[str, Any]] = {}
    noise: list[str] = []
    stderr: list[str] = []
    response_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                noise.append(line)
                continue
            if isinstance(value, dict):
                response_queue.put(value)
        response_queue.put(None)
    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stdout_thread.start()
    if process.stderr is not None:
        def drain() -> None:
            for line in process.stderr:
                stderr.append(line)
                if sum(map(len, stderr)) > 8192:
                    stderr[:] = ["".join(stderr)[-8192:]]
        stderr_thread = threading.Thread(target=drain, daemon=True)
        stderr_thread.start()
    else:
        stderr_thread = None
    try:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("MCP stdio pipes were not created")
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            if "id" not in request:
                continue
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    value = response_queue.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if value is None:
                    break
                if value.get("id") == request["id"]:
                    responses[int(request["id"])] = value
                    break
                noise.append(json.dumps(value, sort_keys=True))
        missing = sorted({1, 2, 3, 5, 6, 7, 8, 9} - responses.keys())
        if missing:
            return {"status": "FAIL", "reason": "MCP response missing", "missing": missing,
                    "stdout_noise_tail": "".join(noise)[-2000:],
                    "stderr_tail": "".join(stderr)[-2000:]}
        initialize = responses[1].get("result")
        listing = _mcp_value(responses[2])
        tool_names = {row.get("name") for row in listing.get("tools", [])} if isinstance(listing, dict) else set()
        required = {"open_fault", "get_thread_trace", "resolve_addresses",
                    "get_function_source", "get_call_relations"}
        opened = _mcp_value(responses[3])
        trace = _mcp_value(responses[5])
        resolved = _mcp_value(responses[6])
        source = _mcp_value(responses[7])
        relations = _mcp_value(responses[8])
        error_result = responses[9].get("result", {})
        error_text = ""
        if isinstance(error_result, dict):
            error_text = " ".join(str(row.get("text", "")) for row in error_result.get("content", [])
                                   if isinstance(row, dict))
        error_text += " " + str((responses[9].get("error") or {}).get("message", ""))
        checks = {
            "initialize": isinstance(initialize, dict),
            "required_tools_listed": required <= tool_names,
            "open_fault_success": isinstance(opened, dict) and isinstance(opened.get("header"), dict),
            "get_thread_trace_success": isinstance(trace, dict) and isinstance(trace.get("items"), list),
            "resolve_addresses_success": isinstance(resolved, dict) and bool(resolved.get("items")),
            "get_function_source_success": isinstance(source, dict) and source.get("resolved") is True
            and bool(source.get("source")),
            "get_call_relations_success": isinstance(relations, dict)
            and relations.get("evidence") == "static_index",
            "path_escape_error": bool(error_result.get("isError"))
            or "outside the allowlisted root" in error_text,
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL",
                "checks": checks, "tool_count": len(tool_names),
                "resolved_function": source.get("symbol") if isinstance(source, dict) else None,
                "thread_trace_items": len(trace.get("items", [])) if isinstance(trace, dict) else None,
                "address_rows": len(resolved.get("items", [])) if isinstance(resolved, dict) else None,
                "relation_evidence": relations.get("evidence") if isinstance(relations, dict) else None,
                "path_escape_error": error_text[:500],
                "responses_sha256": hashlib.sha256(json.dumps(responses, sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()}
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        return {"status": "FAIL", "reason": f"MCP stdio exchange failed: {exc}",
                "responses": sorted(responses)}
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, help="existing libuv checkout at the pinned commit")
    parser.add_argument("--runtime-dir", type=Path, default=REPOSITORY / "build")
    parser.add_argument("--work-dir", type=Path, default=Path("/tmp/faultdebug-libuv-v1.48.0"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", help="do not clone when --source is omitted")
    ns = parser.parse_args()
    output = ns.output.resolve()
    work = ns.work_dir.resolve()
    tools = {
        "python": sys.version.splitlines()[0],
        "platform": platform.platform(),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "git": version(["git", "--version"]),
        "cmake": version(["cmake", "--version"]),
        "ninja": version(["ninja", "--version"]),
        "clang": version([str(REPOSITORY / ".tools/bin/clang"), "--version"]),
        "readelf": version(["readelf", "--version"]),
    }
    result: dict[str, Any] = {
        "schema": 1,
        "status": "NOT RUN",
        "identity": {"project": "libuv", "tag": TAG, "commit": COMMIT,
                     "repository": UPSTREAM,
                     "faultdebug_commit": None,
                     "faultdebug_worktree_clean": None,
                     "faultdebug_dirty_paths": [],
                     "faultdebug_source_tree_sha256": None,
                     "runtime_library_sha256": None},
        "environment": tools,
        "scope": ["pinned libuv static library", "C timer callback and loop run",
                  "SIGABRT capture", "uv_* symbol and bundled source resolution",
                  "local MCP source and relation calls"],
        "checks": {},
        "commands": [],
        "limitations": ["This bounded evaluation does not establish production readiness or broad workload coverage."],
    }

    git_head = run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, timeout=15)
    result["identity"]["faultdebug_commit"] = git_head.get("stdout", "").strip() or None
    dirty = run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=REPOSITORY, timeout=15)
    dirty_paths = [line[3:] for line in dirty.get("stdout", "").splitlines() if len(line) > 3]
    result["identity"]["faultdebug_worktree_clean"] = not dirty_paths
    result["identity"]["faultdebug_dirty_paths"] = dirty_paths
    result["identity"]["faultdebug_source_tree_sha256"] = source_tree_sha256(REPOSITORY)
    runtime = ns.runtime_dir.resolve() / "libfaultdebug_runtime.so"
    if runtime.is_file():
        result["identity"]["runtime_library_sha256"] = sha256(runtime)
    missing = [name for name in ("git", "cmake", "ninja", "clang") if not tools[name]]
    missing.extend(name for name, ok in (
        ("runtime library", runtime.is_file()),
        ("FaultDebug Python package", (REPOSITORY / "faultdebug").is_dir()),
    ) if not ok)
    if missing:
        result["reason"] = "required input unavailable: " + ", ".join(missing)
        write_report(output, result)
        return 0

    try:
        import faultdebug  # noqa: F401
        import clang.cindex  # noqa: F401
        import elftools  # noqa: F401
    except Exception as exc:
        result["reason"] = f"Python evaluation dependency unavailable: {exc}"
        write_report(output, result)
        return 0

    source = ns.source.resolve() if ns.source else work / "source"
    created_source = False
    if ns.source is None and ns.offline and not source.is_dir():
        result["reason"] = "offline mode requested and pinned source checkout is unavailable"
        write_report(output, result)
        return 0
    if ns.source is None and not source.is_dir():
        work.mkdir(parents=True, exist_ok=True)
        clone = run(["git", "clone", "--quiet", "--no-checkout", UPSTREAM, str(source)], timeout=120)
        result["commands"].append(clone)
        if clone.get("returncode") != 0:
            result["reason"] = "could not fetch pinned libuv source"
            write_report(output, result)
            return 0
        created_source = True
    if not (source / "CMakeLists.txt").is_file():
        result["reason"] = f"libuv source directory is unavailable: {source}"
        write_report(output, result)
        return 0

    head = run(["git", "rev-parse", "HEAD"], cwd=source, timeout=15)
    observed_before_checkout = head.get("stdout", "").strip()
    if head.get("returncode") != 0 or observed_before_checkout != COMMIT:
        if not created_source:
            result["status"] = "FAIL"
            result["reason"] = ("caller-supplied libuv checkout is not at the pinned commit; "
                                 f"expected {COMMIT}, observed {observed_before_checkout or 'unavailable'}; "
                                 "the checkout was left unchanged")
            result["identity"]["observed_libuv_commit"] = observed_before_checkout or None
            write_report(output, result)
            return 1
        checkout = run(["git", "checkout", "--quiet", "--detach", COMMIT], cwd=source, timeout=30)
        result["commands"].append(checkout)
        head = run(["git", "rev-parse", "HEAD"], cwd=source, timeout=15)
    observed_commit = head.get("stdout", "").strip()
    result["identity"]["observed_libuv_commit"] = observed_commit or None
    if head.get("returncode") != 0 or observed_commit != COMMIT:
        result["status"] = "FAIL"
        result["reason"] = "libuv source could not be verified at the pinned commit"
        write_report(output, result)
        return 1

    status = run(["git", "status", "--porcelain"], cwd=source, timeout=15)
    if status.get("returncode") != 0 or status.get("stdout", "").strip():
        result["status"] = "FAIL"
        result["reason"] = "pinned libuv source checkout is dirty"
        result["checks"]["source_clean"] = {"status": "FAIL", "output": status.get("stdout")}
        write_report(output, result)
        return 1
    result["checks"]["source_clean"] = {"status": "PASS", "commit": COMMIT}

    work.mkdir(parents=True, exist_ok=True)
    evidence = work / ("evidence-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{os.getpid()}")
    artifacts = evidence / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    original_build = work / "build-original"
    instrumented_build = work / "build-instrumented"
    driver_dir = work / "driver"
    driver_dir.mkdir(parents=True, exist_ok=True)
    driver_src = driver_dir / "main.c"
    driver_src.write_text(DRIVER, encoding="utf-8")
    compiler = str(REPOSITORY / ".tools/bin/clang")
    wrapper = str(REPOSITORY / "scripts/faultdebug-cc")
    base_env = os.environ.copy()
    base_env["FAULTDEBUG_RUNTIME_DIR"] = str(runtime.parent)
    base_env["PYTHONPATH"] = str(REPOSITORY) + (os.pathsep + base_env.get("PYTHONPATH", ""))
    instrumented_env = dict(base_env, FAULTDEBUG_REAL_CC=compiler)
    original_configure = ["cmake", "-S", str(source), "-B", str(original_build),
                          "-G", "Ninja", f"-DCMAKE_C_COMPILER={compiler}",
                          "-DBUILD_TESTING=OFF", "-DLIBUV_BUILD_TESTS=OFF",
                          "-DLIBUV_BUILD_SHARED=OFF", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
    instrumented_configure = ["cmake", "-S", str(source), "-B", str(instrumented_build),
                              "-G", "Ninja", f"-DCMAKE_C_COMPILER={wrapper}",
                              ("-DCMAKE_C_FLAGS="
                               f"-ffile-prefix-map={instrumented_build}=/build/libuv "
                               f"-fdebug-prefix-map={instrumented_build}=/build/libuv"),
                              "-DBUILD_TESTING=OFF", "-DLIBUV_BUILD_TESTS=OFF",
                              "-DLIBUV_BUILD_SHARED=OFF", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"]
    for label, command, env in (
        ("configure_original", original_configure, base_env),
        ("build_original", ["cmake", "--build", str(original_build), "--target", "uv_a", "--parallel", "2"], base_env),
        ("configure_instrumented", instrumented_configure, instrumented_env),
        ("build_instrumented", ["cmake", "--build", str(instrumented_build), "--target", "uv_a", "--parallel", "2"], instrumented_env),
    ):
        row = run(command, cwd=source, env=env, timeout=900)
        result["commands"].append(row)
        result["checks"][label] = {"status": "PASS" if row.get("returncode") == 0 else "FAIL",
                                   "returncode": row.get("returncode"), "stderr": row.get("stderr", "")}
        if row.get("returncode") != 0:
            result["status"] = "FAIL"
            result["reason"] = f"{label} failed"
            write_report(output, result)
            return 1

    def find_library(build: Path) -> Path | None:
        return next((p for p in build.rglob("libuv.a") if p.is_file()), None)

    original_lib = find_library(original_build)
    instrumented_lib = find_library(instrumented_build)
    if not original_lib or not instrumented_lib:
        result["status"] = "FAIL"
        result["reason"] = "expected libuv static archive is missing"
        write_report(output, result)
        return 1
    result["checks"]["library_archives"] = {
        "status": "PASS" if sha256(original_lib) != sha256(instrumented_lib) else "FAIL",
        "original_sha256": sha256(original_lib),
        "instrumented_sha256": sha256(instrumented_lib),
        "distinct": sha256(original_lib) != sha256(instrumented_lib),
    }
    if result["checks"]["library_archives"]["status"] != "PASS":
        result["status"] = "FAIL"
        result["reason"] = "original and instrumented libuv archives are identical"
        write_report(output, result)
        return 1
    common_link = ["-g", "-O0", "-fno-lto",
                   f"-ffile-prefix-map={driver_dir}=/build/driver",
                   f"-fdebug-prefix-map={driver_dir}=/build/driver",
                   "-I", str(source / "include"),
                   str(driver_src), "-pthread", "-ldl", "-lrt", "-Wl,--build-id=sha1"]
    original_binary = driver_dir / "libuv-original"
    instrumented_binary = driver_dir / "libuv-instrumented"
    for label, command, env in (
        ("link_original_driver", [compiler, *common_link, str(original_lib), "-o", str(original_binary)], base_env),
        ("link_instrumented_driver", [compiler, *common_link, str(instrumented_lib),
                                       "-L", str(runtime.parent), "-lfaultdebug_runtime",
                                       "-Wl,-rpath," + str(runtime.parent), "-o", str(instrumented_binary)], base_env),
    ):
        row = run(command, cwd=source, env=env, timeout=180)
        result["commands"].append(row)
        result["checks"][label] = {"status": "PASS" if row.get("returncode") == 0 else "FAIL",
                                   "returncode": row.get("returncode"), "stderr": row.get("stderr", "")}
        if row.get("returncode") != 0:
            result["status"] = "FAIL"
            result["reason"] = f"{label} failed"
            write_report(output, result)
            return 1
    original_id, instrumented_id = build_id(original_binary), build_id(instrumented_binary)
    result["checks"]["build_ids"] = {"status": "PASS" if original_id and instrumented_id and original_id != instrumented_id else "FAIL",
                                      "original": original_id, "instrumented": instrumented_id,
                                      "distinct": bool(original_id and instrumented_id and original_id != instrumented_id)}
    if result["checks"]["build_ids"]["status"] != "PASS":
        result["status"] = "FAIL"
        result["reason"] = "driver Build IDs missing or not distinct"
        write_report(output, result)
        return 1

    normal = run([str(original_binary)], cwd=source, env=base_env, timeout=30)
    result["commands"].append(normal)
    result["checks"]["original_runtime"] = {"status": "PASS" if normal.get("returncode") == -signal.SIGABRT else "FAIL",
                                             "expected_signal": signal.SIGABRT,
                                             "returncode": normal.get("returncode")}
    capture = run([sys.executable, "-m", "faultdebug.cli", "run", "--artifact-dir",
                   str(artifacts), "--", str(instrumented_binary)], cwd=REPOSITORY,
                  env=base_env, timeout=60)
    result["commands"].append(capture)
    summary = None
    for line in reversed(capture.get("stdout", "").splitlines()):
        try:
            candidate = json.loads(line)
            if isinstance(candidate, dict):
                summary = candidate
                break
        except json.JSONDecodeError:
            pass
    artifact_path = Path(summary["artifact"]) if summary and summary.get("artifact") else None
    if artifact_path and not artifact_path.is_absolute():
        artifact_path = (REPOSITORY / artifact_path).resolve()
    if not artifact_path or not artifact_path.is_file():
        result["status"] = "FAIL"
        result["reason"] = "instrumented external process produced no readable artifact"
        result["checks"]["fault_capture"] = {"status": "FAIL", "stdout": capture.get("stdout"),
                                              "stderr": capture.get("stderr")}
        write_report(output, result)
        return 1

    from faultdebug.artifact import read_artifact
    report = read_artifact(artifact_path)
    events = [event for thread in report.get("threads", []) for event in thread.get("events", [])]
    crashes = report.get("crashes", [])
    crash_signal = crashes[0].get("signal") if crashes else None
    result["checks"]["fault_capture"] = {
        "status": "PASS" if crash_signal == signal.SIGABRT and summary and
                  (summary.get("target") or {}).get("signal") == signal.SIGABRT else "FAIL",
        "expected_signal": signal.SIGABRT,
        "target_signal": (summary.get("target") or {}).get("signal") if summary else None,
        "artifact_signal": crash_signal,
        "artifact_sha256": sha256(artifact_path),
        "event_count": len(events),
    }
    result["evidence"] = {"artifact": str(artifact_path), "artifact_sha256": sha256(artifact_path),
                          "original_binary": str(original_binary),
                          "instrumented_binary": str(instrumented_binary),
                          "compile_database": str(instrumented_build / "compile_commands.json")}
    if result["checks"]["fault_capture"]["status"] != "PASS":
        result["status"] = "FAIL"
        result["reason"] = "the instrumented target did not produce the expected SIGABRT evidence"
        write_report(output, result)
        return 1

    index_path = evidence / "index.json"
    from faultdebug.index import build_index
    from faultdebug.bundle import create_bundle
    from faultdebug.inspect import resolve_addresses
    build_index(instrumented_build / "compile_commands.json", index_path)
    bundle_path = evidence / "bundle"
    source_files = [path for path in source.rglob("*") if path.is_file() and ".git" not in path.relative_to(source).parts]
    bundle = create_bundle(source, bundle_path, files=source_files, index=index_path,
                           binaries=[instrumented_binary])
    addresses = list(dict.fromkeys(int(e["function"]) for e in events if int(e.get("function", 0))))
    resolutions = resolve_addresses(report, addresses[:500], bundle)
    uv_resolutions = [row for row in resolutions if row.get("resolved") and
                      str(row.get("symbol", "")).startswith("uv_")]
    index_rows = {row.get("id"): row for row in bundle.index_rows()}
    uv_with_source = []
    for row in uv_resolutions:
        source_row = index_rows.get(row.get("function_id"), {})
        source_file = str(source_row.get("file", ""))
        if source_file.endswith(".c") and "/src/" in ("/" + source_file.replace("\\", "/")):
            uv_with_source.append({"symbol": row["symbol"], "file": source_file,
                                   "function_id": row.get("function_id")})
    result["checks"]["external_symbol_source"] = {
        "status": "PASS" if uv_with_source else "FAIL",
        "resolved_uv_functions": uv_with_source[:20],
        "resolved_address_count": len(resolutions),
        "bundle_verified": True,
        "bundle_file_count": len(bundle.files),
    }
    root = evidence
    artifact_name = artifact_path.relative_to(root).as_posix()
    bundle_name = bundle_path.relative_to(root).as_posix()
    target = uv_with_source[0] if uv_with_source else None
    if target and addresses:
        mcp = _mcp_stdio_check(root, artifact_name, bundle_name,
                               target["function_id"], addresses[0])
    else:
        mcp = {"status": "FAIL", "reason": "no resolved libuv source target or trace address"}
    mcp_path = evidence / "mcp-result.json"
    mcp_path.write_text(json.dumps(mcp, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["evidence"]["mcp_result"] = str(mcp_path)
    result["checks"]["mcp_stdio_success_and_error"] = {
        "status": mcp.get("status", "FAIL"),
        "function": target["symbol"] if target else None,
        "checks": mcp.get("checks", {}),
        "reason": mcp.get("reason"),
        "response_sha256": mcp.get("responses_sha256"),
    }

    statuses = [check["status"] for check in result["checks"].values()]
    result["status"] = "FAIL" if "FAIL" in statuses else "PASS"
    result["evidence"]["report_written_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_report(output, result)
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
