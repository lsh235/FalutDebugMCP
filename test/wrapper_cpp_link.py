#!/usr/bin/env python3
"""Verify the explicit C++ wrapper on a source compile and object-only link."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=pathlib.Path,
                        default=(pathlib.Path(os.environ["FAULTDEBUG_RUNTIME_DIR"])
                                 if os.environ.get("FAULTDEBUG_RUNTIME_DIR") else None))
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    if ns.runtime_dir is None:
        report = {"status": "NOT RUN", "reason": "FAULTDEBUG_RUNTIME_DIR or --runtime-dir is required"}
        ns.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))
        return 0
    if not (ns.runtime_dir / "libfaultdebug_runtime.so").is_file():
        report = {"status": "NOT RUN", "reason": "libfaultdebug_runtime.so is unavailable"}
        ns.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))
        return 0
    wrapper = ROOT / "scripts" / "faultdebug-cc"
    real_cxx = os.environ.get("FAULTDEBUG_REAL_CXX", shutil.which("c++") or "c++")
    env = dict(os.environ)
    env["FAULTDEBUG_REAL_CXX"] = real_cxx
    env["FAULTDEBUG_LINK_DRIVER"] = real_cxx
    env["FAULTDEBUG_RUNTIME_DIR"] = str(ns.runtime_dir.resolve())
    with tempfile.TemporaryDirectory(prefix="faultdebug-cxx-link-") as raw:
        work = pathlib.Path(raw)
        source = work / "object_only.cpp"
        object_file = work / "object_only.o"
        binary = work / "object_only"
        source.write_text("#include <iostream>\nint main() { std::cout << 42 << '\\n'; }\n")
        compile_run = subprocess.run([str(wrapper), "-std=c++17", "-c", str(source), "-o", str(object_file)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
        link_run = subprocess.run([str(wrapper), str(object_file), "-o", str(binary)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30) if compile_run.returncode == 0 else None
        execute_run = subprocess.run([str(binary)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30) if link_run and link_run.returncode == 0 else None
    checks = {
        "compile": {"status": "PASS" if compile_run.returncode == 0 else "FAIL", "returncode": compile_run.returncode, "stderr": compile_run.stderr[-2000:]},
        "object_only_cxx_link": {"status": "PASS" if link_run and link_run.returncode == 0 else "FAIL", "returncode": link_run.returncode if link_run else None, "stderr": link_run.stderr[-2000:] if link_run else "compile failed"},
        "execute": {"status": "PASS" if execute_run and execute_run.returncode == 0 and execute_run.stdout.strip() == "42" else "FAIL", "returncode": execute_run.returncode if execute_run else None, "stdout": execute_run.stdout if execute_run else ""},
    }
    status = "FAIL" if any(item["status"] == "FAIL" for item in checks.values()) else "PASS"
    report = {"status": status, "wrapper": str(wrapper), "checks": checks}
    ns.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
