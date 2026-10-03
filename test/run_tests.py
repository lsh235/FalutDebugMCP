#!/usr/bin/env python3
"""Black-box fixture runner.

The launcher and collector are deliberately injected with FD_LAUNCHER and
FD_COLLECTOR. This runner owns fixture expectations and never treats an
artifact's mere existence as a passing trace.
"""
from __future__ import annotations
import argparse, json, os, pathlib, re, shlex, signal, subprocess, sys, time, resource, shutil

ROOT = pathlib.Path(__file__).resolve().parent
SOURCE_ROOT = ROOT.parent
EXPECTED = {"segv": signal.SIGSEGV, "bus": signal.SIGBUS, "ill": signal.SIGILL,
            "fpe": signal.SIGFPE, "abrt": signal.SIGABRT}
SOAK_SAMPLE = re.compile(
    r"^soak sample elapsed_s=(\d+) rss_current_kb=(\d+) rss_peak_kb=(\d+) "
    r"fd_count=(\d+) recorder_mapping_bytes=(\d+)$")

def run(cmd, *, cwd=None, timeout=60, env=None):
    try:
        def child_limits():
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout, preexec_fn=child_limits)
        return p.returncode, p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    except subprocess.TimeoutExpired as e:
        return None, (e.stdout or b"").decode(errors="replace"), "timeout"

def status(ok, reason):
    return {"status": "PASS" if ok else "FAIL", "reason": reason}

