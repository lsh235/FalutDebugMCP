#!/usr/bin/env python3
"""Build and run the paired non-faulting C++ call benchmark for v1.1."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("cpp_call_workload.cpp")
LAUNCHER = Path(__file__).with_name("cpp_call_benchmark_launcher.sh")
THREADS = 32
ITERATIONS_PER_THREAD = 500
OPERATIONS = THREADS * ITERATIONS_PER_THREAD * 3
WORKLOAD_PROFILES = (("clean-1x500", 1, 500, False),
                     ("clean-8x500", 8, 500, False),
                     ("clean-32x500", 32, 500, False),
                     ("overflow-1x5000", 1, 5000, True))
UINT64_MASK = (1 << 64) - 1
LEAF_MULTIPLIER = 0x9e3779b185ebca87
INITIAL_STATE = 0x243f6a8885a308d3
ITERATION_SEED = 0x517cc1b727220a95

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def invoke(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 600) -> dict[str, Any]:
    start = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                   text=True, timeout=timeout, check=False)
        return {"command": command, "cwd": str(cwd), "returncode": completed.returncode,
                "duration_s": round(time.monotonic() - start, 3),
                "stdout": completed.stdout[-5000:], "stderr": completed.stderr[-5000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "cwd": str(cwd), "returncode": None,
                "duration_s": round(time.monotonic() - start, 3), "error": str(exc)}


def first_line(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None and not Path(command[0]).is_file():
        return None
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (result.stdout or result.stderr).splitlines()
    return lines[0] if result.returncode == 0 and lines else None


def build_id(binary: Path) -> str | None:
    command = ["readelf", "-n", str(binary)]
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", result.stdout)
    return match.group(1).lower() if result.returncode == 0 and match else None


def expected_checksum(threads: int, iterations: int) -> int:
    """Independent Python implementation of the checked-in uint64 workload."""
    checksum = 0
    for worker in range(threads):
        state = INITIAL_STATE ^ worker
        for iteration in range(iterations):
            value = state ^ ((iteration + ITERATION_SEED) & UINT64_MASK)
            leaf_value = (((value ^ (value >> 7)) & UINT64_MASK) * LEAF_MULTIPLIER) & UINT64_MASK
            state = (state + leaf_value + iteration) & UINT64_MASK
        checksum ^= state
    return checksum


def expected_result_line(threads: int, iterations: int) -> str:
    operations = threads * iterations * 3
    return (f"threads={threads} iterations_per_thread={iterations} "
            f"function_calls={operations} checksum={expected_checksum(threads, iterations)}")


def save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--python", type=Path, default=ROOT / ".venv/bin/python")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    ns = parser.parse_args()
    work = ns.work_dir.expanduser().resolve()
    output = ns.output.expanduser().resolve()
    runtime_dir = ns.runtime_dir.expanduser().resolve()
    # Preserve the clang++ symlink name: resolving it may turn it into the
    # clang driver, which skips the default C++ standard-library link step.
    compiler = ROOT / ".tools/bin/clang++"
    runtime = runtime_dir / "libfaultdebug_runtime.so"
    baseline = work / "cpp-calls-baseline"
    instrumented = work / "cpp-calls-instrumented"
    baseline_runner = work / "baseline-runner"
    instrumented_runner = work / "instrumented-runner"
    work.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema": 1,
        "schema_name": "faultdebug.cpp_call_benchmark_evidence",
        "status": "NOT RUN",
        "workload": {"source": str(SOURCE), "source_sha256": sha256(SOURCE),
                     "functions_per_iteration": 3,
                     "profiles": [{"name": name, "threads": threads,
                                   "iterations_per_thread": iterations,
                                   "operations_per_invocation": threads * iterations * 3,
                                   "expected_result_line": expected_result_line(threads, iterations),
                                   "forced_overflow": overflow}
                                  for name, threads, iterations, overflow in WORKLOAD_PROFILES],
                     "description": "non-faulting C++ call chain with synchronized workers: worker -> step -> combine -> leaf; expected checksums are independently calculated by this driver"},
        "environment": {"platform": platform.platform(), "machine": platform.machine(),
                        "python": sys.version.splitlines()[0],
                        "compiler": first_line([str(compiler), "--version"]),
                        "runtime_sha256": sha256(runtime) if runtime.is_file() else None,
                        "nm": first_line(["nm", "--version"]),
                        "readelf": first_line(["readelf", "--version"]),
                        "git": first_line(["git", "--version"])},
        "builds": {},
        "smoke_checks": {},
        "benchmark": None,
        "limitations": [
            "Measurements are descriptive for this workload and host; no pass threshold is applied.",
            "Process wall time includes the faultdebug launcher and collector; target wall time is reported separately by the launcher.",
            "The baseline links the runtime to use the same launcher handshake but compiles the workload without function instrumentation.",
            "This microbenchmark does not represent arbitrary application mixes or fault-path cost.",
        ],
    }
    missing = []
    for label, available in (("Clang 18 compiler", compiler.is_file() and os.access(compiler, os.X_OK)),
                             ("runtime library", runtime.is_file()),
                             ("benchmark Python", ns.python.is_file()),
                             ("faultdebug package", (ROOT / "faultdebug").is_dir())):
        if not available:
            missing.append(label)
    for tool in ("readelf", "nm"):
        if not shutil.which(tool):
            missing.append(tool)
    if ns.repeats < 1 or ns.warmups < 0:
        missing.append("valid repeat/warmup counts")
    if missing:
        report["reason"] = "required input unavailable: " + ", ".join(missing)
        save(output, report)
        print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
        return 0

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env.get("PYTHONPATH", ""))
    env["FAULTDEBUG_RUNTIME_DIR"] = str(runtime_dir)
    common_flags = ["-std=c++17", "-O0", "-g", "-fno-optimize-sibling-calls",
                    "-fno-lto", "-fno-omit-frame-pointer", "-Wl,--build-id=sha1"]
    baseline_command = [str(compiler), *common_flags, str(SOURCE),
                        "-L", str(runtime_dir), "-Wl,-rpath," + str(runtime_dir),
                        "-lfaultdebug_runtime", "-ldl", "-pthread", "-o", str(baseline)]
    baseline_build = invoke(baseline_command, cwd=ROOT, env=env)
    report["builds"]["baseline"] = baseline_build
    if baseline_build["returncode"] != 0:
        report["status"] = "FAIL"
        report["reason"] = "baseline compile/link failed"
        save(output, report)
        print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
        return 1

    instrumented_env = dict(env)
    instrumented_env["FAULTDEBUG_REAL_CXX"] = str(compiler)
    instrumented_env["FAULTDEBUG_REAL_CC"] = str(compiler)
    instrumented_command = [str(ROOT / "scripts/faultdebug-cxx"), *common_flags,
                            str(SOURCE), "-o", str(instrumented)]
    instrumented_build = invoke(instrumented_command, cwd=ROOT, env=instrumented_env)
    report["builds"]["instrumented"] = instrumented_build
    if instrumented_build["returncode"] != 0:
        report["status"] = "FAIL"
        report["reason"] = "instrumented compile/link via project wrapper failed"
        save(output, report)
        print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
        return 1

    report["builds"]["baseline"].update({"binary": str(baseline),
                                         "sha256": sha256(baseline),
                                         "build_id": build_id(baseline),
                                         "instrumentation": "disabled; runtime linked"})
    report["builds"]["instrumented"].update({"binary": str(instrumented),
                                             "sha256": sha256(instrumented),
                                             "build_id": build_id(instrumented),
                                             "instrumentation": "enabled by scripts/faultdebug-cxx"})
    if not report["builds"]["baseline"]["build_id"] or not report["builds"]["instrumented"]["build_id"]:
        report["status"] = "FAIL"
        report["reason"] = "one or both workload binaries lack Build IDs"
        save(output, report)
        print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
        return 1

    hook_symbols: dict[str, list[str]] = {}
    for name, binary in (("baseline", baseline), ("instrumented", instrumented)):
        symbols = invoke(["nm", "-D", str(binary)], cwd=ROOT, env=env)
        hook_symbols[name] = [line.split()[-1] for line in symbols.get("stdout", "").splitlines()
                              if line.split() and line.split()[-1] in
                              {"__cyg_profile_func_enter", "__cyg_profile_func_exit"}]
    hooks_expected = {"__cyg_profile_func_enter", "__cyg_profile_func_exit"}
    baseline_hooks = set(hook_symbols["baseline"])
    instrumented_hooks = set(hook_symbols["instrumented"])
    report["instrumentation_hooks"] = {
        "status": "PASS" if not baseline_hooks and instrumented_hooks == hooks_expected else "FAIL",
        "baseline": sorted(baseline_hooks),
        "instrumented": sorted(instrumented_hooks),
        "expected_instrumented": sorted(hooks_expected),
    }
    if report["instrumentation_hooks"]["status"] != "PASS":
        report["status"] = "FAIL"
        report["reason"] = "baseline/instrumented hook-symbol contract failed"
        save(output, report)
        print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
        return 1

    shutil.copyfile(LAUNCHER, baseline_runner)
    baseline_runner.chmod(0o755)
    shutil.copyfile(LAUNCHER, instrumented_runner)
    instrumented_runner.chmod(0o755)
    report["launchers"] = {"source": str(LAUNCHER), "sha256": sha256(LAUNCHER),
                           "baseline_runner_sha256": sha256(baseline_runner),
                           "instrumented_runner_sha256": sha256(instrumented_runner)}
    run_env = dict(env)
    run_env["FAULTDEBUG_BENCH_PYTHON"] = str(ns.python.resolve())
    run_env["FAULTDEBUG_BENCH_BASELINE"] = str(baseline)
    run_env["FAULTDEBUG_BENCH_INSTRUMENTED"] = str(instrumented)
    expected_output = expected_result_line(THREADS, ITERATIONS_PER_THREAD)
    for name, binary in (("baseline", baseline), ("instrumented", instrumented)):
        smoke = invoke([str(ns.python.resolve()), "-m", "faultdebug.cli", "run", "--",
                        str(binary), str(THREADS), str(ITERATIONS_PER_THREAD)],
                       cwd=ROOT, env=run_env, timeout=30)
        report["smoke_checks"][name] = smoke
        target_line = next((line for line in smoke.get("stdout", "").splitlines()
                            if line.startswith("threads=")), None)
        result_line = next((line for line in reversed(smoke.get("stdout", "").splitlines())
                            if line.startswith("{")), None)
        try:
            summary = json.loads(result_line) if result_line else {}
        except json.JSONDecodeError:
            summary = {}
        matches = target_line == expected_output
        runtime_status = summary.get("collector", {}).get("status")
        overflow_bits = (1 << 3) | (1 << 4) | (1 << 5) | (1 << 9)
        no_overflow = isinstance(runtime_status, int) and not (runtime_status & overflow_bits)
        passed = (smoke.get("returncode") == 0 and matches and
                  summary.get("target", {}).get("returncode") == 0 and
                  summary.get("collector", {}).get("ok") is True and no_overflow)
        report["smoke_checks"][name]["status"] = "PASS" if passed else "FAIL"
        report["smoke_checks"][name]["target_output"] = target_line
        report["smoke_checks"][name]["collector_ok"] = summary.get("collector", {}).get("ok")
        report["smoke_checks"][name]["runtime_status_flags"] = runtime_status
        report["smoke_checks"][name]["no_overflow_or_partial_flags"] = no_overflow
        report["smoke_checks"][name]["expected_workload_output"] = expected_output
        report["smoke_checks"][name]["target_wall_time_ms"] = summary.get("target", {}).get("wall_time_ms")
    report["smoke_checks"]["same_workload_output"] = {
        "status": "PASS" if all(
            report["smoke_checks"][name].get("status") == "PASS" for name in ("baseline", "instrumented")) else "FAIL",
        "expected": expected_output,
    }
    if any(item.get("status") != "PASS" for item in report["smoke_checks"].values()):
        report["status"] = "FAIL"
        report["reason"] = "baseline/instrumented smoke validation failed"
        save(output, report)
        print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
        return 1

    from faultdebug.run import run_target
    try:
        trace_report = run_target([str(instrumented), str(THREADS), str(ITERATIONS_PER_THREAD)], timeout=30)
        trace_threads = trace_report.get("threads", [])
        trace_events = [event for thread in trace_threads for event in thread.get("events", [])]
        dropped = sum(int(thread.get("dropped_count", 0)) for thread in trace_threads)
        runtime_status = int((trace_report.get("collector") or {}).get("status", 0))
        trace_flags_ok = not (runtime_status & ((1 << 3) | (1 << 4) | (1 << 5) | (1 << 9)))
        report["direct_trace_check"] = {
            "status": "PASS" if trace_report.get("target", {}).get("returncode") == 0 and
                      trace_report.get("target", {}).get("signal") is None and
                      trace_report.get("collector", {}).get("ok") is True and
                      trace_report.get("complete") is True and trace_flags_ok and dropped == 0 and len(trace_threads) == THREADS + 1 and
                      bool(trace_events) else "FAIL",
            "target": trace_report.get("target"),
            "collector": trace_report.get("collector"),
            "trace_complete": trace_report.get("complete"),
            "runtime_status_flags": runtime_status,
            "thread_records": len(trace_threads),
            "expected_thread_records": THREADS + 1,
            "event_records": len(trace_events),
            "dropped_count": dropped,
            "per_thread_event_count_min": min((len(row.get("events", [])) for row in trace_threads), default=0),
            "per_thread_event_count_max": max((len(row.get("events", [])) for row in trace_threads), default=0),
            "artifact_written": bool(trace_report.get("artifact")),
        }
    except Exception as exc:
        report["direct_trace_check"] = {"status": "FAIL", "error": str(exc)}
    if report["direct_trace_check"]["status"] != "PASS":
        report["status"] = "FAIL"
        report["reason"] = "instrumented direct trace or no-loss check failed"
        save(output, report)
        print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
        return 1

    benchmark_profiles: dict[str, Any] = {}
    profile_errors: list[str] = []
    overflow_bit = 1 << 3
    artifact_base = work / "measurement-artifacts"
    for profile_name, workers, iterations, forced_overflow in WORKLOAD_PROFILES:
        operations = workers * iterations * 3
        expected_line = expected_result_line(workers, iterations)
        raw_benchmark = work / f"benchmark-{profile_name}.json"
        benchmark_command = [str(ns.python.resolve()), "-m", "faultdebug.cli", "benchmark",
                             "--baseline", str(baseline_runner), "--instrumented", str(instrumented_runner),
                             "--repeats", str(ns.repeats), "--warmups", str(ns.warmups),
                             "--timeout", "30", "--cwd", str(ROOT), "--operations", str(operations),
                             "--expected-result-line", expected_line,
                             "--artifact-dir", str(artifact_base),
                             "--output", str(raw_benchmark), "--",
                             "{artifact_dir}", str(workers), str(iterations)]
        benchmark_run = invoke(benchmark_command, cwd=ROOT, env=run_env, timeout=900)
        profile: dict[str, Any] = {
            "workload": {"threads": workers, "iterations_per_thread": iterations,
                         "operations_per_invocation": operations,
                         "expected_result_line": expected_line,
                         "forced_overflow": forced_overflow},
            "benchmark_cli": benchmark_run,
        }
        if benchmark_run.get("returncode") != 0 or not raw_benchmark.is_file():
            profile["status"] = "FAIL"
            profile["reason"] = "paired benchmark CLI failed or report was not written"
            benchmark_profiles[profile_name] = profile
            profile_errors.append(profile_name)
            continue
        benchmark = json.loads(raw_benchmark.read_text(encoding="utf-8"))
        profile["benchmark"] = benchmark
        profile["benchmark_cli_report"] = {"path": str(raw_benchmark), "sha256": sha256(raw_benchmark)}
        checks: dict[str, Any] = {}
        checks["benchmark_status"] = benchmark.get("status") == "PASS"
        checks["sample_count"] = len(benchmark.get("samples", [])) == 2 * ns.repeats
        checks["warmup_count"] = len(benchmark.get("warmups", [])) == 2 * ns.warmups
        all_rows = benchmark.get("samples", []) + benchmark.get("warmups", [])
        sample_ids = [row.get("sample_id") for row in all_rows]
        artifact_directories = [row.get("artifact_directory") for row in all_rows]
        checks["sample_identity_contract"] = (
            all(isinstance(value, str) and value for value in sample_ids)
            and len(sample_ids) == len(set(sample_ids))
            and all(isinstance(value, str) and value for value in artifact_directories)
            and len(artifact_directories) == len(set(artifact_directories))
            and all(Path(value).is_dir() for value in artifact_directories)
        )
        checks["workload_result_contract"] = all(
            row.get("workload_result", {}).get("status") == "PASS"
            and row.get("workload_result", {}).get("expected") == expected_line
            for row in all_rows
        )
        checks["target_collector_contract"] = all(
            row.get("target_result", {}).get("status") == "PASS"
            and row.get("collector_result", {}).get("status") == "PASS"
            for row in all_rows
        )
        checks["timing_and_artifact_metrics"] = all(
            row.get("metrics", {}).get("wall_time_ms", {}).get("status") == "PASS"
            and row.get("metrics", {}).get("target_wall_time_ms", {}).get("status") == "PASS"
            and row.get("metrics", {}).get("artifact_size_bytes", {}).get("status") == "PASS"
            and row.get("metrics", {}).get("loss_count", {}).get("status") == "PASS"
            and row.get("metrics", {}).get("trace_quality", {}).get("status") == "PASS"
            for row in all_rows
        )
        sample_groups = {
            target: [row for row in benchmark.get("samples", []) if row.get("target") == target]
            for target in ("baseline", "instrumented")
        }
        def trace_artifact(row: dict[str, Any]) -> dict[str, Any]:
            quality = row.get("metrics", {}).get("trace_quality", {}).get("value") or {}
            artifacts = quality.get("artifacts") or []
            return artifacts[0] if artifacts and isinstance(artifacts[0], dict) else {}

        def loss_value(row: dict[str, Any]) -> int | None:
            value = row.get("metrics", {}).get("loss_count", {}).get("value")
            return int(value) if isinstance(value, int) else None

        if forced_overflow:
            baseline_clean = all(
                loss_value(row) == 0
                and trace_artifact(row).get("trace_complete") is True
                for row in sample_groups["baseline"]
            )
            instrumented_loss = all(
                loss_value(row) is not None and loss_value(row) > 0
                and trace_artifact(row).get("trace_complete") is False
                and isinstance(trace_artifact(row).get("status_flags"), int)
                and int(trace_artifact(row)["status_flags"]) & overflow_bit
                for row in sample_groups["instrumented"]
            )
            checks["forced_overflow_disclosed"] = baseline_clean and instrumented_loss
        else:
            clean = all(
                loss_value(row) == 0
                and trace_artifact(row).get("trace_complete") is True
                for row in all_rows
            )
            checks["clean_trace_no_loss"] = clean
        profile["checks"] = checks
        profile["status"] = "PASS" if all(checks.values()) else "FAIL"
        if profile["status"] != "PASS":
            profile_errors.append(profile_name)
        benchmark_profiles[profile_name] = profile

    report["benchmark_matrix"] = benchmark_profiles
    report["benchmark_status_interpretation"] = (
        "PASS requires every sample to match the independently computed workload result and report its target, "
        "collector, target/process timing, artifact quality, and loss. Clean profiles require zero loss; the "
        "1x5000 profile requires baseline zero loss and explicit instrumented overflow. Timing remains descriptive."
    )
    report["status"] = "FAIL" if profile_errors else "PASS"
    if profile_errors:
        report["reason"] = "benchmark profile contracts failed: " + ", ".join(profile_errors)
    else:
        report["reason"] = "all clean and forced-overflow profiles met their recorded evidence contracts"
    save(output, report)
    print(json.dumps({"status": report["status"], "report": str(output)}, sort_keys=True))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
