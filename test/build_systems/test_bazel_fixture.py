#!/usr/bin/env python3
"""Build the Bazel adoption fixture and verify selective object instrumentation."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "bazel"


def main() -> int:
    bazel = shutil.which("bazel") or shutil.which("bazelisk")
    if not bazel:
        print(json.dumps({"status": "NOT RUN", "reason": "Bazel/Bazelisk is unavailable"}))
        return 0
    with tempfile.TemporaryDirectory(prefix="faultdebug-bazel-fixture-") as raw:
        temp = Path(raw)
        prefix = temp / "links" / "bazel-"
        run = subprocess.run(
            [bazel, "--batch", f"--output_base={temp / 'output-base'}", "build", "--lockfile_mode=off",
             f"--symlink_prefix={prefix}", "//:instrumented_object", "//:excluded_object"],
            cwd=FIXTURE, text=True, capture_output=True, timeout=180)
        if run.returncode:
            print(json.dumps({"status": "FAIL", "reason": "Bazel build failed",
                              "stderr": run.stderr[-4000:]}, indent=2))
            return 1
        outputs = Path(f"{prefix}bin")
        nm = shutil.which("nm")
        if not nm:
            print(json.dumps({"status": "NOT RUN", "reason": "nm is unavailable",
                              "bazel_status": "PASS"}, indent=2))
            return 0

        def undefined_symbols(name: str) -> set[str]:
            result = subprocess.run([nm, "-u", str(outputs / name)],
                                    text=True, capture_output=True, timeout=10)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return {line.split()[-1] for line in result.stdout.splitlines() if line.split()}

        instrumented = undefined_symbols("instrumented.o")
        excluded = undefined_symbols("excluded.o")
        checks = {
            "allowlisted source references instrumentation hooks":
                {"__cyg_profile_func_enter", "__cyg_profile_func_exit"} <= instrumented,
            "excluded source has no instrumentation hooks":
                not ({"__cyg_profile_func_enter", "__cyg_profile_func_exit"} & excluded),
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        print(json.dumps({"status": status, "checks": checks,
                          "bazel_stdout": run.stdout[-2000:]}, indent=2))
        return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
