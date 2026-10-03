#!/usr/bin/env python3
"""Focused schema-v2 evidence-store checks."""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.artifact import write_artifact
from faultdebug.bundle import create_bundle
from faultdebug.evidence_store import EvidenceStore, SCHEMA_VERSION


EXPECTED = {
    "build_id": "build-v08",
    "binary_sha256": "b" * 64,
    "source_sha256": "s" * 64,
    "index_sha256": "i" * 64,
}


def report(session_id: str, process_id: str, *, start_ns: int, with_provenance: bool = True) -> dict:
    value = {
        "session": {"schema": 1, "session_id": session_id, "participant_id": process_id},
        "process": {"pid": start_ns % 100000, "parent_pid": 1, "start_monotonic_ns": start_ns,
                    "identity": {"schema": 1, "session_id": session_id,
                                  "process_id": process_id, "process_generation": 1, "role": process_id}},
        "target": {"returncode": 0, "signal": None},
        "collector": {"ok": True, "status": 0, "phase": "complete", "partial": False},
        "rpc_trace": {"schema": 1, "events": [{"sequence": 1, "rpc_id": 7, "method_id": 3,
                                                   "phase": "begin", "monotonic_ns": start_ns + 1,
                                                   "pid": start_ns % 100000}]},
        "static_candidates": [{"kind": "possible_rpc", "source": "test"}],
        "hypotheses": [{"kind": "operator_hypothesis", "confidence": "unknown"}],
        "peer_snapshots": [{"peer": process_id, "collector": {"phase": "partial", "partial": True}}],
        "evidence_class": "incident_snapshot" if process_id == "proc-a" else "observed",
    }
    if with_provenance:
        value["provenance"] = dict(EXPECTED)
    return value


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        artifacts = root / "artifacts"; artifacts.mkdir()
        first = write_artifact(report("session-a", "proc-a", start_ns=100), artifacts, 100)
        second = write_artifact(report("session-b", "proc-b", start_ns=200, with_provenance=False), artifacts, 200)
        db = root / "evidence.sqlite3"
        with EvidenceStore(db) as store:
            trusted = store.ingest(first, expected=EXPECTED)
            assert trusted["status"] == "ingested" and trusted["trust_state"] == "verified", trusted
            unresolved = store.ingest(second)
            assert unresolved["trust_state"] == "unresolved", unresolved
            sessions = store.list_sessions()
            assert sessions["schema"] == SCHEMA_VERSION and sessions["total"] == 2
            assert [row["session_id"] for row in sessions["sessions"]] == ["session-a", "session-b"]
            assert [row["session_id"] for row in store.list_sessions(start_ns=150)["sessions"]] == ["session-b"]
            assert [row["session_id"] for row in store.list_sessions(trust_state="verified")["sessions"]] == ["session-a"]
            selected = store.get_session("session-a")
            assert selected["observed"]["rpc_events"]
            assert selected["observed"]["peer_snapshots"]
            assert any(row.get("collector", {}).get("phase") == "complete"
                       for row in selected["observed"]["peer_snapshots"] if isinstance(row, dict))
            assert selected["static_candidates"] and selected["hypotheses"] and selected["unresolved"]
            assert selected["participants"][0]["runtime_process_id"] == "proc-a"
            provenance = store.get_provenance(session_id="session-a")
            assert provenance["provenance"][0]["trust_state"] == "verified"
            reopened = store.reindex([first])
            assert reopened["ingested"] == 1 and reopened["quarantined"] == 0

            mismatch = root / "mismatch.fault"
            mismatch.write_bytes(first.read_bytes())
            result = store.ingest(mismatch, expected={**EXPECTED, "build_id": "wrong"})
            assert result["status"] == "quarantined" and result["reason"] == "invalid_artifact"
            corrupt = root / "corrupt.fault"
            corrupt.write_bytes(first.read_bytes()[:-1] + b"x")
            result = store.ingest(corrupt)
            assert result["status"] == "quarantined"
            assert store.quarantine_rows()["total"] == 2

        with EvidenceStore(db, readonly=True) as readonly:
            assert readonly.list_sessions()["total"] == 2

        # Restart and migration from the v0.6 plural ArtifactIndex schema.
        legacy = root / "legacy.sqlite3"
        payload = report("legacy-session", "legacy-proc", start_ns=300)
        connection = sqlite3.connect(legacy)
        connection.execute("CREATE TABLE artifacts (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, pid INTEGER, trace_id TEXT, correlation_id TEXT, parent_pid INTEGER, start_ns INTEGER, payload TEXT NOT NULL, updated_ns INTEGER NOT NULL)")
        connection.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)", ("legacy.json", "legacy-digest", 1, None, None, None, 300, json.dumps(payload), 1))
        connection.commit(); connection.close()
        with EvidenceStore(legacy) as migrated:
            assert int(migrated.db.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
            assert migrated.list_sessions()["total"] == 1

        incident_root = root / "incident-artifacts"
        incident = report("incident-session", "incident-proc", start_ns=400, with_provenance=False)
        incident["collector"].update({"incident_id": "incident-1", "trigger_process_id": "incident-proc",
                                       "trigger_signal": 11, "phase": "incident_snapshot", "partial": True})
        incident["evidence_class"] = "incident_snapshot"
        source_root = root / "source"; source_root.mkdir()
        source_file = source_root / "main.c"; source_file.write_text("int main(void) {\n  return 0;\n}\n")
        source_index = root / "index.json"
        source_index.write_text(json.dumps({"functions": [{"id": "fn-main", "name": "main", "file": "main.c", "line": 1, "source_range": {"start": 1, "end": 3}}]}))
        incident["source_evidence"] = [{"function_id": "fn-main"}]
        incident_path = write_artifact(incident, incident_root, 400)
        bundle = create_bundle(source_root, root / "bundle", index=source_index)
        with EvidenceStore(root / "incident.sqlite3") as store:
            stored = store.ingest(incident_path)
            assert stored["status"] == "ingested"
            listed = store.list_incidents()
            assert listed["total"] == 1 and listed["incidents"][0]["incident_id"] == "incident-1"
            sliced = store.get_incident_slice("incident-1")
            assert sliced["observed"]["peer_snapshots"] and sliced["participants"]
            assert sliced["source_references"]
            citations = store.get_source_evidence("incident-1", bundle.root)
            assert citations["total"] == 1 and citations["citations"][0]["file"] == "source/main.c"
            assert citations["citations"][0]["line_start"] == 1 and citations["citations"][0]["sha256"]
            unresolved = store.get_unresolved("incident-1")
            assert isinstance(unresolved["unresolved"], list)
    print("evidence-store-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
