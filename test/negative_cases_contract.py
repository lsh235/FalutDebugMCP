#!/usr/bin/env python3
"""Regression checks for independent, isolated malformed-artifact cases."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

NEGATIVE_CASES = Path(__file__).with_name("negative_cases.py")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fd-negative-contract-") as temp:
        root = Path(temp)
        artifacts = root / "artifacts"
        artifacts.mkdir()
        fixture = {
            "header": {"status": 2},
            "modules": [{"text_start": 4096, "text_end": 8192}],
            "threads": [{"tid": 1, "generation": 1, "events": [
                {"sequence": 1, "type": 1, "generation": 1, "function": 4100},
                {"sequence": 2, "type": 2, "generation": 1, "function": 4100},
            ]}],
            "crashes": [{"signal": 11, "pc": 4104}],
        }
        (artifacts / "fault-valid.json").write_text(json.dumps(fixture), encoding="utf-8")
        run = subprocess.run([sys.executable, str(NEGATIVE_CASES), str(artifacts)],
                             capture_output=True, text=True, check=False)
        report = json.loads(run.stdout)
        assert run.returncode == 0 and report["status"] == "PASS", report
        assert report["normal_control"]["status"] == "PASS", report
        assert {case["name"] for case in report["cases"]} == {
            "bad_signal", "bad_pc", "bad_generation", "truncated"}
        assert all(case["status"] == "PASS" for case in report["cases"]), report

        empty = root / "empty"
        empty.mkdir()
        missing = subprocess.run([sys.executable, str(NEGATIVE_CASES), str(empty)],
                                 capture_output=True, text=True, check=False)
        missing_report = json.loads(missing.stdout)
        assert missing.returncode == 2 and missing_report["status"] == "NOT RUN"

    print("negative-cases-contract-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