def status_exit_code(value):
    return {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[value]

def parse_soak_samples(stderr):
    samples = []
    for line in stderr.splitlines():
        match = SOAK_SAMPLE.fullmatch(line.strip())
        if match:
            elapsed, current_rss, peak_rss, fd_count, mapping = map(int, match.groups())
            samples.append({"elapsed_seconds": elapsed, "rss_current_kb": current_rss,
                            "rss_peak_kb": peak_rss, "fd_count": fd_count,
                            "recorder_mapping_bytes": mapping})
    return samples

def validate_soak_samples(samples, recorder_budget_bytes):
    elapsed = [row["elapsed_seconds"] for row in samples]
    values_valid = all(row["rss_current_kb"] >= 0 and row["rss_peak_kb"] >= 0
                       and row["fd_count"] >= 0 and row["recorder_mapping_bytes"] > 0
                       for row in samples)
    ordered = all(right > left for left, right in zip(elapsed, elapsed[1:]))
    gaps = [right - left for left, right in zip(elapsed, elapsed[1:])]
    mapping_sizes = sorted({row["recorder_mapping_bytes"] for row in samples})
    ok = (len(samples) >= 29 and values_valid and ordered and bool(elapsed)
          and elapsed[0] <= 61 and elapsed[-1] >= 1800 and (not gaps or max(gaps) <= 61)
          and len(mapping_sizes) == 1 and mapping_sizes[0] <= recorder_budget_bytes)
    rss = [row["rss_current_kb"] for row in samples]
    fds = [row["fd_count"] for row in samples]
    return {"status": "PASS" if ok else "FAIL", "sample_count": len(samples),
            "first_elapsed_seconds": elapsed[0] if elapsed else None,
            "last_elapsed_seconds": elapsed[-1] if elapsed else None,
            "max_sample_gap_seconds": max(gaps) if gaps else None,
            "current_rss_kb_min": min(rss) if rss else None,
            "current_rss_kb_max": max(rss) if rss else None,
            "peak_rss_kb_max": max((row["rss_peak_kb"] for row in samples), default=None),
            "fd_count_min": min(fds) if fds else None,
            "fd_count_max": max(fds) if fds else None,
            "recorder_mapping_bytes": mapping_sizes[0] if len(mapping_sizes) == 1 else mapping_sizes,
            "recorder_budget_bytes": recorder_budget_bytes,
            "samples": samples,
            "note": "RSS and FD ranges are recorded observations; no leak-growth threshold was predeclared."}

def simultaneous_termination_mode(target, process_returncode):
    """Accept direct SIGSEGV or the runtime's crash-recorded shell-style exit."""
    if not isinstance(target, dict):
        return None
    try:
        target_returncode = int(target.get("returncode"))
        target_signal = target.get("signal")
        if target_signal is not None:
            if (int(target_signal) == signal.SIGSEGV
                    and process_returncode in (-signal.SIGSEGV, signal.SIGSEGV,
                                               128 + signal.SIGSEGV)):
                return "signal_return"
            return None
        if (target_returncode == 128 + signal.SIGSEGV
                and process_returncode == 128 + signal.SIGSEGV):
            return "shell_style_return"
    except (TypeError, ValueError):
        return None
    return None

def fixture_cmd(launcher, exe, args, artifact_dir):
    return launcher + ["run", "--artifact-dir", str(artifact_dir), "--", str(exe), *map(str, args)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=("smoke", "acceptance", "soak"), default="smoke")
    ap.add_argument("--output", type=pathlib.Path, required=True)
    ap.add_argument("--build", type=pathlib.Path, default=None)
    ns = ap.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    build = ns.build or ns.output / "build"
    report = {"suite": ns.suite, "started": time.time(), "checks": [], "limits": {
        "max_threads": 64, "events_per_thread": 4096, "recorder_budget_bytes": 32 * 1024 * 1024}}
    # Build is a required gate. Generated build files stay under the run output.
    clang = SOURCE_ROOT / ".tools" / "clang" / "usr" / "bin"
    configure = ["cmake", "-S", str(SOURCE_ROOT), "-B", str(build), "-G", "Ninja",
                 "-DFAULTDEBUG_BUILD_TESTS=ON",
                 f"-DFAULTDEBUG_PYTHON_EXECUTABLE={sys.executable}"]
    if (clang / "clang-18").exists():
        configure += [f"-DCMAKE_C_COMPILER={clang / 'clang-18'}", f"-DCMAKE_CXX_COMPILER={clang / 'clang++-18'}"]
    rc, out, err = run(configure, timeout=120)
    report["cmake_configure"] = {"returncode": rc, "stderr": err[-4000:]}
    if rc == 0:
        rc, out, err = run(["cmake", "--build", str(build), "-j2"], timeout=180)
    report["build"] = {"returncode": rc, "stderr": err[-4000:]}
    launcher_text = os.environ.get("FD_LAUNCHER", "")
    if launcher_text:
        launcher = shlex.split(launcher_text)
    else:
        candidates = [SOURCE_ROOT / ".venv" / "bin" / "faultdebug", SOURCE_ROOT / ".venv" / "bin" / "fault-debug"]
        found = next((str(p) for p in candidates if p.exists()), shutil.which("faultdebug") or shutil.which("fault-debug"))
        launcher = [found] if found else []
    if rc != 0:
        report["checks"].append(status(False, "build failed"))
    elif not launcher:
        report["checks"].append({"status": "NOT RUN", "reason": "FD_LAUNCHER is unset"})
    else:
        def check(name, exe, args=(), expected=0, timeout=60):
            cmd = fixture_cmd(launcher, build / "test" / exe, args, ns.output)
            started = time.time(); r, so, se = run(cmd, timeout=timeout)
            observed = r
            target = {}
            line = {}
            parse_error = None
            try:
                line = json.loads(so.strip().splitlines()[-1])
                if not isinstance(line, dict):
                    raise TypeError("launcher output is not a JSON object")
                target = line.get("target", {})
                target_signal = target.get("signal")
                observed = -int(target_signal) if target_signal else int(target.get("returncode", r))
            except (ValueError, json.JSONDecodeError, IndexError, TypeError, AttributeError) as exc:
                line = {}
                parse_error = str(exc)
            collector = line.get("collector")
            collector_ok = isinstance(collector, dict) and collector.get("ok") is True
            expected_process = (r in (expected, -expected, 128 + -expected)
                                if expected < 0 else r == expected)
            nested_mode = None
            if name == "simultaneous_fatal":
                nested_mode = simultaneous_termination_mode(target, r)
                ok = collector_ok and expected_process and nested_mode is not None
                try:
                    artifact = pathlib.Path(line["artifact"])
                    raw = artifact.read_bytes(); payload = json.loads(raw[52:])
                    crashes = payload.get("crashes", [])
                    # First-crash-wins is valid when the second thread is
                    # terminated before the handler can re-enter. Preserve
                    # strict first-crash metadata checks; nested is optional.
                    first = crashes[0] if crashes else {}
                    nested_observed = any(int(c.get("flags", 0)) & 16 for c in crashes)
                    ok = (ok and bool(crashes)
                          and int(first.get("signal", 0)) == signal.SIGSEGV
                          and int(first.get("si_code", 0)) > 0
                          and int(first.get("pc", 0)) != 0)
                    rec_reason = "nested observed" if nested_observed else "first-crash-wins; nested not observed before termination"
                except (KeyError, OSError, ValueError, json.JSONDecodeError, IndexError, TypeError):
                    ok = False
                    nested_observed = False
                    rec_reason = "missing crash metadata"
            else:
                ok = collector_ok and expected_process and observed == expected
                if name == "normal_no_fault_artifact":
                    ok = ok and not line.get("artifact")
            reason = ((rec_reason if name == "simultaneous_fatal" else "target status and collector matched")
                      if ok else f"target={observed}, process={r}, expected={expected}, collector_ok={collector_ok}, parse_error={parse_error}")
            rec = status(ok, reason)
            rec.update({"name": name, "command": cmd, "target": line.get("target"),
                        "collector": collector, "stdout": so[-2000:],
                        "stderr": se[-4000:], "seconds": time.time()-started})
            if name.startswith("complex") and not name.endswith("fault"):
                oracle = subprocess.run([sys.executable, str(ROOT / "complex_oracle.py")], input=so, text=True, capture_output=True)
                rec["independent_marker_oracle"] = "PASS" if oracle.returncode == 0 else "FAIL"
                ok = ok and oracle.returncode == 0
                rec["status"] = "PASS" if ok else "FAIL"
            if nested_mode: rec["nested_termination_mode"] = nested_mode
            if name == "simultaneous_fatal": rec["nested_observed"] = nested_observed
            report["checks"].append(rec)
        check("c_chain_normal", "fd_c_chain", [16])
        check("cpp_chain_normal", "fd_cpp_chain", [8])
        check("normal_no_fault_artifact", "fd_c_chain", [16])
        check("c_chain_completed_then_fault", "fd_c_chain", [16, "fault"], -signal.SIGILL)
        check("complex_normal", "fd_complex")
        check("complex_fault", "fd_complex", ["fault"], -signal.SIGILL)
        if ns.suite in ("acceptance", "soak"):
            for label, num in (("segv",11),("bus",7),("ill",4),("fpe",8),("abrt",6)):
                repetitions = 100 if ns.suite == "acceptance" else 1
                for i in range(repetitions):
                    check(f"fatal_{label}_{i+1}", "fd_signals", [num], -EXPECTED[label])
            check("recursion_32", "fd_recursion", [32])
            check("threads_8", "fd_threads", [8])
            check("thread_slot_reuse_80", "fd_slot_reuse", [80])
            check("wrap_4200", "fd_wrap", [4200])
            check("pie_startup_module", "fd_pie_dso")
            check("branch_left", "fd_branch", [1])
            check("branch_right", "fd_branch", [2])
            check("cpp_exception", "fd_exceptions", [1])
            check("simultaneous_fatal", "fd_simultaneous", [], -signal.SIGSEGV)
            check("stack_exhaustion", "fd_stack_exhaust", [], -signal.SIGSEGV, timeout=30)
        if ns.suite == "soak":
            # One long-lived process is required to expose per-process leaks.
            started=time.monotonic()
            cmd=fixture_cmd(launcher, build / "test" / "fd_soak", [1800], ns.output)
            r,so,se=run(cmd, timeout=1865)
            elapsed=time.monotonic()-started
            line = {}
            target = {}
            collector = None
            observed = r
            collector_ok = False
            try:
                line = json.loads(so.strip().splitlines()[-1])
                if not isinstance(line, dict):
                    raise TypeError("launcher output is not a JSON object")
                target = line.get("target", {})
                observed = -int(target["signal"]) if target.get("signal") else int(target.get("returncode", r))
                collector = line.get("collector")
                collector_ok = isinstance(collector, dict) and collector.get("ok") is True
            except (ValueError, json.JSONDecodeError, IndexError, TypeError, AttributeError):
                observed, collector_ok = r, False
            ok = (collector_ok and observed == -signal.SIGSEGV
                  and r in (-signal.SIGSEGV, signal.SIGSEGV, 128 + signal.SIGSEGV)
                  and elapsed >= 1800)
            samples = parse_soak_samples(se)
            telemetry = validate_soak_samples(samples, report["limits"]["recorder_budget_bytes"])
            report["checks"].append({**status(ok, "long-lived soak reached 1800s and faulted"
                                               if ok else f"elapsed={elapsed:.3f}, returncode={r}"),
                                     "name": "long_lived_soak", "command": cmd,
                                     "elapsed": elapsed, "process_returncode": r,
                                     "target": target, "collector": collector,
                                     "artifact": line.get("artifact"), "trace": line.get("trace"),
                                     "stdout": so[-2000:], "stderr": se[-4000:]})
            report["checks"].append({"name": "soak_resource_telemetry", "status": telemetry["status"],
                                     "reason": "periodic RSS/FD samples and recorder mapping fit the declared budget"
                                     if telemetry["status"] == "PASS" else "resource telemetry was incomplete or outside its declared contract",
                                     "telemetry": telemetry})
            report["soak_elapsed_seconds"] = elapsed
    if launcher:
        negative = subprocess.run([sys.executable, str(ROOT / "negative_cases.py"), str(ns.output)],
                                  capture_output=True, text=True, timeout=120, check=False)
        try:
            negative_report = json.loads(negative.stdout)
        except json.JSONDecodeError:
            negative_report = {"status": "FAIL", "reason": "negative-case runner emitted non-JSON output"}
        negative_status = negative_report.get("status")
        if negative.returncode == 0 and negative_status == "PASS":
            negative_status = "PASS"
        elif negative.returncode == 2 and negative_status == "NOT RUN":
            negative_status = "NOT RUN"
        else:
            negative_status = "FAIL"
        report["checks"].append({"name": "negative_cases", "status": negative_status,
                                 "report": negative_report, "stdout": negative.stdout[-4000:],
                                 "stderr": negative.stderr[-4000:], "returncode": negative.returncode})
        oracle = shlex.split(os.environ.get("FD_ORACLE", "")) or [sys.executable, str(ROOT / "oracle.py")]
        r, so, se = run(oracle + [str(ns.output)], timeout=300)
        report["fidelity_oracle"] = {"status": "PASS" if r == 0 else "FAIL", "returncode": r, "stdout": so[-4000:], "stderr": se[-4000:]}
        if r != 0:
            report["checks"].append(status(False, "independent trace oracle failed"))
    else:
        report["checks"].append({"name": "negative_cases", "status": "NOT RUN",
                                 "reason": "launcher unavailable; no real artifact was collected"})
        report["fidelity_oracle"] = {"status": "NOT RUN", "reason": "FD_ORACLE is unset; child exit status is not trace fidelity evidence"}
        report["checks"].append({"status": "NOT RUN", "reason": "independent trace oracle unavailable"})
    report["finished"] = time.time()
    report["summary"] = {s: sum(1 for c in report["checks"] if c.get("status") == s)
                          for s in ("PASS", "FAIL", "NOT RUN")}
    states = [check.get("status") for check in report["checks"]]
    if report["fidelity_oracle"]["status"] not in states:
        states.append(report["fidelity_oracle"]["status"])
    report["status"] = ("FAIL" if "FAIL" in states else
                        "NOT RUN" if "NOT RUN" in states else "PASS")
    (ns.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], **report["summary"]}, sort_keys=True))
    return status_exit_code(report["status"])

if __name__ == "__main__":
    raise SystemExit(main())
