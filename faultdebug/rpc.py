"""Optional semantic RPC evidence decoding.

ABI v1 records function entry/exit addresses only.  Semantic RPC data is an
optional, explicitly versioned artifact extension produced by a later runtime
contract.  This module deliberately does not reinterpret function names,
static edges, process IDs, or trace IDs as RPC observations.

The reader accepts an extension under ``rpc_trace`` (``rpc`` and
``semantic_rpc`` are accepted as compatibility aliases).  The extension must
be an object with ``schema == 1`` and an ``events`` array.  Unknown extension
versions and explicit ABI/provenance mismatches are errors; an absent
extension is a valid unresolved result for an ABI v1 artifact.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

RPC_SCHEMA_VERSION = 1
INCIDENT_REPORT_SCHEMA_VERSION = 1
_RPC_KEYS = ("rpc_trace", "rpc", "semantic_rpc")
_EVENT_KEYS = ("events", "rpc_events", "semantic_events")
_SEQ_KEYS = ("sequence", "event_sequence")
_TIME_KEYS = ("monotonic_ns", "timestamp_ns")
_KIND_KEYS = ("kind", "event_type", "type")
_SENSITIVE_KEYS = {
    "method", "method_name", "method_string", "method_hash", "metadata",
    "payload", "request", "response", "credentials", "headers",
    "peer_metadata",
}
_RPC_ID_KEYS = ("rpc_id", "rpc_id_hash", "call_id")
_PID_KEYS = ("pid", "process_id")
_PEER_PID_KEYS = ("peer_pid", "remote_pid", "endpoint_pid")


class RPCDecodeError(ValueError):
    """The optional RPC extension is malformed or conflicts with evidence."""


def _first(mapping: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _as_int(value: Any, field: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RPCDecodeError(f"rpc event {field} must be an integer")
    if positive and value < 0:
        raise RPCDecodeError(f"rpc event {field} must be non-negative")
    return value


def _extension(report: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    present = [(key, report[key]) for key in _RPC_KEYS if key in report]
    if not present:
        # The v0.4 sidecar decoder publishes this compact top-level shape so
        # ABI v1 JSON readers do not need to know about the sidecar layout.
        # Keep both names while the contract transition is in progress.
        top_level = next((key for key in ("rpc_events", "semantic_rpc_events") if key in report), None)
        if top_level is None:
            nested: list[Any] = []
            for thread in report.get("threads", []):
                if not isinstance(thread, dict):
                    continue
                nested.extend(thread.get("rpc_events", thread.get("semantic_events", [])) or [])
            if not nested:
                return None, None
            return {"schema": report.get("semantic_rpc_schema", report.get("rpc_schema", 1)),
                    "events": nested}, "threads.semantic_events"
        return {"schema": report.get("semantic_rpc_schema", report.get("rpc_schema", 1)),
                "events": report.get(top_level)}, top_level
    if len(present) != 1:
        raise RPCDecodeError("multiple semantic RPC extensions are ambiguous")
    key, value = present[0]
    if not isinstance(value, dict):
        raise RPCDecodeError(f"{key} must be an object")
    # ``format.collect_mapping`` publishes the native sidecar as
    # ``{"header": ..., "events": ..., "complete": ...}``; its header was
    # already checked against the native version before reaching this layer.
    if key == "rpc" and "schema" not in value and "version" not in value:
        if isinstance(value.get("header"), dict):
            value = dict(value)
            value["schema"] = RPC_SCHEMA_VERSION
    return value, key


def _check_provenance(report: dict[str, Any], extension: dict[str, Any]) -> None:
    """Check only provenance values supplied by both sides of the artifact.

    Older artifacts do not carry an FDAR digest in their JSON payload, so a
    digest is checked only when the reader has an explicit counterpart.  ABI
    and module Build ID comparisons are always possible when present.
    """
    header = report.get("header") or {}
    declared_abi = extension.get("abi_version")
    actual_abi = header.get("abi_version", header.get("version"))
    if declared_abi is not None and actual_abi is not None and declared_abi != actual_abi:
        raise RPCDecodeError("rpc extension ABI version does not match artifact header")
    declared_digest = extension.get("artifact_sha256")
    actual_digest = (report.get("_fdar") or {}).get("sha256")
    if declared_digest is not None and actual_digest is not None and str(declared_digest).lower() != str(actual_digest).lower():
        raise RPCDecodeError("rpc extension artifact digest does not match FDAR evidence")
    declared_build_ids = extension.get("build_ids")
    if declared_build_ids is None:
        provenance = extension.get("provenance")
        if isinstance(provenance, dict):
            declared_build_ids = provenance.get("build_ids")
    if declared_build_ids is None:
        return
    if not isinstance(declared_build_ids, dict):
        raise RPCDecodeError("rpc extension build_ids must be an object")
    actual_by_path = {
        str(row.get("path")): str(row.get("build_id", "")).lower()
        for row in report.get("modules", [])
        if isinstance(row, dict) and row.get("path") is not None
    }
    for path, build_id in declared_build_ids.items():
        if not isinstance(path, str) or not isinstance(build_id, str):
            raise RPCDecodeError("rpc extension build_ids must map strings to strings")
        if path in actual_by_path and actual_by_path[path] and actual_by_path[path] != build_id.lower():
            raise RPCDecodeError(f"rpc provenance Build ID mismatch for module {path}")


def _normalize_event(event: Any, index: int, report: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise RPCDecodeError(f"rpc event {index} must be an object")
    sensitive = sorted(key for key in _SENSITIVE_KEYS if key in event)
    if sensitive:
        raise RPCDecodeError(f"rpc event {index} contains forbidden sensitive fields: {', '.join(sensitive)}")
    result: dict[str, Any] = {"event_index": index}
    sequence = _first(event, _SEQ_KEYS)
    timestamp = _first(event, _TIME_KEYS)
    if timestamp is None:
        timestamp = event.get("start_monotonic_ns", event.get("end_monotonic_ns"))
    rpc_id = _first(event, _RPC_ID_KEYS)
    kind = _first(event, _KIND_KEYS)
    if sequence is not None:
        result["sequence"] = _as_int(sequence, "sequence", positive=True)
    if timestamp is not None:
        result["monotonic_ns"] = _as_int(timestamp, "timestamp", positive=True)
    for key in ("start_monotonic_ns", "end_monotonic_ns", "trace_id_hi", "trace_id_lo", "direction"):
        if key in event:
            result[key] = _as_int(event[key], key, positive=True)
    if rpc_id is not None:
        if not isinstance(rpc_id, (str, int)) or isinstance(rpc_id, bool):
            raise RPCDecodeError(f"rpc event {index} rpc_id must be a string or integer")
        result["rpc_id"] = rpc_id
    if kind is not None:
        if not isinstance(kind, (str, int)) or isinstance(kind, bool):
            raise RPCDecodeError(f"rpc event {index} kind must be a string or integer")
        result["kind"] = kind
    method_id = event.get("method_id")
    if method_id is not None:
        result["method_id"] = _as_int(method_id, "method_id", positive=True)
    for output, keys in (("phase", ("phase",)), ("role", ("role",)), ("status", ("status", "status_code"))):
        value = _first(event, keys)
        if value is not None:
            if not isinstance(value, (str, int)):
                raise RPCDecodeError(f"rpc event {index} {output} must be a string or integer")
            result[output] = value
    for output, keys in (("deadline_ns", ("deadline_ns", "deadline_monotonic_ns")),
                         ("retry_count", ("retry_count",)),
                         ("attempt", ("attempt",))):
        value = _first(event, keys)
        if value is not None:
            result[output] = _as_int(value, output, positive=True)
    for output, keys in (("stream", ("stream", "stream_type", "stream_kind")),
                         ("streaming", ("streaming",))):
        value = _first(event, keys)
        if value is not None:
            if output == "streaming" and not isinstance(value, bool):
                raise RPCDecodeError(f"rpc event {index} streaming must be boolean")
            if output == "stream" and not isinstance(value, (str, int)):
                raise RPCDecodeError(f"rpc event {index} stream must be a string or integer")
            result[output] = value
    phase = result.get("phase")
    if phase is not None:
        phase_name = str(phase).lower()
        if phase_name not in {"begin", "send", "receive", "recv", "status", "end", "cancel"}:
            raise RPCDecodeError(f"rpc event {index} has unsupported phase {phase!r}")
        result["phase"] = phase_name
    if phase is None and "flags" in event:
        flags = int(event["flags"])
        if flags & 1:
            result["phase"] = "begin"
        elif flags & 2:
            result["phase"] = "end"
        else:
            result["phase"] = "status"
    pid = _first(event, _PID_KEYS)
    peer_pid = _first(event, _PEER_PID_KEYS)
    if pid is not None:
        result["pid"] = _as_int(pid, "pid", positive=True)
    if peer_pid is not None:
        result["peer_pid"] = _as_int(peer_pid, "peer_pid", positive=True)
    # Keep contract-defined flags/cutoffs intact without treating them as RPC
    # semantics.  This is useful for callers deciding whether an event was
    # committed while preserving forward-compatible fields.
    for key in ("flags", "generation", "publication"):
        if key in event:
            result[key] = _as_int(event[key], key, positive=True)
    if "source" in event:
        if not isinstance(event["source"], str):
            raise RPCDecodeError(f"rpc event {index} source must be a string")
        result["source"] = event["source"]
    return result


def rpc_trace(report: dict[str, Any], *, static_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Decode semantic RPC evidence while retaining evidence classes.

    ``observed`` contains only committed semantic events from the optional
    extension.  ``static_candidates`` is caller supplied or explicitly
    recorded in the extension and is never merged into observations.
    ``unresolved`` records absent, incomplete, or ambiguous evidence.
    """
    extension, key = _extension(report)
    unresolved: list[dict[str, Any]] = []
    if extension is None:
        return {"schema": RPC_SCHEMA_VERSION, "status": "unresolved", "source": None,
                "observed": [], "static_candidates": list(static_candidates or []),
                "unresolved": [{"reason": "semantic_rpc_extension_absent", "evidence": "artifact"}]}
    version = extension.get("schema", extension.get("version"))
    if version != RPC_SCHEMA_VERSION:
        raise RPCDecodeError(f"unsupported semantic RPC schema version: {version!r}")
    _check_provenance(report, extension)
    raw_events = _first(extension, _EVENT_KEYS)
    if raw_events is None:
        raw_events = []
    if not isinstance(raw_events, list):
        raise RPCDecodeError("semantic RPC events must be an array")
    observed: list[dict[str, Any]] = []
    for index, event in enumerate(raw_events):
        observed.append(_normalize_event(event, index, report))
    observed.sort(key=lambda row: (row.get("monotonic_ns", 0), row.get("sequence", row["event_index"]), row["event_index"]))
    for before, after in zip(observed, observed[1:]):
        if "sequence" in before and "sequence" in after and after["sequence"] <= before["sequence"]:
            unresolved.append({"reason": "rpc_sequence_not_monotonic", "before": before["sequence"], "after": after["sequence"]})
        elif "sequence" in before and "sequence" in after and after["sequence"] > before["sequence"] + 1:
            unresolved.append({"reason": "rpc_sequence_gap", "before": before["sequence"], "after": after["sequence"]})
    status = int((report.get("header") or {}).get("status", 0))
    if status & ((1 << 3) | (1 << 9)):
        unresolved.append({"reason": "runtime_trace_partial_or_overflow", "status": status})
    extension_candidates = extension.get("static_candidates", report.get("static_candidates", []))
    if extension_candidates is not None and not isinstance(extension_candidates, list):
        raise RPCDecodeError("semantic RPC static_candidates must be an array")
    candidates = list(static_candidates if static_candidates is not None else extension_candidates or [])
    sidecar_header = extension.get("header") if isinstance(extension.get("header"), dict) else {}
    sidecar_flags = int(sidecar_header.get("flags", 0))
    if extension.get("complete") is False or sidecar_flags & 3:
        unresolved.append({"reason": "semantic_rpc_stream_incomplete", "flags": sidecar_flags,
                           "dropped_count": sidecar_header.get("dropped_count", 0)})
    if not observed and not unresolved:
        unresolved.append({"reason": "semantic_rpc_events_empty", "evidence": key})
    return {"schema": RPC_SCHEMA_VERSION, "status": "complete" if not unresolved else "limited",
            "source": key, "observed": observed, "static_candidates": candidates, "unresolved": unresolved}


def process_relations(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Join explicit RPC endpoints and IPC pairs across process reports.

    A relation is observed only when exactly one matching send/request and one
    matching receive/response have explicit process IDs.  Parent PID and
    shared trace IDs are retained as unresolved context and never promoted to
    causal edges.
    """
    observed: list[dict[str, Any]] = []
    static_candidates: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    rpc_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for report in reports:
        try:
            decoded = rpc_trace(report)
        except RPCDecodeError as exc:
            unresolved.append({"reason": "rpc_decode_error", "message": str(exc)})
            continue
        unresolved.extend(decoded["unresolved"])
        for event in decoded["observed"]:
            rpc_rows.append((report, event))
    grouped: dict[Any, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for report, event in rpc_rows:
        if event.get("rpc_id") is not None:
            grouped[event["rpc_id"]].append((report, event))
    for rpc_id, rows in grouped.items():
        by_pid: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for item in rows:
            pid = item[1].get("pid") or (item[0].get("process") or {}).get("pid")
            if pid is not None:
                by_pid[int(pid)].append(item)
        if len(by_pid) != 2:
            unresolved.append({"reason": "rpc_endpoint_pair_not_unique", "rpc_id": rpc_id,
                               "events": len(rows), "processes": sorted(by_pid)})
            continue
        endpoint_roles: dict[int, set[str]] = defaultdict(set)
        explicit_pairs: set[tuple[int, int]] = set()
        for pid, items in by_pid.items():
            for report, event in items:
                direction = event.get("direction")
                phase = str(event.get("phase", "")).lower()
                if direction == 2 or phase in {"begin", "send"}:
                    endpoint_roles[pid].add("outbound")
                elif direction == 1 or phase in {"receive", "recv"}:
                    endpoint_roles[pid].add("inbound")
                peer_pid = event.get("peer_pid")
                if peer_pid is not None:
                    explicit_pairs.add((pid, int(peer_pid)))
        outbound_pids = [pid for pid, roles in endpoint_roles.items() if roles == {"outbound"}]
        inbound_pids = [pid for pid, roles in endpoint_roles.items() if roles == {"inbound"}]
        if len(outbound_pids) == 1 and len(inbound_pids) == 1 and outbound_pids[0] != inbound_pids[0]:
            left_pid, right_pid = outbound_pids[0], inbound_pids[0]
        elif not endpoint_roles and len(explicit_pairs) == 2:
            pair = sorted(by_pid)
            if explicit_pairs != {(pair[0], pair[1]), (pair[1], pair[0])}:
                unresolved.append({"reason": "rpc_endpoint_pair_not_unique", "rpc_id": rpc_id,
                                   "pairs": sorted(explicit_pairs)})
                continue
            left_pid, right_pid = pair
        else:
            unresolved.append({"reason": "rpc_endpoint_pair_not_unique", "rpc_id": rpc_id,
                               "outbound": sorted(outbound_pids), "inbound": sorted(inbound_pids),
                               "pairs": sorted(explicit_pairs)})
            continue
        left = by_pid[left_pid][0]
        right = by_pid[right_pid][0]
        observed.append({"kind": "rpc", "rpc_id": rpc_id, "from_pid": left_pid,
                         "to_pid": right_pid, "method_id": left[1].get("method_id", right[1].get("method_id")),
                         "evidence": ["semantic_rpc_events"]})
    # Reuse the existing strict IPC joiner only for explicit context evidence.
    from .aggregate import build_timeline
    timeline = build_timeline(reports)
    observed.extend(timeline.get("relations", []))
    unresolved.extend(timeline.get("diagnostics", []))
    for report in reports:
        for candidate in (report.get("static_candidates") or []):
            if isinstance(candidate, dict):
                static_candidates.append(candidate)
    return {"schema": RPC_SCHEMA_VERSION, "status": "complete" if not unresolved else "limited",
            "observed": observed, "static_candidates": static_candidates, "unresolved": unresolved}


def evidence_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Return counts and limits without collapsing evidence classes."""
    decoded: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for report in reports:
        try:
            decoded.append(rpc_trace(report))
        except RPCDecodeError as exc:
            unresolved.append({"reason": "rpc_decode_error", "message": str(exc)})
    relations = process_relations(reports)
    unresolved.extend(relations["unresolved"])
    return {"schema": RPC_SCHEMA_VERSION,
            "status": "complete" if not unresolved else "limited",
            "artifacts": len(reports),
            "observed": {"rpc_events": sum(len(row["observed"]) for row in decoded),
                         "process_relations": len(relations["observed"])},
            "static_candidates": sum(len(row["static_candidates"]) for row in decoded),
            "unresolved": unresolved}


def incident_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a read-only incident view without merging evidence classes.

    Status, deadline, retry, and stream values are copied only when an
    artifact explicitly supplies them. No status, deadline, retry, or stream
    value is inferred from timestamps, process identity, static edges, or
    function names.
    """
    observed_events: list[dict[str, Any]] = []
    static_candidates: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    fields: dict[str, list[dict[str, Any]]] = {
        "status": [], "deadlines": [], "retries": [], "streams": []
    }
    artifacts: list[dict[str, Any]] = []
    for artifact_index, report in enumerate(reports):
        process = report.get("process") if isinstance(report.get("process"), dict) else {}
        target = report.get("target") if isinstance(report.get("target"), dict) else {}
        collector = report.get("collector") if isinstance(report.get("collector"), dict) else {}
        artifacts.append({"index": artifact_index,
                          "pid": process.get("pid"),
                          "target": {key: target[key] for key in ("returncode", "signal") if key in target},
                          "collector": {key: collector[key] for key in ("ok", "status", "partial", "phase") if key in collector}})
        try:
            decoded = rpc_trace(report)
        except RPCDecodeError as exc:
            unresolved.append({"artifact_index": artifact_index, "reason": "rpc_decode_error", "message": str(exc)})
            continue
        for item in decoded["unresolved"]:
            unresolved.append({"artifact_index": artifact_index, **item})
        for candidate in decoded["static_candidates"]:
            static_candidates.append(candidate)
        for event in decoded["observed"]:
            row = {"artifact_index": artifact_index, **event}
            observed_events.append(row)
            for field_name, output_name in (("status", "status"), ("deadline_ns", "deadlines"),
                                            ("retry_count", "retries"), ("attempt", "retries"),
                                            ("stream", "streams"), ("streaming", "streams")):
                if field_name in event:
                    fields[output_name].append({"artifact_index": artifact_index,
                                                "rpc_id": event.get("rpc_id"),
                                                field_name: event[field_name]})
    relations = process_relations(reports)
    for item in relations["unresolved"]:
        unresolved.append({"scope": "process_relations", **item})
    status = "complete" if not unresolved else ("limited" if observed_events or relations["observed"] else "unresolved")
    return {"schema": INCIDENT_REPORT_SCHEMA_VERSION, "status": status,
            "artifacts": artifacts,
            "observed": {"rpc_events": observed_events, "process_relations": relations["observed"]},
            "static_candidates": static_candidates,
            "unresolved": unresolved, "fields": fields}
