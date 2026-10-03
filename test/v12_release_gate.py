#!/usr/bin/env python3
"""Required v1.2 CI/release gates, including a checkout-free wheel consumer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import venv
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from faultdebug import __version__ as PACKAGE_VERSION  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_V10 = ("install_consumer", "capability_cli", "mcp_capabilities_store",
                "store_compatibility", "native_ctest", "package_metadata")


def _result(name: str, status: str, summary: str, **details: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "summary": summary, **details}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None,
         timeout: int = 900) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                   text=True, errors="replace", timeout=timeout, check=False)
        return {"command": command, "cwd": str(cwd), "returncode": completed.returncode,
                "duration_s": round(time.monotonic() - started, 3),
                "stdout_tail": completed.stdout[-6000:], "stderr_tail": completed.stderr[-6000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "cwd": str(cwd), "returncode": None,
                "duration_s": round(time.monotonic() - started, 3), "error": str(exc)}


def _v10_compatibility(report_path: Path, profile: str) -> dict[str, Any]:
    if not report_path.is_file():
        return _result("source_compatibility", "FAIL", "v1.0 compatibility report is missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = {row.get("name"): row for row in report.get("checks", []) if isinstance(row, dict)}
    missing = [name for name in REQUIRED_V10 if name not in rows]
    failed = [name for name in REQUIRED_V10
              if name in rows and rows[name].get("status") != "PASS"]
    if missing or failed:
        return _result("source_compatibility", "FAIL", "required v1.0 compatibility row failed or is absent",
                       missing=missing, failed=failed, report_status=report.get("status"))
    v09 = rows.get("v09_regression", {})
    nested = v09.get("report", {})
    v09_checks = {row.get("name"): row for row in nested.get("checks", []) if isinstance(row, dict)}
    mcp = v09_checks.get("mcp_stdio_protocol", {})
    if mcp.get("status") != "PASS":
        return _result("source_compatibility", "FAIL", "v0.9 required MCP stdio row did not pass",
                       mcp=mcp, report_status=report.get("status"))
    grpc_rows = {name: row.get("status") for name, row in v09_checks.items()
                 if str(name).startswith("grpc_")}
    grpc_failed = [name for name, status in grpc_rows.items() if status == "FAIL"]
    if grpc_failed or (profile == "grpc" and (report.get("status") != "PASS"
                                               or any(status != "PASS" for status in grpc_rows.values()))):
        return _result("source_compatibility", "FAIL", "gRPC regression profile did not pass",
                       grpc_rows=grpc_rows, failed=grpc_failed, report_status=report.get("status"))
    return _result("source_compatibility", "PASS", "all required source compatibility rows passed",
                   v10_rows={name: rows[name]["status"] for name in REQUIRED_V10},
                   v09_status=v09.get("status"), mcp_stdio=mcp.get("status"),
                   grpc_rows=grpc_rows, optional_not_run=[name for name, status in grpc_rows.items()
                                                          if status == "NOT RUN"])


def _mcp_exchange(executable: Path, root: Path, env: dict[str, str]) -> dict[str, Any]:
    process = subprocess.Popen([str(executable), "mcp", "--root", str(root)], cwd=root, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", bufsize=1)
    responses: queue.Queue[dict[str, Any] | None] = queue.Queue()
    stderr: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                responses.put(value)
        responses.put(None)

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr.append(line)
            if sum(map(len, stderr)) > 8192:
                stderr[:] = ["".join(stderr)[-8192:]]

    threads = [threading.Thread(target=read_stdout, daemon=True),
               threading.Thread(target=read_stderr, daemon=True)]
    for thread in threads:
        thread.start()
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "faultdebug-v12-wheel", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "open_fault", "arguments": {"name": "wheel-success.fault"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "open_fault", "arguments": {"name": "../outside.fault"}}},
    ]
    found: dict[int, dict[str, Any]] = {}
    try:
        assert process.stdin is not None
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            if "id" not in request:
                continue
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    response = responses.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if response is None:
                    break
                if response.get("id") == request["id"]:
                    found[int(request["id"])] = response
                    break
        missing = sorted({1, 2, 3, 4} - found.keys())
        if missing:
            return {"status": "FAIL", "missing_responses": missing,
                    "stderr_tail": "".join(stderr)[-2000:]}
        tools_value = found[2].get("result", {})
        tools = {row.get("name") for row in tools_value.get("tools", [])} if isinstance(tools_value, dict) else set()
        success = found[3].get("result", {})
        success_content = success.get("structuredContent") if isinstance(success, dict) else None
        if success_content is None and isinstance(success, dict):
            for row in success.get("content", []):
                if isinstance(row, dict) and row.get("type") == "text":
                    try:
                        success_content = json.loads(row.get("text", ""))
                    except json.JSONDecodeError:
                        pass
                    break
        error = found[4].get("result", {})
        error_text = " ".join(str(row.get("text", "")) for row in error.get("content", [])
                               if isinstance(row, dict)) if isinstance(error, dict) else ""
        checks = {"initialize": isinstance(found[1].get("result"), dict),
                  "open_fault_success": isinstance(success_content, dict)
                  and isinstance(success_content.get("header"), dict),
                  "path_error": ((bool(error.get("isError")) if isinstance(error, dict) else False)
                                 or "outside the allowlisted root" in error_text),
                  "required_tools_listed": {"open_fault", "get_thread_trace", "resolve_addresses",
                    "get_function_source", "get_call_relations"} <= tools}
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
                "tool_count": len(tools), "path_error": error_text[:400]}
    except (OSError, AssertionError, TypeError, ValueError) as exc:
        return {"status": "FAIL", "reason": str(exc), "stderr_tail": "".join(stderr)[-2000:]}
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=1)


def _wheel_consumer(ns: argparse.Namespace, work: Path, build_dir: Path) -> dict[str, Any]:
    dist = work / "dist"
    built = _run([str(ns.python), "-m", "build", "--sdist", "--wheel", "--outdir", str(dist)], timeout=600)
    build_fallback: dict[str, Any] | None = None
    build_output = " ".join(built.get("stdout_tail", "").split())
    if (built.get("returncode") != 0 and "ensurepip is not available" in build_output):
        # Some distro Python installs omit python3-venv. Keep the hermetic
        # build as the primary path, but allow the caller's already provisioned
        # build backend to package the wheel on those hosts.
        build_fallback = built
        built = _run([str(ns.python), "-m", "build", "--no-isolation", "--sdist", "--wheel",
                      "--outdir", str(dist)], timeout=600)
    wheels = sorted(dist.glob("*.whl")) if dist.is_dir() else []
    sdists = sorted(dist.glob("*.tar.gz")) if dist.is_dir() else []
    if built["returncode"] != 0 or len(wheels) != 1 or len(sdists) != 1:
        return _result("package_build", "FAIL", "wheel/sdist build did not emit one of each",
                       build=built, build_isolation_fallback=build_fallback,
                       wheels=[str(path) for path in wheels], sdists=[str(path) for path in sdists])
    consumer = work / "installed-consumer"
    shutil.rmtree(consumer, ignore_errors=True)
    consumer.mkdir()
    envdir = work / "wheel-env"
    shutil.rmtree(envdir, ignore_errors=True)
    consumer_mode = "venv"
    venv_error: str | None = None
    ensurepip_entry = Path(sysconfig.get_path("stdlib")) / "ensurepip" / "__main__.py"
    if ensurepip_entry.is_file():
        try:
            venv.create(envdir, with_pip=True, system_site_packages=True)
        except (OSError, subprocess.SubprocessError) as exc:
            venv_error = str(exc)
    else:
        venv_error = f"ensurepip entry point is missing: {ensurepip_entry}"
    if venv_error is None:
        python = envdir / "bin" / "python"
        install_command = [str(python), "-m", "pip", "install", "--disable-pip-version-check",
                           "--no-deps", "--force-reinstall", str(wheels[0])]
        wheel_site = envdir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    else:
        # Use an isolated install prefix when ensurepip is absent. The CLI
        # entry-point still runs from the installed prefix, and PYTHONPATH
        # keeps its wheel ahead of any source/editable package on the host.
        consumer_mode = "prefix"
        venv_error = str(venv_error)
        shutil.rmtree(envdir, ignore_errors=True)
        envdir = work / "wheel-prefix"
        shutil.rmtree(envdir, ignore_errors=True)
        pip_executable = (shutil.which(f"pip{sys.version_info.major}.{sys.version_info.minor}")
                          or shutil.which(f"pip{sys.version_info.major}")
                          or shutil.which("pip"))
        if pip_executable is None:
            return _result("installed_wheel_consumer", "FAIL",
                           "host lacks both ensurepip and a pip executable for prefix installation",
                           venv_failure=venv_error)
        python = ns.python.absolute()
        install_command = [pip_executable, "install", "--disable-pip-version-check",
                           "--no-deps", "--force-reinstall", "--prefix", str(envdir), str(wheels[0])]
        wheel_site = envdir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    install = _run(install_command, cwd=consumer, timeout=300)
    installed_packages = sorted(envdir.rglob("faultdebug/__init__.py"))
    if installed_packages:
        wheel_site = installed_packages[0].parent.parent
    installed_scripts = sorted(path for path in envdir.rglob("faultdebug")
                               if path.is_file() and path.parent.name == "bin")
    executable = installed_scripts[0] if installed_scripts else envdir / "bin" / "faultdebug"
    env = dict(os.environ)
    dependency_paths = [path for path in sys.path
                        if path and Path(path).is_dir()
                        and ("site-packages" in path or "dist-packages" in path)
                        and Path(path).resolve() != ROOT.resolve()]
    env["PYTHONPATH"] = os.pathsep.join([str(wheel_site), *dependency_paths])
    env["PATH"] = str(executable.parent) + os.pathsep + env.get("PATH", "")
    env["FAULTDEBUG_RUNTIME_DIR"] = str(build_dir)
    env["FAULTDEBUG_REAL_CC"] = shutil.which("clang-18") or shutil.which("clang") or "clang"
    env["FAULTDEBUG_REAL_CXX"] = shutil.which("clang++-18") or shutil.which("clang++") or "clang++"
    import_result = _run([str(python), "-c", "import faultdebug; print(faultdebug.__file__); print(faultdebug.__version__)"],
                         cwd=consumer, env=env, timeout=30)
    package_path = Path(import_result.get("stdout_tail", "").splitlines()[0]).resolve() if import_result.get("stdout_tail") else None
    under_venv = package_path is not None and envdir.resolve() in package_path.parents
    summary = _run([str(executable), "capabilities"], cwd=consumer, env=env, timeout=30) if executable.is_file() else {"returncode": None}
    doctor = _run([str(executable), "doctor", "--json"], cwd=consumer, env=env, timeout=90) if executable.is_file() else {"returncode": None}
    doctor_payload: dict[str, Any] = {}
    try:
        doctor_payload = json.loads(doctor.get("stdout_tail", ""))
    except json.JSONDecodeError:
        pass
    target = build_dir / "test" / "fd_c_chain"
    artifact_dir = consumer / "artifacts"
    normal = (_run([str(executable), "run", "--artifact-dir", str(artifact_dir), "--", str(target), "16"],
                   cwd=consumer, env=env, timeout=60) if executable.is_file() and target.is_file()
              else {"returncode": None})
    clean_files = list(artifact_dir.glob("*.fault")) if artifact_dir.is_dir() else []
    trace = (_run([str(executable), "run", "--collect-success", "--artifact-dir", str(artifact_dir),
                   "--", str(target), "16"], cwd=consumer, env=env, timeout=60)
             if executable.is_file() and target.is_file() else {"returncode": None})
    summaries: list[dict[str, Any]] = []
    for line in trace.get("stdout_tail", "").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "target" in value and "collector" in value:
            summaries.append(value)
    faults = sorted(artifact_dir.glob("*.fault")) if artifact_dir.is_dir() else []
    if len(faults) != 1:
        return _result("installed_wheel_consumer", "FAIL", "normal/opt-in trace behavior did not produce exactly one artifact",
                       install=install, import_result=import_result, package_path=str(package_path), normal=normal,
                       normal_artifacts=len(clean_files), trace=trace, artifacts=[str(path) for path in faults],
                       capabilities=summary, doctor=doctor)
    shutil.copy2(faults[0], consumer / "wheel-success.fault")
    mcp = _mcp_exchange(executable, consumer, env)
    statuses = {"install": install.get("returncode") == 0, "installed_path": under_venv,
                "capabilities": summary.get("returncode") == 0,
                "doctor": doctor.get("returncode") == 0 and doctor_payload.get("status") == "PASS",
                "default_clean_run": normal.get("returncode") == 0 and len(clean_files) == 0,
                "opt_in_trace_run": trace.get("returncode") == 0 and len(summaries) == 1
                and summaries[0].get("trace", {}).get("complete") is True,
                "mcp_stdio": mcp.get("status") == "PASS"}
    status = "PASS" if all(statuses.values()) else "FAIL"
    return _result("installed_wheel_consumer", status,
                   "wheel CLI, doctor, normal/opt-in tracing, and MCP stdio were exercised outside the checkout",
                   checks=statuses, package_path=str(package_path), wheel=str(wheels[0]),
                   wheel_sha256=_sha256(wheels[0]), sdist=str(sdists[0]), sdist_sha256=_sha256(sdists[0]),
                   normal=normal, trace=trace, mcp=mcp, capabilities=summary,
                   doctor=doctor, consumer_mode=consumer_mode,
                   build_isolation_fallback=build_fallback,
                   venv_failure=(venv_error if consumer_mode == "prefix" else None),
                   consumer_prefix=str(envdir))


def validate_v10_status(report: dict[str, Any], profile: str) -> tuple[bool, list[str], list[str]]:
    rows = {row.get("name"): row for row in report.get("checks", []) if isinstance(row, dict)}
    missing = [name for name in REQUIRED_V10 if name not in rows]
    failed = [name for name in REQUIRED_V10
              if name in rows and rows[name].get("status") != "PASS"]
    return not missing and not failed, missing, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("core", "grpc"), required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--install-prefix", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--cc", default=os.environ.get("CC", "clang-18"))
    parser.add_argument("--cxx", default=os.environ.get("CXX", "clang++-18"))
    ns = parser.parse_args()
    build_dir = ns.build_dir.resolve()
    install_prefix = ns.install_prefix.resolve()
    work = ns.work_dir.resolve()
    output = ns.output.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update({"CC": ns.cc, "CXX": ns.cxx, "FAULTDEBUG_REAL_CC": ns.cc,
                "FAULTDEBUG_REAL_CXX": ns.cxx, "FAULTDEBUG_RUNTIME_DIR": str(build_dir)})
    grpc_enabled = ns.profile == "grpc"
    configure = _run(["cmake", "-S", str(ROOT), "-B", str(build_dir), "-G", "Ninja",
                      f"-DCMAKE_C_COMPILER={ns.cc}", f"-DCMAKE_CXX_COMPILER={ns.cxx}",
                      f"-DFAULTDEBUG_PYTHON_EXECUTABLE={ns.python.absolute()}",
                      "-DFAULTDEBUG_BUILD_TESTS=ON", "-DFAULTDEBUG_ENABLE_PROVENANCE=ON",
                      f"-DFAULTDEBUG_BUILD_GRPC_PROXY={'ON' if grpc_enabled else 'OFF'}"], env=env)
    checks: list[dict[str, Any]] = [_result("configure", "PASS" if configure.get("returncode") == 0 else "FAIL",
                                             "configured provenance-enabled release profile", run=configure)]
    build = _run(["cmake", "--build", str(build_dir), "--parallel", "2"], env=env) if configure.get("returncode") == 0 else {"returncode": None, "reason": "configure failed"}
    checks.append(_result("build", "PASS" if build.get("returncode") == 0 else "FAIL",
                          "native release profile built", run=build))
    if build.get("returncode") == 0:
        source_manifest = build_dir / "faultdebug-source-snapshot" / "source-manifest.json"
        target_manifest = build_dir / "test" / "fd_c_chain.faultdebug.manifest.json"
        manifests_valid = False
        manifest_reason = "source/target provenance manifests are missing"
        try:
            source_data = json.loads(source_manifest.read_text(encoding="utf-8"))
            target_data = json.loads(target_manifest.read_text(encoding="utf-8"))
            manifests_valid = bool(source_data.get("files")) and bool(target_data.get("build_id"))
            manifest_reason = "source and fixture provenance manifests decoded"
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            manifest_reason = str(exc)
        checks.append(_result("build_provenance", "PASS" if manifests_valid else "FAIL",
                              manifest_reason, source_manifest=str(source_manifest),
                              target_manifest=str(target_manifest)))
        junit = work / "ctest.xml"
        ctest = _run(["ctest", "--test-dir", str(build_dir), "--output-on-failure",
                      "--output-junit", str(junit)], env=env, timeout=900)
        checks.append(_result("named_ctest", "PASS" if ctest.get("returncode") == 0 else "FAIL",
                              "all registered named tests completed", run=ctest,
                              junit=str(junit) if junit.is_file() else None))
        v10_dir = work / "v10"
        v10_command = [str(ns.python.absolute()), str(ROOT / "test" / "v10_validation.py"),
                       "--build-dir", str(build_dir), "--install-prefix", str(install_prefix),
                       "--ctest-dir", str(build_dir), "--python", str(ns.python.absolute()),
                       "--output", str(v10_dir)]
        if grpc_enabled:
            v10_command.extend(["--grpc-build-dir", str(build_dir)])
        v10_run = _run(v10_command, env=env, timeout=1800)
        v10_report = v10_dir / "report.json"
        v10_result: dict[str, Any] = {}
        if v10_report.is_file():
            v10_result = json.loads(v10_report.read_text(encoding="utf-8"))
        compatibility = _v10_compatibility(v10_report, ns.profile)
        compatibility.update({"report": str(v10_report), "run": v10_run})
        checks.append(compatibility)
    else:
        checks.extend([_result("build_provenance", "NOT RUN", "build failed"),
                       _result("named_ctest", "NOT RUN", "build failed"),
                       _result("source_compatibility", "NOT RUN", "build failed")])
    if build.get("returncode") == 0:
        wheel = _wheel_consumer(ns, work, build_dir)
        checks.append(wheel)
    else:
        checks.append(_result("installed_wheel_consumer", "NOT RUN", "native build failed"))
    statuses = [row["status"] for row in checks]
    status = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "schema_name": "faultdebug.v1_2_release_gate", "version": PACKAGE_VERSION,
              "profile": ns.profile, "status": status,
              "configuration": {"source": str(ROOT), "build_dir": str(build_dir),
                                "install_prefix": str(install_prefix), "work_dir": str(work),
                                "python": str(ns.python.absolute()), "cc": ns.cc, "cxx": ns.cxx,
                                "provenance_enabled": True, "grpc_enabled": grpc_enabled},
              "checks": checks,
              "acceptance_note": "This is a v1.2.0 release candidate; independent P4 acceptance remains pending."}
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "report": str(output)}, sort_keys=True))
    return {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[status]


if __name__ == "__main__":
    raise SystemExit(main())
