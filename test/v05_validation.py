#!/usr/bin/env python3
"""Independent v0.5 storage, privacy, build-profile, and regression gate.

The v0.5 spool API is intentionally optional while its public contract is
being finalized.  The gate reports missing implementations as ``NOT RUN``;
it never turns a missing feature into a passing quota or rotation claim.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(name: str, status: str, reason: str, **extra: Any) -> dict[str, Any]:
    value = {"name": name, "status": status, "reason": reason}
    value.update(extra)
    return value


def _atomic_artifact_check() -> dict[str, Any]:
    """Verify the existing FDAR writer never exposes a partial/checksum-bad file."""
    try:
        from faultdebug.artifact import read_artifact, write_artifact
    except ImportError as exc:
        return check("atomic_artifact_write", "NOT RUN", f"artifact module unavailable: {exc}")
    with tempfile.TemporaryDirectory(prefix="faultdebug-v05-artifact-") as raw:
        root = pathlib.Path(raw)
        paths = [write_artifact({"header": {"status": 1}, "serial": i}, root, 100 + i)
                 for i in range(3)]
        if len({path.name for path in paths}) != 3:
            return check("atomic_artifact_write", "FAIL", "artifact names were not unique")
        for path in paths:
            try:
                payload = read_artifact(path)
            except Exception as exc:
                return check("atomic_artifact_write", "FAIL", f"written artifact was unreadable: {exc}")
            if payload.get("header", {}).get("status") != 1:
                return check("atomic_artifact_write", "FAIL", "artifact payload changed")
            raw_bytes = path.read_bytes()
            if hashlib.sha256(raw_bytes[52:]).digest() != raw_bytes[20:52]:
                return check("atomic_artifact_write", "FAIL", "artifact checksum mismatch")
    return check("atomic_artifact_write", "PASS", "FDAR files are complete and checksum-valid after write")


def _spool_contract() -> dict[str, Any]:
    """Discover the v0.5 spool module without assuming an unapproved API."""
    candidates = ("faultdebug.spool", "faultdebug.spool_store", "faultdebug.storage")
    module = next((name for name in candidates if importlib.util.find_spec(name)), None)
    if module is None:
        return check("spool_quota_rotation", "NOT RUN", "v0.5 spool module is not present")
    loaded = importlib.import_module(module)
    api = {name for name in ("Spool", "ArtifactSpool", "write", "append", "rotate") if hasattr(loaded, name)}
    if not api:
        return check("spool_quota_rotation", "NOT RUN", f"{module} has no recognized public spool API")
    if not hasattr(loaded, "ArtifactSpool"):
        return check("spool_quota_rotation", "NOT RUN", f"{module} has no supported ArtifactSpool adapter", api=sorted(api))
    try:
        from faultdebug.artifact import read_artifact, write_artifact
        store_type = loaded.ArtifactSpool
        with tempfile.TemporaryDirectory(prefix="faultdebug-v05-spool-") as raw:
            root = pathlib.Path(raw)
            source = root / "source"
            spool = root / "spool"
            source.mkdir()
            stale = spool / ".faultdebug-crashed.tmp"
            spool.mkdir()
            stale.write_bytes(b"partial")
            artifacts = [write_artifact({"header": {"status": 0},
                                         "context": {"trace_id": f"trace-{i}", "correlation_id": f"corr-{i}"},
                                         "threads": [], "modules": [], "crashes": []}, source, 100 + i)
                         for i in range(3)]
            store = store_type(spool, max_bytes=10000, max_files=2,
                               redact_context_ids=("trace-1",))
            if stale.exists():
                return check("spool_quota_rotation", "FAIL", "abandoned temporary file was not recovered")
            for artifact in artifacts:
                store.ingest(artifact)
            stats = store.stats()
            retained = store.list_files()
            if stats["files"] != 2 or len(retained) != 2 or stats["bytes"] > stats["max_bytes"]:
                return check("spool_quota_rotation", "FAIL", "file/byte quota was not enforced", stats=stats)
            redacted = [read_artifact(path) for path in retained if "fault-101" in path.name]
            if not redacted or redacted[0].get("context", {}).get("trace_id") != "[REDACTED]":
                return check("spool_quota_rotation", "FAIL", "configured context ID was not redacted")
            if any(path.name.startswith(".faultdebug-") for path in spool.iterdir()):
                return check("spool_quota_rotation", "FAIL", "temporary file remained after atomic ingest")
            oversized = write_artifact({"header": {}, "large": "x" * 1000}, source, 999)
            try:
                store_type(root / "tiny", max_bytes=100, max_files=2).ingest(oversized)
            except Exception:
                pass
            else:
                return check("spool_quota_rotation", "FAIL", "oversized artifact bypassed max_bytes")
    except Exception as exc:
        return check("spool_quota_rotation", "FAIL", f"spool contract failed: {exc}", module=module)
    return check("spool_quota_rotation", "PASS", "temporary recovery, atomic ingest, file/byte quotas, rotation, and exact-ID redaction passed", module=module)


def _redaction_check() -> dict[str, Any]:
    """Ensure sensitive RPC values cannot become observed evidence."""
    try:
        from faultdebug.rpc import RPCDecodeError, rpc_trace
    except ImportError as exc:
        return check("redaction_behavior", "NOT RUN", f"RPC decoder unavailable: {exc}")
    sensitive = [
        {"method": "/private.Service/Call"},
        {"metadata": {"authorization": "Bearer secret-token"}},
        {"payload": "private request body"},
        {"credentials": "secret"},
    ]
    rejected: list[str] = []
    for fields in sensitive:
        event = {"rpc_id": 1, "phase": "begin", "monotonic_ns": 1, **fields}
        try:
            rpc_trace({"header": {"abi_version": 1}, "rpc_events": [event]})
        except RPCDecodeError:
            rejected.append(next(iter(fields)))
        else:
            return check("redaction_behavior", "FAIL", "sensitive RPC field became observed evidence", field=next(iter(fields)))
    return check("redaction_behavior", "PASS", "method, metadata, payload, and credentials are rejected from RPC evidence", rejected=rejected)


def _spool_cli_discovery() -> dict[str, Any]:
    try:
        from faultdebug.artifact import write_artifact
    except ImportError as exc:
        return check("spool_cli_discovery", "NOT RUN", f"artifact module unavailable: {exc}")
    with tempfile.TemporaryDirectory(prefix="faultdebug-v05-cli-") as raw:
        root = pathlib.Path(raw)
        source = root / "source"
        spool = root / "spool"
        source.mkdir()
        artifact = write_artifact({"header": {"status": 0}, "threads": [], "modules": [], "crashes": []}, source, 42)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        ingest = subprocess.run([sys.executable, "-m", "faultdebug.cli", "spool", "--root", str(spool), str(artifact)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        if ingest.returncode != 0:
            return check("spool_cli_discovery", "FAIL", "faultdebug spool CLI failed", stderr=ingest.stderr[-2000:])
        try:
            ingest_report = json.loads(ingest.stdout)
        except json.JSONDecodeError as exc:
            return check("spool_cli_discovery", "FAIL", f"spool CLI returned invalid JSON: {exc}")
        discover = subprocess.run([sys.executable, "-m", "faultdebug.cli", "artifact-discover", str(spool)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        if discover.returncode != 0:
            return check("spool_cli_discovery", "FAIL", "artifact-discover CLI failed", stderr=discover.stderr[-2000:])
        listing = json.loads(discover.stdout)
        if listing.get("valid") != 1 or listing.get("invalid") != 0:
            return check("spool_cli_discovery", "FAIL", "discovery did not report one valid artifact", discovery=listing)
        return check("spool_cli_discovery", "PASS", "spool ingest and artifact discovery CLI passed", ingest=ingest_report, discovery=listing)


def _selective_profile(build_dir: pathlib.Path | None) -> dict[str, Any]:
    if build_dir is None:
        return check("selective_instrumentation", "NOT RUN", "--build-dir was not supplied")
    compdb = build_dir / "compile_commands.json"
    if not compdb.is_file():
        return check("selective_instrumentation", "NOT RUN", "compile_commands.json is unavailable")
    try:
        commands = json.loads(compdb.read_text())
    except Exception as exc:
        return check("selective_instrumentation", "FAIL", f"compile database is unreadable: {exc}")
    if not isinstance(commands, list):
        return check("selective_instrumentation", "FAIL", "compile database is not an array")
    instrumented: list[str] = []
    generated_instrumented: list[str] = []
    for row in commands:
        if not isinstance(row, dict):
            continue
        command = str(row.get("command", ""))
        args = row.get("arguments")
        if isinstance(args, list):
            command = " ".join(str(value) for value in args)
        if "-finstrument-functions" not in command:
            continue
        file_name = str(row.get("file", ""))
        instrumented.append(file_name)
        if "grpc_proxy_generated" in file_name or file_name.endswith("main.cc"):
            generated_instrumented.append(file_name)
    if generated_instrumented:
        return check("selective_instrumentation", "FAIL", "generated/gRPC state-machine source is blanket-instrumented", files=generated_instrumented)
    if not instrumented:
        return check("selective_instrumentation", "FAIL", "no application-owned instrumentation boundary found")
    return check("selective_instrumentation", "PASS", "instrumentation is limited to explicit application boundary sources", files=instrumented)


def _wrapper_link_regression(runtime_dir: pathlib.Path | None) -> dict[str, Any]:
    """Exercise both explicit C++ and C wrapper drivers, including .o-only C++ linking."""
    if runtime_dir is None:
        return check("wrapper_link_regression", "NOT RUN", "runtime directory was not supplied")
    if not (runtime_dir / "libfaultdebug_runtime.so").is_file():
        return check("wrapper_link_regression", "NOT RUN", "runtime library is unavailable")
    cc_wrapper = ROOT / "scripts" / "faultdebug-cc"
    cxx_wrapper = pathlib.Path(os.environ.get("FAULTDEBUG_LINK_DRIVER", str(ROOT / "scripts" / "faultdebug-cxx")))
    if not cxx_wrapper.is_file():
        return check("wrapper_link_regression", "NOT RUN", "FAULTDEBUG_LINK_DRIVER is unavailable", driver=str(cxx_wrapper))
    env = dict(os.environ)
    env["FAULTDEBUG_RUNTIME_DIR"] = str(runtime_dir.resolve())
    env["FAULTDEBUG_REAL_CC"] = shutil.which("cc") or "cc"
    env["FAULTDEBUG_REAL_CXX"] = shutil.which("c++") or "c++"
    with tempfile.TemporaryDirectory(prefix="faultdebug-v05-wrapper-") as raw:
        work = pathlib.Path(raw)
        cpp = work / "object_only.cpp"
        cpp_obj = work / "object_only.o"
        cpp_bin = work / "object_only"
        c = work / "c_main.c"
        c_obj = work / "c_main.o"
        c_bin = work / "c_main"
        cpp.write_text("#include <iostream>\nint main() { std::cout << 42 << '\\n'; }\n")
        c.write_text("#include <stdio.h>\nint main(void) { puts(\"c-ok\"); return 0; }\n")
        cpp_compile = subprocess.run([str(cxx_wrapper), "-std=c++17", "-c", str(cpp), "-o", str(cpp_obj)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        cpp_link = subprocess.run([str(cxx_wrapper), str(cpp_obj), "-o", str(cpp_bin)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30) if cpp_compile.returncode == 0 else None
        c_compile = subprocess.run([str(cc_wrapper), "-c", str(c), "-o", str(c_obj)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        c_link = subprocess.run([str(cc_wrapper), str(c_obj), "-o", str(c_bin)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30) if c_compile.returncode == 0 else None
        cpp_run = subprocess.run([str(cpp_bin)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30) if cpp_link and cpp_link.returncode == 0 else None
        c_run = subprocess.run([str(c_bin)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30) if c_link and c_link.returncode == 0 else None
    failures = []
    if cpp_compile.returncode != 0: failures.append("cpp_compile")
    if not cpp_link or cpp_link.returncode != 0: failures.append("cpp_object_only_link")
    if not cpp_run or cpp_run.stdout.strip() != "42": failures.append("cpp_execute")
    if c_compile.returncode != 0: failures.append("c_compile")
    if not c_link or c_link.returncode != 0: failures.append("c_link")
    if not c_run or c_run.stdout.strip() != "c-ok": failures.append("c_execute")
    return check("wrapper_link_regression", "FAIL" if failures else "PASS",
                 "wrapper compile/link regression failed" if failures else "explicit C++ object-only and C wrapper links passed",
                 driver=str(cxx_wrapper), failures=failures)


def _malformed_artifact_check() -> dict[str, Any]:
    try:
        from faultdebug.artifact import ArtifactError, read_artifact
    except ImportError as exc:
        return check("malformed_artifacts", "NOT RUN", f"artifact module unavailable: {exc}")
    with tempfile.TemporaryDirectory(prefix="faultdebug-v05-malformed-") as raw:
        path = pathlib.Path(raw) / "bad.fault"
        path.write_bytes(b"FDAR\x01")
        try:
            read_artifact(path)
        except (ArtifactError, ValueError, OSError):
            return check("malformed_artifacts", "PASS", "truncated FDAR is rejected")
        except Exception as exc:
            return check("malformed_artifacts", "FAIL", f"unexpected malformed-artifact exception: {exc}")
        return check("malformed_artifacts", "FAIL", "truncated FDAR was accepted")


def _run_regression(script: str, args: list[str] | None = None) -> dict[str, Any]:
    path = ROOT / "test" / script
    if not path.is_file():
        return check(f"regression_{script}", "NOT RUN", "regression script is unavailable")
    command = [sys.executable, str(path)] + (args or [])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
    if completed.returncode == 0:
        return check(f"regression_{script}", "PASS", "regression script passed", stdout=completed.stdout[-2000:])
    return check(f"regression_{script}", "FAIL", "regression script failed", returncode=completed.returncode, stderr=completed.stderr[-2000:])


def _run_grpc_regression(build_dir: pathlib.Path, output: pathlib.Path) -> dict[str, Any]:
    report_dir = output / "grpc"
    completed = subprocess.run([sys.executable, str(ROOT / "test" / "grpc_proxy_test.py"),
                                "--build-dir", str(build_dir), "--output", str(report_dir)],
                               cwd=ROOT, text=True, capture_output=True, timeout=180)
    report_path = report_dir / "report.json"
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text())
            if report.get("status") == "NOT RUN":
                return check("regression_grpc_proxy", "NOT RUN", "gRPC regression gate lacks an optional dependency", report=str(report_path))
            if report.get("status") == "PASS":
                return check("regression_grpc_proxy", "PASS", "gRPC regression gate passed", report=str(report_path))
        except (OSError, json.JSONDecodeError):
            pass
    return check("regression_grpc_proxy", "FAIL", "gRPC regression script failed", returncode=completed.returncode, stderr=completed.stderr[-2000:])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=pathlib.Path)
    parser.add_argument("--runtime-dir", type=pathlib.Path)
    parser.add_argument("--run-grpc", action="store_true")
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    checks = [
        _atomic_artifact_check(),
        _spool_contract(),
        _spool_cli_discovery(),
        _redaction_check(),
        _selective_profile(ns.build_dir),
        _wrapper_link_regression(ns.runtime_dir or ns.build_dir),
        _malformed_artifact_check(),
        _run_regression("rpc_analysis.py"),
    ]
    if ns.run_grpc and ns.build_dir is not None:
        checks.append(_run_grpc_regression(ns.build_dir, ns.output))
    else:
        checks.append(check("regression_grpc_proxy", "NOT RUN", "--run-grpc and --build-dir are required"))
    statuses = [item["status"] for item in checks]
    overall = "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    report = {"schema": 1, "status": overall, "checks": checks}
    report_path = ns.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": overall, "checks": {state: statuses.count(state) for state in ("PASS", "FAIL", "NOT RUN")}, "report": str(report_path)}, sort_keys=True))
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
