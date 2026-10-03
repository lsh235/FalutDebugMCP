#!/usr/bin/env python3
"""Unit checks for evidence-only timelines and restartable artifact indexes."""
import tempfile
from pathlib import Path
from faultdebug.aggregate import ArtifactIndex, build_timeline

def main() -> int:
    reports = [
        {"process": {"pid": 10, "start_monotonic_ns": 1}, "context": {"ipc_events": [{"kind": "send", "message_id": "m", "channel": "pipe", "timestamp_ns": 10, "receiver_pid": 11}]}},
        {"process": {"pid": 11, "parent_pid": 10, "start_monotonic_ns": 2}, "context": {"ipc_events": [{"kind": "receive", "message_id": "m", "channel": "pipe", "timestamp_ns": 20, "sender_pid": 10}]}}
    ]
    timeline = build_timeline(reports)
    assert timeline["status"] == "complete" and len(timeline["relations"]) == 1
    missing = build_timeline([{ "process": {"pid": 1}, "context": {}}, {"process": {"pid": 2}, "context": {}}])
    assert any(item["status"] == "evidence_missing" for item in missing["diagnostics"])
    invalid = build_timeline([{"process": {"pid": 1}, "context": {"ipc_events": [{"kind": "send", "timestamp_ns": 1}]}}])
    assert not invalid["relations"] and any(item["reason"] == "invalid_ipc_evidence" for item in invalid["diagnostics"])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); artifact = root / "one.json"
        artifact.write_text('{"process":{"pid":1},"context":{"trace_id":"t"},"target":{},"collector":{},"crashes":[] }')
        db = root / "artifacts.sqlite"
        index = ArtifactIndex(db); assert index.add([artifact]) == 1; index.close()
        reopened = ArtifactIndex(db); assert len(reopened.query(trace_id="t")) == 1; assert reopened.add([artifact]) == 1; assert len(reopened.query(trace_id="t")) == 1; reopened.close()
    print("aggregate-ok")
    return 0

if __name__ == "__main__": raise SystemExit(main())
