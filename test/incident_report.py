#!/usr/bin/env python3
"""Focused checks for the read-only v0.6 incident report surface."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.rpc import incident_report


def main() -> int:
    sender = {
        "header": {"status": 0, "abi_version": 1},
        "process": {"pid": 10},
        "target": {"returncode": 0},
        "collector": {"ok": True, "status": "complete"},
        "rpc_events": [{
            "rpc_id": "r1", "phase": "send", "monotonic_ns": 10,
            "pid": 10, "method_id": 7, "status": "OK",
            "deadline_ns": 100, "retry_count": 1, "stream": "unary",
        }],
        "static_candidates": [{"kind": "possible", "rpc_id": "r1"}],
    }
    receiver = {
        "header": {"status": 0, "abi_version": 1},
        "process": {"pid": 11},
        "target": {"returncode": 0},
        "collector": {"ok": True, "status": "complete"},
        "rpc_events": [{
            "rpc_id": "r1", "phase": "receive", "monotonic_ns": 20,
            "pid": 11, "method_id": 7, "status": "OK",
            "streaming": False, "attempt": 1,
        }],
    }
    result = incident_report([sender, receiver])
    assert result["schema"] == 1
    assert result["status"] == "limited"
    assert len(result["observed"]["rpc_events"]) == 2
    assert len(result["observed"]["process_relations"]) == 1
    assert result["static_candidates"] == [{"kind": "possible", "rpc_id": "r1"}]
    assert any(item.get("scope") == "process_relations" for item in result["unresolved"])
    assert {row["status"] for row in result["fields"]["status"]} == {"OK"}
    assert result["fields"]["deadlines"] == [{
        "artifact_index": 0, "rpc_id": "r1", "deadline_ns": 100,
    }]
    assert {row.get("retry_count", row.get("attempt")) for row in result["fields"]["retries"]} == {1}
    assert {row.get("stream", row.get("streaming")) for row in result["fields"]["streams"]} == {"unary", False}

    absent = incident_report([{
        "header": {"status": 0, "abi_version": 1},
        "process": {"pid": 12},
        "rpc_events": [{"rpc_id": "r2", "phase": "send", "monotonic_ns": 1}],
    }])
    assert absent["fields"] == {"status": [], "deadlines": [], "retries": [], "streams": []}
    assert absent["status"] == "limited"
    assert any(item.get("scope") == "process_relations" for item in absent["unresolved"])

    print("incident-report-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
