#!/usr/bin/env python3
"""Focused v0.7 session manifest and participant checks."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.session import SessionDecodeError, process_participants, session_manifest


def _report(pid: int, participant: str, phase: str, direction: int) -> dict:
    return {
        "header": {"status": 0, "abi_version": 1},
        "session": {"schema": 1, "session_id": "s-1", "participant_id": participant,
                     "expected_participants": ["frontend", "backend"]},
        "process": {"pid": pid, "parent_pid": 1, "executable": f"/bin/{participant}",
                     "start_monotonic_ns": pid},
        "target": {"returncode": 0}, "collector": {"ok": True, "status": "complete"},
        "rpc_events": [{"rpc_id": "r1", "phase": phase, "direction": direction,
                         "monotonic_ns": pid, "pid": pid, "method_id": 7}],
        "static_candidates": [{"kind": "possible", "rpc_id": "r1"}] if participant == "frontend" else [],
    }


def main() -> int:
    reports = [_report(10, "frontend", "send", 2), _report(11, "backend", "receive", 1)]
    manifest = session_manifest(reports, artifact_refs=["front.fault", "back.fault"])
    assert manifest["schema"] == 1
    assert manifest["session"]["identity_source"] == "session.session_id"
    assert manifest["session"]["expected_participants"] == ["frontend", "backend"]
    assert [row["participant_id"] for row in manifest["participants"]] == ["frontend", "backend"]
    assert len(manifest["observed"]["rpc_events"]) == 2
    assert len(manifest["derived"]["process_relations"]) == 1
    assert "process_relations" not in manifest["observed"]
    assert manifest["static_candidates"] == [{"kind": "possible", "rpc_id": "r1"}]
    assert not any(row.get("reason") == "expected_participants_missing" for row in manifest["unresolved"])

    legacy = session_manifest([{
        "header": {"status": 0, "abi_version": 1},
        "context": {"trace_id": "legacy-t"},
        "process": {"pid": 20}, "rpc_events": [],
    }])
    assert legacy["session"]["identity_source"] == "context.trace_id"
    assert legacy["session"]["compatibility"] == "legacy_context"

    participants = process_participants(reports, artifact_refs=["front.fault", "back.fault"])
    assert len(participants["participants"]) == 2
    assert all("target" in row and "collector" in row for row in participants["participants"])

    runtime_reports = [{
        "header": {"status": 0, "abi_version": 1},
        "session": {"schema": 1, "session_id": "runtime-s"},
        "process": {"schema": 1, "process_id": "proc-a", "process_generation": 2, "role": "frontend", "pid": 21},
    }, {
        "header": {"status": 0, "abi_version": 1},
        "session": {"schema": 1, "session_id": "runtime-s"},
        "process": {"schema": 1, "process_id": "proc-b", "process_generation": 1, "role": "backend", "pid": 22},
    }]
    runtime_manifest = session_manifest(runtime_reports)
    assert [row["participant_id"] for row in runtime_manifest["participants"]] == ["frontend", "backend"]
    assert runtime_manifest["participants"][0]["process_id"] == "proc-a"
    assert runtime_manifest["participants"][0]["process_generation"] == 2

    try:
        session_manifest([{"session": {"schema": 99, "session_id": "bad"}}])
    except SessionDecodeError:
        pass
    else:
        raise AssertionError("unsupported session schema was accepted")
    try:
        session_manifest([{"session": {"schema": 1, "session_id": "a"}},
                          {"session": {"schema": 1, "session_id": "b"}}])
    except SessionDecodeError:
        pass
    else:
        raise AssertionError("session identity mismatch was accepted")
    print("session-manifest-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
