"""Paired baseline/instrumented benchmark and versioned JSON report schema."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

BENCHMARK_SCHEMA = 2
BENCHMARK_SCHEMA_NAME = "faultdebug.benchmark"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; p50 is reported separately as the median."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * fraction + 0.999999) - 1))
    return ordered[index]


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [row for row in samples if row["status"] == "PASS"]
    values = [float(row["metrics"]["wall_time_ms"]["value"]) for row in successful]
    operations = [row["metrics"]["throughput_ops_per_second"]["value"]
                  for row in successful
                  if row["metrics"]["throughput_ops_per_second"]["status"] == "PASS"]
    cpu = [row["metrics"]["cpu_time_ms"]["value"] for row in successful
           if row["metrics"]["cpu_time_ms"]["status"] == "PASS"]
    rss = [row["metrics"]["max_rss_bytes"]["value"] for row in successful
           if row["metrics"]["max_rss_bytes"]["status"] == "PASS"]
    artifact_sizes = [row["metrics"]["artifact_size_bytes"]["value"] for row in successful
                      if row["metrics"]["artifact_size_bytes"]["status"] == "PASS"]
    losses = [row["metrics"]["loss_count"]["value"] for row in successful
              if row["metrics"]["loss_count"]["status"] == "PASS"]
    target_wall = [float(row["metrics"]["target_wall_time_ms"]["value"]) for row in successful
                   if row["metrics"]["target_wall_time_ms"]["status"] == "PASS"]
    target_throughput = [float(row["metrics"]["target_throughput_ops_per_second"]["value"])
                         for row in successful
                         if row["metrics"]["target_throughput_ops_per_second"]["status"] == "PASS"]
    return {
        "successful_runs": len(successful),
        "failed_runs": len(samples) - len(successful),
        "wall_time_ms": {"p50": statistics.median(values) if values else None,
                         "p95": _percentile(values, .95), "p99": _percentile(values, .99),
                         "min": min(values) if values else None,
                         "max": max(values) if values else None},
        "target_wall_time_ms": {"p50": statistics.median(target_wall) if target_wall else None,
                                "p95": _percentile(target_wall, .95),
                                "p99": _percentile(target_wall, .99),
                                "min": min(target_wall) if target_wall else None,
                                "max": max(target_wall) if target_wall else None},
        "target_throughput_ops_per_second": {
            "p50": statistics.median(target_throughput) if target_throughput else None,
            "p95": _percentile(target_throughput, .95),
            "p99": _percentile(target_throughput, .99)},
        "throughput_ops_per_second": {"p50": statistics.median(operations) if operations else None,
                                       "p95": _percentile(operations, .95),
                                       "p99": _percentile(operations, .99)},
        "cpu_time_ms": {"p50": statistics.median(cpu) if cpu else None,
                        "p95": _percentile(cpu, .95), "p99": _percentile(cpu, .99)},
        "max_rss_bytes": {"p50": statistics.median(rss) if rss else None,
                          "p95": _percentile(rss, .95), "p99": _percentile(rss, .99)},
        "artifact_size_bytes": {"p50": statistics.median(artifact_sizes) if artifact_sizes else None,
                                "p95": _percentile(artifact_sizes, .95),
                                "p99": _percentile(artifact_sizes, .99)},
        "loss_count": {"p50": statistics.median(losses) if losses else None,
                       "p95": _percentile(losses, .95), "p99": _percentile(losses, .99)},
    }


def _not_run(reason: str) -> dict[str, Any]:
    return {"status": "NOT RUN", "value": None, "reason": reason}


def _artifact_metrics(run_dir: Path | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if run_dir is None:
        reason = "pass --artifact-dir and use {artifact_dir} in command arguments"
        return _not_run(reason), _not_run(reason), _not_run(reason)
    size = sum(path.stat().st_size for path in run_dir.rglob("*") if path.is_file())
    try:
        from .format import collect_file
        artifact_files = sorted(run_dir.rglob("*.fault"))
        if not artifact_files:
            reason = "no .fault artifacts were created in this run"
            return ({"status": "PASS", "value": size}, _not_run(reason), _not_run(reason))
        lost = 0
        quality: list[dict[str, Any]] = []
        for path in artifact_files:
            report = collect_file(path)
            lost += int((report.get("header") or {}).get("dropped_count", 0))
            threads = report.get("threads", [])
            thread_dropped = sum(int(thread.get("dropped_count", 0)) for thread in threads)
            thread_events = sum(int(thread.get("event_count", 0)) for thread in threads)
            lost += thread_dropped
            rpc = report.get("rpc") or report.get("rpc_sidecar") or {}
            rpc_header = rpc.get("header") or {}
            rpc_dropped = int(rpc_header.get("dropped_count", 0))
            lost += rpc_dropped
            target = report.get("target") or {}
            collector = report.get("collector") or {}
            header = report.get("header") or {}
            quality.append({
                "artifact": path.name,
                "path": str(path.relative_to(run_dir)),
                "sha256": _sha256(path),
                "target_returncode": target.get("returncode"),
                "target_signal": target.get("signal"),
                "target_wall_time_ms": target.get("wall_time_ms"),
                "collector_ok": collector.get("ok"),
                "collector_partial": collector.get("partial"),
                "trace_complete": report.get("complete"),
                "status_flags": header.get("status"),
                "thread_event_count": thread_events,
                "thread_dropped_count": thread_dropped,
                "rpc_event_count": rpc_header.get("event_count"),
                "rpc_dropped_count": rpc_dropped if rpc_header else None,
                "rpc_flags": rpc_header.get("flags"),
            })
        return ({"status": "PASS", "value": size},
                {"status": "PASS", "value": lost},
                {"status": "PASS", "value": {"artifacts": quality}})
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return ({"status": "PASS", "value": size},
                _not_run(f"could not decode generated artifacts to count reported losses: {exc}"),
                _not_run(f"could not decode generated artifact quality: {exc}"))


def _runner_summary(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("target"), dict) and isinstance(value.get("collector"), dict):
            return value
    return None


def _run_one(label: str, binary: Path, args: Sequence[str], cwd: Path,
             timeout: float | None, phase: str, pair: int, *, operations: int | None,
             artifact_root: Path | None, time_binary: str | None,
             expected_result_line: str | None) -> dict[str, Any]:
    run_dir: Path | None = None
    run_args = list(args)
    if artifact_root is not None and any("{artifact_dir}" in arg for arg in run_args):
        run_dir = artifact_root / label / f"{phase}-{pair:04d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        run_args = [arg.replace("{artifact_dir}", str(run_dir)) for arg in run_args]
    command = [str(binary), *run_args]
    metrics_file: Path | None = None
    invocation = command
    if time_binary:
        handle = tempfile.NamedTemporaryFile(prefix="faultdebug-time-", delete=False)
        handle.close()
        metrics_file = Path(handle.name)
        invocation = [time_binary, "-f", "%U\\t%S\\t%M", "-o", str(metrics_file), "--", *command]
    start = time.perf_counter_ns()
    try:
        completed = subprocess.run(invocation, cwd=cwd,
                                   stdout=subprocess.PIPE if expected_result_line is not None else subprocess.DEVNULL,
                                   stderr=subprocess.PIPE if not time_binary else subprocess.DEVNULL,
                                   text=True, errors="replace", check=False, timeout=timeout)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        time_values: list[float] = []
        if metrics_file is not None:
            try:
                fields = metrics_file.read_text().strip().split()
                if len(fields) == 3:
                    time_values = [float(fields[0]), float(fields[1]), float(fields[2])]
            except (OSError, ValueError):
                pass
            finally:
                metrics_file.unlink(missing_ok=True)
        cpu_ms = (time_values[0] + time_values[1]) * 1000 if len(time_values) == 3 else None
        rss_bytes = int(time_values[2] * 1024) if len(time_values) == 3 else None
        throughput = operations / (elapsed_ms / 1000) if operations is not None and elapsed_ms > 0 else None
        artifact_size, loss_count, trace_quality = _artifact_metrics(run_dir)
        stdout = completed.stdout or ""
        runner = _runner_summary(stdout) if expected_result_line is not None else None
        target = (runner or {}).get("target") or {}
        collector = (runner or {}).get("collector") or {}
        target_wall_ms = target.get("wall_time_ms")
        target_wall_ms = float(target_wall_ms) if isinstance(target_wall_ms, (int, float)) else None
        target_wall_throughput = (operations / (target_wall_ms / 1000)
                                  if operations is not None and target_wall_ms and target_wall_ms > 0 else None)
        target_result = (_not_run("runner did not emit a target result summary") if not target else {
            "status": "PASS" if target.get("returncode") == 0 and target.get("signal") is None else "FAIL",
            "returncode": target.get("returncode"), "signal": target.get("signal"),
            "wall_time_ms": target_wall_ms,
        })
        collector_result = (_not_run("runner did not emit a collector result summary") if not collector else {
            "status": "PASS" if collector.get("ok") is True else "FAIL",
            "ok": collector.get("ok"), "partial": collector.get("partial"),
            "status_flags": (runner or {}).get("trace", {}).get("status_flags"),
            "trace_complete": (runner or {}).get("trace", {}).get("complete"),
        })
        if expected_result_line is None:
            workload_result = _not_run("--expected-result-line was not supplied")
        else:
            matching_lines = [line for line in stdout.splitlines() if line == expected_result_line]
            observed_workload_lines = [line for line in stdout.splitlines() if line.startswith("threads=")]
            workload_result = {
                "status": "PASS" if len(matching_lines) == 1 else "FAIL",
                "expected": expected_result_line,
                "matching_occurrences": len(matching_lines),
                "observed": observed_workload_lines[:4],
            }
        sample_status = "PASS" if completed.returncode == 0 else "FAIL"
        if workload_result["status"] == "FAIL" or target_result["status"] == "FAIL" or collector_result["status"] == "FAIL":
            sample_status = "FAIL"
        return {
            "target": label, "phase": phase, "pair": pair,
            "status": sample_status,
            "returncode": completed.returncode, "command": command,
            "artifact_directory": str(run_dir) if run_dir else None,
            "stderr_tail": completed.stderr[-500:] if time_binary is None and completed.returncode else "",
            "target_result": target_result,
            "collector_result": collector_result,
            "workload_result": workload_result,
            "metrics": {
                "wall_time_ms": {"status": "PASS", "value": round(elapsed_ms, 6)},
                "throughput_ops_per_second": ({"status": "PASS", "value": throughput}
                                                if throughput is not None else
                                                _not_run("--operations was not supplied")),
                "cpu_time_ms": ({"status": "PASS", "value": cpu_ms} if cpu_ms is not None
                                else _not_run("GNU /usr/bin/time metrics unavailable")),
                "max_rss_bytes": ({"status": "PASS", "value": rss_bytes} if rss_bytes is not None
                                  else _not_run("GNU /usr/bin/time metrics unavailable")),
                "target_wall_time_ms": ({"status": "PASS", "value": round(target_wall_ms, 6)}
                                         if target_wall_ms is not None else
                                         _not_run("runner target timing unavailable")),
                "target_throughput_ops_per_second": ({"status": "PASS", "value": target_wall_throughput}
                                                       if target_wall_throughput is not None else
                                                       _not_run("target timing or --operations unavailable")),
                "artifact_size_bytes": artifact_size, "loss_count": loss_count,
                "trace_quality": trace_quality,
            },
        }
    except subprocess.TimeoutExpired as exc:
        if metrics_file is not None:
            metrics_file.unlink(missing_ok=True)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        unavailable = _not_run("process did not complete")
        return {"target": label, "phase": phase, "pair": pair, "status": "FAIL",
                "returncode": None, "command": command, "error": f"timed out after {timeout}s",
                "wall_time_ms": round(elapsed_ms, 6), "metrics": {
                    "wall_time_ms": {"status": "PASS", "value": round(elapsed_ms, 6)},
                    "throughput_ops_per_second": unavailable, "cpu_time_ms": unavailable,
                    "max_rss_bytes": unavailable, "artifact_size_bytes": unavailable,
                    "target_wall_time_ms": unavailable,
                    "target_throughput_ops_per_second": unavailable,
                    "loss_count": unavailable, "trace_quality": unavailable},
                "target_result": unavailable, "collector_result": unavailable,
                "workload_result": unavailable}
    except OSError as exc:
        if metrics_file is not None:
            metrics_file.unlink(missing_ok=True)
        unavailable = _not_run("process did not start")
        return {"target": label, "phase": phase, "pair": pair, "status": "FAIL",
                "returncode": None, "command": command, "error": str(exc), "metrics": {
                    "wall_time_ms": unavailable, "throughput_ops_per_second": unavailable,
                    "cpu_time_ms": unavailable, "max_rss_bytes": unavailable,
                    "artifact_size_bytes": unavailable, "target_wall_time_ms": unavailable,
                    "target_throughput_ops_per_second": unavailable,
                    "loss_count": unavailable, "trace_quality": unavailable},
                "target_result": unavailable, "collector_result": unavailable,
                "workload_result": unavailable}


def run_benchmark(baseline: Path, instrumented: Path, args: Sequence[str], *,
                  repeats: int = 10, warmups: int = 2, timeout: float | None = None,
                  cwd: Path | None = None, operations: int | None = None,
                  artifact_dir: Path | None = None,
                  expected_result_line: str | None = None) -> dict[str, Any]:
    """Run identical workloads in paired alternating order and record explicit gaps."""
    if repeats < 1 or warmups < 0:
        raise ValueError("repeats must be positive and warmups must be nonnegative")
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive")
    if operations is not None and operations < 1:
        raise ValueError("operations must be positive")
    if expected_result_line is not None and (not expected_result_line or "\n" in expected_result_line or "\r" in expected_result_line):
        raise ValueError("expected_result_line must be one non-empty line")
    baseline = baseline.expanduser().resolve()
    instrumented = instrumented.expanduser().resolve()
    workdir = (cwd or Path.cwd()).expanduser().resolve()
    for label, binary in (("baseline", baseline), ("instrumented", instrumented)):
        if not binary.is_file():
            raise FileNotFoundError(f"{label} executable does not exist: {binary}")
        if not os.access(binary, os.X_OK):
            raise PermissionError(f"{label} executable is not executable: {binary}")
    if not workdir.is_dir():
        raise NotADirectoryError(workdir)
    run_id = uuid.uuid4().hex
    artifact_base = artifact_dir.expanduser().resolve() if artifact_dir else None
    artifact_requested = artifact_base is not None and any("{artifact_dir}" in arg for arg in args)
    artifact_root = artifact_base / run_id if artifact_requested and artifact_base else None
    if artifact_base:
        artifact_base.mkdir(parents=True, exist_ok=True)
        if artifact_root:
            artifact_root.mkdir(mode=0o700, exist_ok=False)

    binaries = {"baseline": baseline, "instrumented": instrumented}
    time_path = "/usr/bin/time"
    time_binary = time_path if Path(time_path).is_file() and os.access(time_path, os.X_OK) else None
    warmup_results: list[dict[str, Any]] = []
    for index in range(warmups):
        order = ("baseline", "instrumented") if index % 2 == 0 else ("instrumented", "baseline")
        for label in order:
            row = _run_one(label, binaries[label], args, workdir, timeout,
                           "warmup", index + 1, operations=operations,
                           artifact_root=artifact_root, time_binary=time_binary,
                           expected_result_line=expected_result_line)
            row["run_id"] = run_id
            row["sample_id"] = f"{run_id}:{label}:warmup:{index + 1:04d}"
            warmup_results.append(row)

    samples: list[dict[str, Any]] = []
    for pair in range(1, repeats + 1):
        order = ("baseline", "instrumented") if pair % 2 else ("instrumented", "baseline")
        for label in order:
            row = _run_one(label, binaries[label], args, workdir, timeout,
                           "measurement", pair, operations=operations,
                           artifact_root=artifact_root, time_binary=time_binary,
                           expected_result_line=expected_result_line)
            row["run_id"] = run_id
            row["sample_id"] = f"{run_id}:{label}:measurement:{pair:04d}"
            samples.append(row)

    per_target = {label: _summary([row for row in samples if row["target"] == label])
                  for label in binaries}
    base_p50 = per_target["baseline"]["wall_time_ms"]["p50"]
    instrumented_p50 = per_target["instrumented"]["wall_time_ms"]["p50"]
    ratio = (instrumented_p50 / base_p50
             if base_p50 and instrumented_p50 is not None else None)
    failed = any(row["status"] == "FAIL" for row in samples + warmup_results)
    target_wall_available = any(row["metrics"]["target_wall_time_ms"]["status"] == "PASS"
                                for row in samples)
    trace_quality_available = any(row["metrics"]["trace_quality"]["status"] == "PASS"
                                  for row in samples)
    artifact_metric_available = any(row["metrics"]["artifact_size_bytes"]["status"] == "PASS"
                                    for row in samples)
    loss_metric_available = any(row["metrics"]["loss_count"]["status"] == "PASS"
                                for row in samples)
    workload_result_available = expected_result_line is not None
    env_blob = "\0".join(f"{key}={value}" for key, value in sorted(os.environ.items())).encode()
    env_hash = hashlib.sha256(env_blob).hexdigest()
    return {
        "schema": BENCHMARK_SCHEMA, "schema_name": BENCHMARK_SCHEMA_NAME,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL" if failed else "PASS",
        "measurement": "paired_process_benchmark",
        "protocol": {"repeats": repeats, "warmups_per_target": warmups,
                     "order": "alternating; baseline first on odd pairs",
                     "timeout_seconds": timeout,
                     "stdout": "captured for exact workload-result matching" if expected_result_line is not None else "discarded",
                     "working_directory": str(workdir), "arguments": list(args),
                     "environment_sha256": env_hash,
                     "artifact_base_directory": str(artifact_base) if artifact_base else None,
                     "artifact_directory_template": str(artifact_root / "{target}/{phase}-{pair}")
                     if artifact_root else None,
                     "operations_per_invocation": operations,
                     "expected_result_line": expected_result_line},
        "host": {"platform": platform.platform(), "machine": platform.machine(),
                 "python": sys.version.split()[0], "logical_cpu_count": os.cpu_count()},
        "binaries": {label: {"path": str(path), "sha256": _sha256(path)}
                     for label, path in binaries.items()},
        "metric_availability": {
            "wall_time_ms": {"status": "PASS", "method": "perf_counter_ns around process invocation"},
            "throughput_ops_per_second": ({"status": "PASS", "method": "operations divided by process invocation wall time"}
                                           if operations is not None else _not_run("--operations was not supplied")),
            "target_wall_time_ms": ({"status": "PASS", "method": "target lifetime measured by the launcher"}
                                    if target_wall_available else _not_run("runner target timing unavailable")),
            "target_throughput_ops_per_second": ({"status": "PASS", "method": "operations divided by target lifetime"}
                                                  if operations is not None and target_wall_available else
                                                  _not_run("target timing or --operations unavailable")),
            "cpu_time_ms": ({"status": "PASS", "method": "GNU /usr/bin/time user plus system CPU time"}
                            if time_binary else _not_run("GNU /usr/bin/time unavailable")),
            "max_rss_bytes": ({"status": "PASS", "method": "GNU /usr/bin/time peak RSS"}
                               if time_binary else _not_run("GNU /usr/bin/time unavailable")),
            "artifact_size_bytes": ({"status": "PASS", "method": "sum of files in isolated per-run artifact directory"}
                                    if artifact_metric_available else
                                    _not_run("--artifact-dir and {artifact_dir} argument placeholder required")),
            "loss_count": ({"status": "PASS", "method": "sum of decoded dropped_count fields in generated .fault files"}
                           if loss_metric_available else
                           _not_run("--artifact-dir and {artifact_dir} argument placeholder required")),
            "trace_quality": ({"status": "PASS", "method": "decoded per-run artifact status and loss fields"}
                              if trace_quality_available else _not_run("decoded .fault artifact unavailable")),
            "workload_result": ({"status": "PASS", "method": "exact target output line matched for every run"}
                                if workload_result_available else _not_run("--expected-result-line was not supplied")),
        },
        "warmups": warmup_results, "samples": samples,
        "summary": {"targets": per_target,
                    "instrumented_to_baseline_wall_time_p50_ratio": ratio,
                    "interpretation": "descriptive for this workload and host only"},
        "limitations": [
            "PASS means commands and any supplied exact workload-result contract passed; it does not establish workload representativeness",
            "wall_time_ms and throughput_ops_per_second cover the outer process invocation, including launcher and collection",
            "target_wall_time_ms and target_throughput_ops_per_second come from the launcher target lifetime when its summary is available",
            "loss_count only includes dropped_count fields exposed by decoded .fault artifacts",
            "environment values are inherited and represented by a SHA-256 fingerprint, not serialized",
            "host contention, thermal state, and frequency scaling can affect measurements",
        ],
    }


def benchmark_json(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2)


def write_benchmark_report(path: Path, report: dict[str, Any]) -> Path:
    """Atomically replace the requested report path and record its destination."""
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(destination)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{destination.name}.", suffix=".tmp",
            dir=destination.parent, delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(benchmark_json(report))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Atomic replace is already complete; some filesystems do not
            # support syncing directories.
            pass
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination
