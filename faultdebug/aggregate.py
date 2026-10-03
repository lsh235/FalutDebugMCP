"""Backward-compatible multi-process collection and evidence-only timelines."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from .format import collect_file

def collect_artifacts(paths: list[Path], *, trace_id: str | None = None, correlation_id: str | None = None) -> dict:
    rows = []
    for path in paths:
        report = collect_file(path)
        context = report.get("context") or {}
        if trace_id is not None and context.get("trace_id") != trace_id: continue
        if correlation_id is not None and context.get("correlation_id") != correlation_id: continue
        rows.append({"artifact": str(path), "process": report.get("process", {}), "context": context, "target": report.get("target", {}), "collector": report.get("collector", {}), "crashes": report.get("crashes", [])})
    groups = {}
    for row in rows:
        key = row["context"].get("trace_id") or row["context"].get("correlation_id") or "ungrouped"
        groups.setdefault(key, []).append(row["artifact"])
    return {"schema": 1, "count": len(rows), "artifacts": rows, "groups": groups, "filters": {"trace_id": trace_id, "correlation_id": correlation_id}}


def build_timeline(reports: list[dict]) -> dict:
    """Build only edges supported by explicit matching IPC send/receive evidence."""
    events, sends, receives, diagnostics = [], {}, {}, []
    for report in reports:
        process = report.get("process") or {}; pid = process.get("pid")
        start = process.get("start_monotonic_ns")
        if pid is not None and start is not None: events.append({"kind": "process_start", "pid": pid, "timestamp_ns": start, "evidence": "process.start_monotonic_ns"})
        for crash in report.get("crashes", []):
            if crash.get("monotonic_ns") is not None: events.append({"kind": "crash", "pid": pid, "timestamp_ns": crash["monotonic_ns"], "signal": crash.get("signal"), "evidence": "crash.monotonic_ns"})
        for item in (report.get("context") or {}).get("ipc_events", []):
            if (not isinstance(item, dict) or item.get("kind") not in {"send", "receive"}
                    or item.get("timestamp_ns") is None or not item.get("message_id") or not item.get("channel")):
                diagnostics.append({"status": "ambiguous", "reason": "invalid_ipc_evidence", "pid": pid}); continue
            row = dict(item); row["pid"] = pid; row["evidence"] = "context.ipc_events"
            events.append(row); key = (item.get("message_id"), item.get("channel"))
            (sends if item["kind"] == "send" else receives).setdefault(key, []).append(row)
    relations = []
    for key in sorted(set(sends) | set(receives), key=str):
        left, right = sends.get(key, []), receives.get(key, [])
        if len(left) != 1 or len(right) != 1:
            diagnostics.append({"status": "ambiguous" if left or right else "evidence_missing", "reason": "ipc_send_receive_not_unique", "message_id": key[0], "channel": key[1]}); continue
        send, receive = left[0], right[0]
        if receive.get("sender_pid") not in (None, send.get("pid")) or send.get("receiver_pid") not in (None, receive.get("pid")):
            diagnostics.append({"status": "ambiguous", "reason": "ipc_endpoint_mismatch", "message_id": key[0], "channel": key[1]}); continue
        if receive["timestamp_ns"] < send["timestamp_ns"]:
            diagnostics.append({"status": "ambiguous", "reason": "ipc_timestamp_order_invalid", "message_id": key[0], "channel": key[1]}); continue
        relations.append({"kind": "ipc", "message_id": key[0], "channel": key[1], "from_pid": send["pid"], "to_pid": receive["pid"], "send_timestamp_ns": send["timestamp_ns"], "receive_timestamp_ns": receive["timestamp_ns"], "send_sequence": send.get("sequence"), "receive_sequence": receive.get("sequence"), "evidence": ["send", "receive"]})
    if len({(r.get("process") or {}).get("pid") for r in reports}) > 1 and not relations:
        diagnostics.append({"status": "evidence_missing", "reason": "no_explicit_ipc_pair"})
    events.sort(key=lambda row: (row.get("timestamp_ns", 0), row.get("pid", 0)))
    return {"schema": 1, "status": "complete" if not diagnostics else "limited", "events": events, "relations": relations, "diagnostics": diagnostics}


class ArtifactIndex:
    """Restartable SQLite index of artifact metadata; payloads remain in .fault files."""
    def __init__(self, path: Path):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS artifacts (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, pid INTEGER, trace_id TEXT, correlation_id TEXT, parent_pid INTEGER, start_ns INTEGER, payload TEXT NOT NULL, updated_ns INTEGER NOT NULL)")
        self.db.commit()

    def add(self, paths: list[Path]) -> int:
        count = 0
        for path in paths:
            payload = collect_file(path); raw = path.read_bytes(); process = payload.get("process") or {}; context = payload.get("context") or {}
            self.db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,pid=excluded.pid,trace_id=excluded.trace_id,correlation_id=excluded.correlation_id,parent_pid=excluded.parent_pid,start_ns=excluded.start_ns,payload=excluded.payload,updated_ns=excluded.updated_ns", (str(path.resolve()), hashlib.sha256(raw).hexdigest(), process.get("pid"), context.get("trace_id"), context.get("correlation_id"), process.get("parent_pid"), process.get("start_monotonic_ns"), json.dumps(payload, sort_keys=True), time.time_ns()))
            count += 1
        self.db.commit(); return count

    def query(self, *, trace_id: str | None = None, correlation_id: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
        clauses, values = [], []
        if trace_id is not None: clauses.append("trace_id=?"); values.append(trace_id)
        if correlation_id is not None: clauses.append("correlation_id=?"); values.append(correlation_id)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.execute(f"SELECT path,payload FROM artifacts{where} ORDER BY start_ns,pid LIMIT ? OFFSET ?", (*values, min(limit, 1000), max(offset, 0))).fetchall()
        return [{"artifact": path, **json.loads(payload)} for path, payload in rows]

    def close(self): self.db.close()
