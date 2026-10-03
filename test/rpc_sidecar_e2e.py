#!/usr/bin/env python3
"""Launch the numeric RPC producer through faultdebug and decode its artifact."""
from __future__ import annotations

import argparse
import json
import pathlib
import signal
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.format import collect_file  # noqa: E402
from faultdebug.run import run_target  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    report = run_target([str(ns.binary)], artifact_dir=ns.output)
    checks: dict[str, object] = {}
    checks["target_fault"] = {
        "status": "PASS" if report.get("target", {}).get("signal") == signal.SIGSEGV else "FAIL",
        "signal": report.get("target", {}).get("signal"),
    }
    artifact_name = report.get("artifact")
    if not artifact_name:
        checks["artifact"] = {"status": "FAIL", "reason": "launcher did not write a fault artifact"}
    else:
        decoded = collect_file(pathlib.Path(artifact_name))
        rpc = decoded.get("rpc") or {}
        events = rpc.get("events", [])
        ids = [event.get("rpc_id") for event in events]
        starts = [event for event in events if event.get("flags", 0) & 1]
        ends = [event for event in events if event.get("flags", 0) & 2]
        checks["rpc_events"] = {
            "status": "PASS" if len(starts) == 1 and len(ends) == 1 and ids.count(0x7001) == 2 else "FAIL",
            "count": len(events), "rpc_ids": ids,
        }
        checks["crash_incomplete"] = {
            "status": "PASS" if not rpc.get("complete", True) and rpc.get("header", {}).get("flags", 0) & 2 else "FAIL",
            "flags": rpc.get("header", {}).get("flags", 0),
        }
    statuses = [value["status"] for value in checks.values() if isinstance(value, dict) and "status" in value]
    result = {"status": "FAIL" if "FAIL" in statuses else "PASS", "checks": checks,
              "artifact": artifact_name if artifact_name else None}
    (ns.output / "rpc-sidecar-e2e.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
