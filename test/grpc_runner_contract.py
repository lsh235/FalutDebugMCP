#!/usr/bin/env python3
"""Preserve gRPC runner diagnostics when child output contains invalid UTF-8."""
from __future__ import annotations

import sys

from grpc_v09_scenarios import _run, _start, _stop


def main() -> int:
    command = [sys.executable, "-c",
               "import sys; print('stdout-ok'); sys.stderr.buffer.write(bytes([255]) + b'\\n')"]
    completed = _run(command)
    assert completed["returncode"] == 0, completed
    assert "stdout-ok" in completed["stdout"] and r"\xff" in completed["stderr"], completed

    process = _start(command)
    captured = _stop(process)
    assert captured["returncode"] == 0, captured
    assert "stdout-ok" in captured["stdout"] and r"\xff" in captured["stderr"], captured
    print("grpc-runner-log-contract-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
