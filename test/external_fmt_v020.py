#!/usr/bin/env python3
"""Repeatable fmt 11.1.4 timing/RSS and fatal-signal evidence runner.

The runner records raw observations and applies no performance threshold.  It
returns ``NOT RUN`` when the requested external source/build inputs are absent
so an evaluator cannot mistake a skipped external-project run for a pass.
All generated drivers, binaries, artifacts, and JSON output live outside the
repository by default.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


SIGNALS = (signal.SIGILL, signal.SIGSEGV, signal.SIGBUS, signal.SIGFPE, signal.SIGABRT)
SIGNAL_NAMES = {number: signal.Signals(number).name for number in SIGNALS}
DRIVER_SOURCE = r'''
#include <csignal>
#include <cstdlib>
#include <fmt/format.h>
#include <string>

__attribute__((noinline)) static std::string fmt_work(int value) {
  return fmt::format("fmt-v020:{}:{}", value, value + 1);
}

int main(int argc, char **argv) {
  int rounds = 20000;
  if (argc > 1 && std::string(argv[1]) != "normal") rounds = 1;
  volatile std::size_t sink = 0;
  for (int i = 0; i < rounds; ++i) sink += fmt_work(i).size();
  if (argc > 1 && std::string(argv[1]) != "normal") {
    const int requested = std::atoi(argv[1]);
    std::raise(requested);
  }
  return sink == 0xdead ? 3 : 0;
}
'''


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _not_run(reason: str, output: Path) -> int:
    result = {"schema": 1, "status": "NOT RUN", "reason": reason}
    _write_json(output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


def _build_id(binary: Path) -> str | None:
    try:
        text = subprocess.check_output(["readelf", "-n", str(binary)], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", text)
    return match.group(1).lower() if match else None


def _run_timed(binary: Path, runtime_dir: Path, rounds: int) -> dict[str, Any]:
    command = [str(binary), "normal"]
    env = os.environ.copy()
    env["FAULTDEBUG_RUNTIME_DIR"] = str(runtime_dir)
    # Keep the raw wall-clock and maximum RSS values from the same invocation.
    # No threshold or derived pass/fail decision is applied to either value.
    rss_kb = None
    timed = subprocess.run(
        ["/usr/bin/time", "-f", "%e %M", *command],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines = [line.strip() for line in timed.stderr.splitlines() if line.strip()]
    elapsed_s = None
    if lines:
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s+(\d+)", lines[-1])
        if match:
            elapsed_s = float(match.group(1))
            rss_kb = int(match.group(2))
    return {
        "rounds": rounds,
        "elapsed_s": elapsed_s,
        "max_rss_kb": rss_kb,
        "measurement_valid": elapsed_s is not None and rss_kb is not None,
        "returncode": timed.returncode,
        "stderr": timed.stderr[-500:],
    }


def _last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _signal_run(binary: Path, runtime_dir: Path, artifact_dir: Path, number: int, repo: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "faultdebug.cli",
        "run",
        "--artifact-dir",
        str(artifact_dir),
        "--",
        str(binary),
        str(number),
    ]
    env = os.environ.copy()
    env["FAULTDEBUG_RUNTIME_DIR"] = str(runtime_dir)
    env["PYTHONPATH"] = str(repo) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    completed = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    summary = _last_json(completed.stdout) or {}
    artifact = Path(summary["artifact"]) if summary.get("artifact") else None
    crash_signal = None
    crash_count = 0
    artifact_status = None
    if artifact and artifact.is_file():
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from faultdebug.artifact import read_artifact

        report = read_artifact(artifact)
        crash_count = len(report.get("crashes", []))
        artifact_status = (report.get("collector") or {}).get("status")
        if report.get("crashes"):
            crash_signal = report["crashes"][0].get("signal")
    observed_signal = (summary.get("target") or {}).get("signal")
    return {
        "expected_signal": number,
        "expected_name": SIGNAL_NAMES[number],
        "returncode": completed.returncode,
        "observed_signal": observed_signal,
        "artifact": str(artifact) if artifact else None,
        "artifact_exists": bool(artifact and artifact.is_file()),
        "collector_status": artifact_status,
        "crash_count": crash_count,
        "crash_signal": crash_signal,
        "pass": observed_signal == number and bool(artifact and artifact.is_file()) and crash_signal == number,
        "stdout": completed.stdout[-1000:],
        "stderr": completed.stderr[-1000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/tmp/faultdebug-external"))
    parser.add_argument("--original-build", type=Path, default=Path("/tmp/faultdebug-external-build-original"))
    parser.add_argument("--instrumented-build", type=Path, default=Path("/tmp/faultdebug-external-build-instrumented"))
    parser.add_argument("--runtime-dir", type=Path, default=Path("build"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    ns = parser.parse_args()
    output = ns.output.resolve()
    required = [ns.source, ns.original_build, ns.instrumented_build, ns.runtime_dir / "libfaultdebug_runtime.so"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _not_run("missing external inputs: " + ", ".join(missing), output)
    if not ns.repo.is_dir() or not (ns.repo / "faultdebug").is_dir():
        return _not_run("faultdebug source package is unavailable", output)
    if str(ns.repo) not in sys.path:
        sys.path.insert(0, str(ns.repo))
    try:
        import faultdebug  # noqa: F401
    except Exception as exc:
        return _not_run("faultdebug Python package is unavailable: " + str(exc), output)
    if shutil.which(os.environ.get("CXX", "clang++")) is None:
        return _not_run("C++ compiler is unavailable", output)
    if not Path("/usr/bin/time").is_file():
        return _not_run("/usr/bin/time is unavailable", output)
    if ns.repeats < 1:
        return _not_run("--repeats must be positive", output)
    def find_fmt_lib(build: Path) -> Path | None:
        candidates = [build / "libfmtd.a", build / "libfmt.a"]
        candidates.extend(sorted(build.rglob("libfmtd.a")))
        candidates.extend(sorted(build.rglob("libfmt.a")))
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    original_lib = find_fmt_lib(ns.original_build)
    instrumented_lib = find_fmt_lib(ns.instrumented_build)
    if original_lib is None or instrumented_lib is None:
        return _not_run("fmt static libraries are missing", output)
    work = ns.work_dir or Path(tempfile.mkdtemp(prefix="faultdebug-fmt-v020-", dir="/tmp"))
    work.mkdir(parents=True, exist_ok=True)
    source = work / "driver.cpp"
    source.write_text(DRIVER_SOURCE, encoding="utf-8")
    clangxx = os.environ.get("CXX", "clang++")
    # Keep the driver at O0.  The external fmt library is the instrumented
    # target under test; instrumenting this small driver as well can make
    # libstdc++ inline bodies reference non-exported definitions on some
    # Clang/libstdc++ combinations.  The trace still exercises instrumented
    # fmt functions from the external build.
    common = [clangxx, "-I", str(ns.source / "include"), "-g", "-O0", "-fno-lto"]
    original = work / "fmt-original"
    instrumented = work / "fmt-instrumented"
    commands = []
    original_obj = work / "fmt-original.o"
    instrumented_obj = work / "fmt-instrumented.o"
    build_commands = [
        common + ["-c", str(source), "-o", str(original_obj)],
        common + ["-c", str(source), "-o", str(instrumented_obj)],
        [clangxx, str(original_obj), str(original_lib), "-Wl,--build-id", "-o", str(original)],
        [clangxx, str(instrumented_obj), str(instrumented_lib), "-L", str(ns.runtime_dir), "-lfaultdebug_runtime", "-Wl,--build-id", "-Wl,-rpath," + str(ns.runtime_dir.resolve()), "-o", str(instrumented)],
    ]
    for command in build_commands:
        completed = subprocess.run(command, cwd=ns.repo, capture_output=True, text=True)
        commands.append({"command": command, "returncode": completed.returncode, "stderr": completed.stderr[-2000:]})
        if completed.returncode:
            result = {"schema": 1, "status": "FAIL", "reason": "driver build failed", "commands": commands}
            _write_json(output, result)
            print(json.dumps(result, sort_keys=True))
            return 1
    timing = {
        "repeats": ns.repeats,
        "original": [_run_timed(original, ns.runtime_dir, 20000) for _ in range(ns.repeats)],
        "instrumented": [_run_timed(instrumented, ns.runtime_dir, 20000) for _ in range(ns.repeats)],
        "threshold_applied": False,
    }
    timing_samples = timing["original"] + timing["instrumented"]
    timing_valid = all(
        sample["returncode"] == 0
        and sample["measurement_valid"]
        for sample in timing_samples
    )
    signals = []
    signal_dir = work / "artifacts"
    for number in SIGNALS:
        signals.append(_signal_run(instrumented, ns.runtime_dir, signal_dir / SIGNAL_NAMES[number], number, ns.repo))
    result = {
        "schema": 1,
        "status": "PASS" if timing_valid and all(item["pass"] for item in signals) else "FAIL",
        "inputs": {"source": str(ns.source), "original_build": str(ns.original_build), "instrumented_build": str(ns.instrumented_build), "original_library": str(original_lib), "instrumented_library": str(instrumented_lib)},
        "binaries": {"original": str(original), "instrumented": str(instrumented), "original_build_id": _build_id(original), "instrumented_build_id": _build_id(instrumented)},
        "commands": commands,
        "timing_rss": timing,
        "timing_valid": timing_valid,
        "signals": signals,
        "limitations": ["single fmt driver workload", "driver is not instrumented separately because fmt library is the instrumented external target", "raw timing/RSS only; no acceptance threshold", "signal capture is evaluated for the instrumented binary"],
    }
    _write_json(output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
