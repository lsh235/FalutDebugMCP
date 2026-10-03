#!/usr/bin/env python3
"""Focused checks for optional semantic RPC decoding and MCP evidence classes."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.rpc import RPCDecodeError, evidence_summary, process_relations, rpc_trace


def main() -> int:
    absent = rpc_trace({"header": {"status": 0}, "threads": []})
    assert absent["status"] == "unresolved"
    assert absent["observed"] == [] and absent["static_candidates"] == []
    report = {
        "header": {"status": 0, "abi_version": 1},
        "process": {"pid": 10},
        "rpc_events": [
            {"rpc_id": "r1", "phase": "send", "monotonic_ns": 10, "pid": 10, "method_id": 7},
            {"rpc_id": "r1", "phase": "end", "monotonic_ns": 30, "pid": 10, "method_id": 7},
        ],
        "static_candidates": [{"kind": "possible", "rpc_id": "r1"}],
    }
    decoded = rpc_trace(report)
    assert decoded["status"] == "complete"
    assert len(decoded["observed"]) == 2 and decoded["observed"][0]["phase"] == "send"
    assert decoded["observed"][0]["method_id"] == 7
    assert "method" not in decoded["observed"][0]
    assert len(decoded["static_candidates"]) == 1
    sidecar = rpc_trace({
        "header": {"status": 0, "abi_version": 1},
        "rpc": {"header": {"flags": 0, "dropped_count": 0}, "complete": True,
                 "events": [{"sequence": 0, "rpc_id": 4, "direction": 1,
                             "start_monotonic_ns": 3, "end_monotonic_ns": 4,
                             "flags": 1, "status": 0}]},
    })
    assert sidecar["status"] == "complete"
    assert sidecar["observed"][0]["phase"] == "begin"
    peer = {
        "header": {"status": 0, "abi_version": 1},
        "process": {"pid": 11},
        "rpc_events": [
            {"rpc_id": "r1", "phase": "receive", "monotonic_ns": 20, "pid": 11, "method_id": 7},
            {"rpc_id": "r1", "phase": "end", "monotonic_ns": 25, "pid": 11, "method_id": 7},
        ],
    }
    relations = process_relations([report, peer])
    assert len(relations["observed"]) == 1 and relations["observed"][0]["kind"] == "rpc"
    assert relations["observed"][0]["from_pid"] == 10
    assert relations["static_candidates"] == [{"kind": "possible", "rpc_id": "r1"}]
    ambiguous = process_relations([report, peer, {
        "header": {"status": 0, "abi_version": 1}, "process": {"pid": 12},
        "rpc_events": [{"rpc_id": "r1", "phase": "send", "monotonic_ns": 11, "pid": 12, "method_id": 7}],
    }])
    assert not any(item.get("kind") == "rpc" for item in ambiguous["observed"])
    assert any(item.get("reason") == "rpc_endpoint_pair_not_unique" for item in ambiguous["unresolved"])
    summary = evidence_summary([report, peer])
    assert summary["observed"]["rpc_events"] == 4
    try:
        rpc_trace({"header": {"abi_version": 1}, "rpc_trace": {"schema": 99, "events": []}})
    except RPCDecodeError:
        pass
    else:
        raise AssertionError("unsupported RPC schema was accepted")
    try:
        rpc_trace({"header": {"abi_version": 1}, "rpc_trace": {"schema": 1, "abi_version": 2, "events": []}})
    except RPCDecodeError:
        pass
    else:
        raise AssertionError("ABI mismatch was accepted")
    for sensitive in ({"method": "/private.Service/Call"}, {"metadata": {"trace": "secret"}}, {"payload": "body"}):
        try:
            rpc_trace({"header": {"abi_version": 1}, "rpc_events": [{"rpc_id": 1, "phase": "begin", "monotonic_ns": 1, **sensitive}]})
        except RPCDecodeError:
            pass
        else:
            raise AssertionError(f"sensitive field was accepted: {sensitive}")
    print("rpc-analysis-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
