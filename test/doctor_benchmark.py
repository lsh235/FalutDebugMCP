#!/usr/bin/env python3
"""Focused CLI/report, compiler-wrapper, runtime, and benchmark contract checks."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.benchmark import BENCHMARK_SCHEMA_NAME, run_benchmark
from faultdebug.artifact import read_artifact, write_artifact
from faultdebug.cli import main as cli_main
from faultdebug.doctor import (_compiler_version, _runtime_probe,
                               collect_doctor_report, overall_status)
from faultdebug.run import run_target
from unittest.mock import patch


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)


def _runtime_smoke(build_dir: Path) -> None:
    runtime = build_dir / "libfaultdebug_runtime.so"
    target = build_dir / "test" / "fd_c_chain"
    assert runtime.is_file(), f"runtime library not found: {runtime}"
    assert target.is_file(), f"native smoke target not found: {target}"
    probe = _runtime_probe(runtime.resolve())
    assert probe.get("returncode") == 0 and not probe.get("error"), probe
    with patch.dict(os.environ, {"FAULTDEBUG_RUNTIME_DIR": str(build_dir)}, clear=False):
        report = run_target([str(target), "3"], timeout=10)
    assert report.get("collector", {}).get("ok") is True, report.get("collector")
    assert report.get("target", {}).get("returncode") == 0, report.get("target")
    assert report.get("threads"), "runtime reached readiness but recorded no instrumented threads"
    assert float(report["target"]["wall_time_ms"]) >= 0

    wrap = build_dir / "test" / "fd_wrap"
    assert wrap.is_file(), f"overflow-contract target not found: {wrap}"
    with tempfile.TemporaryDirectory(prefix="faultdebug-success-telemetry-") as raw:
        artifact_root = Path(raw)
        default = run_target([str(wrap), "1"], timeout=10, artifact_dir=artifact_root)
        assert default.get("target", {}).get("returncode") == 0
        assert not list(artifact_root.rglob("*.fault")), "clean success wrote an artifact without opt-in"
        opted = run_target([str(wrap), "1"], timeout=10, artifact_dir=artifact_root,
                           collect_success=True)
        assert opted.get("target", {}).get("returncode") == 0 and opted.get("artifact"), opted
        clean_trace = read_artifact(Path(opted["artifact"]))
        assert clean_trace.get("complete") is True, clean_trace.get("snapshot_consistency")
        with patch.dict(os.environ, {"FAULTDEBUG_CONFIG": "events=8,threads=2"}, clear=False):
            overflow = run_target([str(wrap), "10000"], timeout=20,
                                  artifact_dir=artifact_root, collect_success=True)
        assert overflow.get("target", {}).get("returncode") == 0, overflow.get("target")
        overflow_trace = read_artifact(Path(overflow["artifact"]))
        overflow_dropped = sum(int(row.get("dropped_count", 0)) for row in overflow_trace.get("threads", []))
        assert overflow_trace.get("complete") is False and overflow_dropped > 0, overflow_trace
        assert int(overflow_trace["header"]["status"]) & (1 << 3)
    print("runtime-load-and-launch-smoke-pass")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--require-runtime-smoke", action="store_true")
    args = parser.parse_args()
    if args.require_runtime_smoke:
        assert args.build_dir is not None, "--require-runtime-smoke requires --build-dir"
        _runtime_smoke(args.build_dir.resolve())

    doctor = collect_doctor_report()
    assert doctor["schema"] == 1 and doctor["schema_name"] == "faultdebug.doctor"
    assert doctor["status"] in {"PASS", "FAIL", "NOT RUN"}
    assert {item["status"] for item in doctor["checks"]} <= {"PASS", "FAIL", "NOT RUN"}
    faultdebug_package = next(item for item in doctor["checks"] if item["name"] == "package:faultdebug")
    assert faultdebug_package["version"] == "1.1.0"
    installed_version = importlib.metadata.version
    with patch("faultdebug.doctor.importlib.metadata.version",
               side_effect=lambda name: "1.0.0" if name == "faultdebug" else installed_version(name)):
        stale_metadata = collect_doctor_report()
    stale_package = next(item for item in stale_metadata["checks"]
                         if item["name"] == "package:faultdebug")
    assert stale_package["status"] == "PASS"
    assert stale_package["version"] == "1.1.0" and stale_package["distribution_version"] == "1.0.0"
    essential = {"python", "package:libclang", "package:pyelftools", "package:mcp",
                 "tool:clang", "tool:clang++", "runtime-library"}
    healthy_checks = [{"name": name, "status": "PASS"} for name in essential]
    assert overall_status(healthy_checks) == "PASS"
    unavailable = [dict(item) for item in healthy_checks]
    next(item for item in unavailable if item["name"] == "tool:clang")["status"] = "NOT RUN"
    assert overall_status(unavailable) == "NOT RUN"
    failed_and_unavailable = [dict(item) for item in unavailable]
    next(item for item in failed_and_unavailable if item["name"] == "package:pyelftools")["status"] = "FAIL"
    assert overall_status(failed_and_unavailable) == "FAIL"
    unavailable = [dict(item) for item in healthy_checks]
    unavailable.append({"name": "optional-tool", "status": "FAIL"})
    assert overall_status(unavailable) == "FAIL"

    original_version = importlib.metadata.version
    original_which = shutil.which
    def broken_setup_version(name: str) -> str:
        if name == "pyelftools":
            raise importlib.metadata.PackageNotFoundError(name)
        return "1.1.0" if name == "faultdebug" else original_version(name)
    def no_compiler(command: str) -> str | None:
        if Path(command).name in {"cc", "c++", "clang", "clang-18", "clang++", "clang++-18"}:
            return None
        return original_which(command)
    stdout = io.StringIO()
    missing_setup = {"FAULTDEBUG_REAL_CC": "", "FAULTDEBUG_REAL_CXX": "",
                     "FAULTDEBUG_RUNTIME_DIR": "/nonexistent/faultdebug-doctor-test"}
    with patch.dict(os.environ, missing_setup), \
         patch("faultdebug.doctor.importlib.metadata.version", side_effect=broken_setup_version), \
         patch("faultdebug.doctor.shutil.which", side_effect=no_compiler), \
         patch("sys.argv", ["fault-debug", "doctor", "--json"]), \
         redirect_stdout(stdout):
        doctor_exit = cli_main()
    failed_report = json.loads(stdout.getvalue())
    assert doctor_exit == 1 and failed_report["status"] == "FAIL"
    assert next(item for item in failed_report["checks"] if item["name"] == "package:pyelftools")["status"] == "FAIL"
    assert next(item for item in failed_report["checks"] if item["name"] == "tool:clang")["status"] == "NOT RUN"
    stdout = io.StringIO()
    with patch.dict(os.environ, missing_setup), \
         patch("faultdebug.doctor.shutil.which", return_value=None), \
         patch("sys.argv", ["fault-debug", "doctor", "--json"]), redirect_stdout(stdout):
        no_toolchain = collect_doctor_report()
        doctor_exit = cli_main()
    assert no_toolchain["status"] == "NOT RUN", no_toolchain["checks"]
    assert doctor_exit == 2 and json.loads(stdout.getvalue())["status"] == "NOT RUN"
    assert next(item for item in no_toolchain["checks"] if item["name"] == "tool:clang")["status"] == "NOT RUN"

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        log = root / "compiler-executed.log"
        compiler_body = (
            'if [ "${1:-}" = "--version" ]; then '
            'printf "clang version 18.1.0\\n"; '
            'else printf "%s\\n" "$0" >> "$FAULTDEBUG_TEST_COMPILER_LOG"; fi'
        )
        selected_compiler = root / "configured-clang"
        _executable(selected_compiler, compiler_body)
        selected_cxx = root / "configured-clang++"
        _executable(selected_cxx, compiler_body)
        fallback_cc = root / "cc"
        _executable(fallback_cc, compiler_body)
        fallback_cxx = root / "c++"
        _executable(fallback_cxx, compiler_body)
        c_source = root / "wrapper-contract.c"
        c_source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        cxx_source = root / "wrapper-contract.cpp"
        cxx_source.write_text("int main() { return 0; }\n", encoding="utf-8")
        wrapper_env = os.environ.copy()
        wrapper_env["PATH"] = os.pathsep.join((str(root), "/usr/bin", "/bin"))
        wrapper_env["FAULTDEBUG_TEST_COMPILER_LOG"] = str(log)
        wrapper_cases = (
            ("clang", "FAULTDEBUG_REAL_CC", selected_compiler, "faultdebug-cc", c_source),
            ("clang++", "FAULTDEBUG_REAL_CXX", selected_cxx, "faultdebug-cxx", cxx_source),
        )
        for name, setting, compiler, wrapper_name, source in wrapper_cases:
            wrapper_env[setting] = str(compiler)
            default = "cc" if name == "clang" else "c++"
            with patch.dict(os.environ, wrapper_env, clear=True):
                selected = _compiler_version(name, setting, default)
            assert selected and selected["path"] == str(compiler)
            assert selected["selected_from"] == setting
            assert "clang version 18" in selected["version"].lower()
            log.unlink(missing_ok=True)
            subprocess.run([str(ROOT / "scripts" / wrapper_name), "-c", str(source),
                            "-o", str(root / f"{name}.o")], env=wrapper_env,
                           check=True, capture_output=True, text=True)
            assert log.read_text(encoding="utf-8").splitlines() == [str(compiler)]

        for name, setting, default, wrapper_name, source, compiler in (
            ("clang", "FAULTDEBUG_REAL_CC", "cc", "faultdebug-cc", c_source, fallback_cc),
            ("clang++", "FAULTDEBUG_REAL_CXX", "c++", "faultdebug-cxx", cxx_source, fallback_cxx),
        ):
            wrapper_env.pop(setting, None)
            with patch.dict(os.environ, wrapper_env, clear=True):
                selected = _compiler_version(name, setting, default)
            assert selected and selected["selected_from"] == "wrapper default"
            assert selected["path"] == str(compiler)
            log.unlink(missing_ok=True)
            subprocess.run([str(ROOT / "scripts" / wrapper_name), "-c", str(source),
                            "-o", str(root / f"{name}-default.o")], env=wrapper_env,
                           check=True, capture_output=True, text=True)
            assert log.read_text(encoding="utf-8").splitlines() == [str(compiler)]

        invalid_cc = root / "missing-configured-compiler"
        with patch.dict(os.environ, {"PATH": wrapper_env["PATH"],
                                     "FAULTDEBUG_REAL_CC": str(invalid_cc),
                                     "FAULTDEBUG_REAL_CXX": str(selected_cxx)}):
            invalid = _compiler_version("clang", "FAULTDEBUG_REAL_CC", "cc")
            invalid_report = collect_doctor_report()
        assert invalid and invalid.get("error")
        assert invalid["selected_from"] == "FAULTDEBUG_REAL_CC"
        invalid_clang = next(item for item in invalid_report["checks"]
                             if item["name"] == "tool:clang")
        assert invalid_clang["status"] == "FAIL"
        assert invalid_clang.get("path") is None
        assert invalid_clang["command"] == str(invalid_cc)

        empty_runtime_dir = root / "empty-runtime"
        empty_runtime_dir.mkdir()
        empty_runtime = empty_runtime_dir / "libfaultdebug_runtime.so"
        empty_runtime.write_bytes(b"")
        bogus_runtime_dir = root / "bogus-runtime"
        bogus_runtime_dir.mkdir()
        bogus_runtime = bogus_runtime_dir / "libfaultdebug_runtime.so"
        bogus_runtime.write_bytes(b"not an ELF shared library")
        assert _runtime_probe(empty_runtime).get("error")
        assert _runtime_probe(bogus_runtime).get("error")
        with patch.dict(os.environ, {"FAULTDEBUG_RUNTIME_DIR": str(empty_runtime_dir)}):
            invalid_runtime_report = collect_doctor_report()
        invalid_runtime = next(item for item in invalid_runtime_report["checks"]
                               if item["name"] == "runtime-library")
        assert invalid_runtime["status"] == "FAIL"
        assert invalid_runtime["path"] == str(empty_runtime.resolve())

        baseline, instrumented = root / "baseline", root / "instrumented"
        _executable(baseline, 'test "$1" = workload')
        _executable(instrumented, 'test "$1" = workload')
        report = run_benchmark(baseline, instrumented, ["workload"], repeats=3,
                               warmups=1, cwd=root)
        assert report["schema"] == 2 and report["schema_name"] == BENCHMARK_SCHEMA_NAME
        assert report["status"] == "PASS"
        assert len(report["samples"]) == 6 and len(report["warmups"]) == 2
        rows = report["samples"] + report["warmups"]
        sample_ids = [item["sample_id"] for item in rows]
        assert len(sample_ids) == len(set(sample_ids))
        assert all(item["run_id"] == report["run_id"] for item in rows)
        assert [item["target"] for item in report["samples"]] == [
            "baseline", "instrumented", "instrumented", "baseline", "baseline", "instrumented"]
        assert all(item["status"] == "PASS" for item in report["samples"])
        summary = report["summary"]["targets"]["baseline"]
        assert {"p50", "p95", "p99"} <= set(summary["wall_time_ms"])
        assert report["metric_availability"]["throughput_ops_per_second"]["status"] == "NOT RUN"
        for metric_name in ("cpu_time_ms", "max_rss_bytes"):
            availability = report["metric_availability"][metric_name]["status"]
            assert availability in {"PASS", "NOT RUN"}
            for item in report["samples"]:
                metric = item["metrics"][metric_name]
                if availability == "PASS":
                    assert metric["status"] == "PASS" and metric["value"] is not None
                else:
                    assert metric["status"] == "NOT RUN"
        assert report["binaries"]["baseline"]["sha256"] == hashlib.sha256(baseline.read_bytes()).hexdigest()

        expected_line = "workload=case-7 checksum=991"
        summary_line = ('{"target":{"returncode":0,"signal":null,"wall_time_ms":2.5},'
                        '"collector":{"ok":true,"partial":false},'
                        '"trace":{"complete":true}}')
        output_body = f"printf '%s\\n' {expected_line!r}\nprintf '%s\\n' {summary_line!r}"
        _executable(baseline, output_body)
        _executable(instrumented, output_body)
        result_report = run_benchmark(baseline, instrumented, [], repeats=1, warmups=0,
                                      cwd=root, operations=10,
                                      expected_result_line=expected_line)
        assert result_report["status"] == "PASS"
        for item in result_report["samples"]:
            assert item["workload_result"]["status"] == "PASS", item["workload_result"]
            assert item["target_result"]["status"] == "PASS", item["target_result"]
            assert item["metrics"]["target_wall_time_ms"] == {"status": "PASS", "value": 2.5}
            assert item["metrics"]["target_throughput_ops_per_second"] == {"status": "PASS", "value": 4000.0}
        _executable(instrumented, "printf '%s\\n' workload=case-7\\ checksum=992; printf '%s\\n' " + repr(summary_line))
        mismatch_report = run_benchmark(baseline, instrumented, [], repeats=1, warmups=0,
                                        cwd=root, expected_result_line=expected_line)
        assert mismatch_report["status"] == "FAIL"
        assert mismatch_report["samples"][1]["workload_result"]["status"] == "FAIL"

        cli_output = root / "benchmark-report.json"
        cli = subprocess.run([sys.executable, "-m", "faultdebug.cli", "benchmark",
                              "--baseline", str(baseline), "--instrumented", str(instrumented),
                              "--repeats", "1", "--warmups", "0", "--output", str(cli_output),
                              "--", "workload"],
                             cwd=ROOT, check=True, capture_output=True, text=True)
        cli_payload = json.loads(cli.stdout)
        assert cli_payload["summary"]["targets"]["baseline"]["successful_runs"] == 1
        assert cli_payload["run_id"] and len(cli_payload["run_id"]) == 32
        assert cli_payload["report_path"] == str(cli_output.resolve())
        assert json.loads(cli_output.read_text()) == cli_payload
        assert not list(root.glob(".benchmark-report.json.*.tmp"))
        doctor_cli = subprocess.run([sys.executable, "-m", "faultdebug.cli", "doctor", "--json"],
                                    cwd=ROOT, check=False, capture_output=True, text=True)
        doctor_payload = json.loads(doctor_cli.stdout)
        assert doctor_cli.returncode == {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[doctor_payload["status"]]
        assert doctor_payload["schema_name"] == "faultdebug.doctor"

        _executable(baseline, 'printf abc > "$1/result"')
        artifact_base = root / "artifacts"
        stale_dir = artifact_base / "baseline" / "measurement-0001"
        stale_dir.mkdir(parents=True)
        stale_file = stale_dir / "stale.bin"
        stale_file.write_bytes(b"stale artifact bytes" * 100)
        write_artifact({"header": {"dropped_count": 999},
                        "threads": [{"dropped_count": 999}]}, stale_dir, 42)
        artifact_report = run_benchmark(baseline, instrumented, ["{artifact_dir}"],
                                        repeats=1, warmups=0, cwd=root,
                                        operations=100, artifact_dir=artifact_base)
        sample = artifact_report["samples"][0]
        assert sample["metrics"]["artifact_size_bytes"] == {"status": "PASS", "value": 3}
        assert sample["metrics"]["loss_count"]["status"] == "NOT RUN"
        assert sample["metrics"]["throughput_ops_per_second"]["status"] == "PASS"
        assert sample["artifact_directory"].startswith(str(artifact_base / artifact_report["run_id"]))
        assert stale_file.exists() and sample["artifact_directory"] != str(stale_dir)
        repeated_report = run_benchmark(baseline, instrumented, ["{artifact_dir}"],
                                        repeats=1, warmups=0, cwd=root,
                                        artifact_dir=artifact_base)
        repeated_sample = repeated_report["samples"][0]
        assert repeated_report["run_id"] != artifact_report["run_id"]
        assert repeated_sample["artifact_directory"] != sample["artifact_directory"]
        assert repeated_sample["metrics"]["artifact_size_bytes"] == {"status": "PASS", "value": 3}
        assert repeated_sample["metrics"]["loss_count"]["status"] == "NOT RUN"
        assert stale_file.exists()

        writer = (f'import os, sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom pathlib import Path\n'
                  'from faultdebug.artifact import write_artifact\n'
                  'write_artifact({"header": {"dropped_count": 3}, '
                  '"threads": [{"dropped_count": 4}]}, Path(sys.argv[1]), os.getpid())\n')
        _executable(baseline, "")
        baseline.write_text("#!/usr/bin/env python3\n" + writer, encoding="utf-8")
        baseline.chmod(0o755)
        instrumented.write_text("#!/usr/bin/env python3\n" + writer, encoding="utf-8")
        instrumented.chmod(0o755)
        loss_report = run_benchmark(baseline, instrumented, ["{artifact_dir}"],
                                    repeats=1, warmups=0, cwd=root,
                                    artifact_dir=artifact_base)
        assert all(item["metrics"]["loss_count"] == {"status": "PASS", "value": 7}
                   for item in loss_report["samples"])
        assert loss_report["run_id"] not in {artifact_report["run_id"], repeated_report["run_id"]}

        _executable(instrumented, "exit 7")
        failed = run_benchmark(baseline, instrumented, ["workload"], repeats=1,
                               warmups=0, cwd=root)
        assert failed["status"] == "FAIL"
        assert failed["summary"]["targets"]["instrumented"]["failed_runs"] == 1

    print("doctor-benchmark-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
