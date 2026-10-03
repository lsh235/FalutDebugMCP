#!/usr/bin/env python3
"""Contract tests for parsing and validating long-soak resource samples."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_tests import (parse_soak_samples, simultaneous_termination_mode,
                       validate_soak_samples)  # noqa: E402


def main() -> int:
    lines = [f"soak sample elapsed_s={second} rss_current_kb={1000 + second} "
             f"rss_peak_kb={1200 + second} fd_count=5 recorder_mapping_bytes=12000000"
             for second in range(60, 1801, 60)]
    samples = parse_soak_samples("noise\n" + "\n".join(lines) + "\nsoak end elapsed=1800\n")
    valid = validate_soak_samples(samples, 32 * 1024 * 1024)
    assert valid["status"] == "PASS" and valid["sample_count"] == 30, valid
    assert valid["fd_count_min"] == valid["fd_count_max"] == 5
    missing = validate_soak_samples(samples[:-2], 32 * 1024 * 1024)
    assert missing["status"] == "FAIL" and missing["last_elapsed_seconds"] == 1680
    over_budget = [dict(row, recorder_mapping_bytes=40 * 1024 * 1024) for row in samples]
    assert validate_soak_samples(over_budget, 32 * 1024 * 1024)["status"] == "FAIL"
    assert simultaneous_termination_mode({"returncode": -11, "signal": 11}, -11) == "signal_return"
    assert simultaneous_termination_mode({"returncode": 139, "signal": None}, 139) == "shell_style_return"
    assert simultaneous_termination_mode({"returncode": 0, "signal": None}, 0) is None
    assert simultaneous_termination_mode({"returncode": 139, "signal": None}, -11) is None
    print("PASS: soak RSS/FD and recorder-budget telemetry contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
