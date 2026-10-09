"""Evidence-bound fault documents and runtime-flow models.

Arrows describe retained instrumented nesting or record order, never an
inferred root cause. Source text comes exclusively from a verified bundle.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile

from .artifact import read_artifact
from .bundle import SourceBundle, load_bundle
from .format import STATUS_DATA_LOSS, STATUS_PARTIAL
from .inspect import diagnose, resolve_addresses, verified_function_source


LIMITATIONS = [
    "Recorded order and instrumented nesting do not establish the root cause or a direct call through uninstrumented code.",
    "The last recorded event before a crash is temporal context, not proof that the event caused the crash.",
    "Unmatched entries describe retained instrumentation, not an operating-system stack unwind.",
    "Threads are separated by TID and generation; no cross-thread causality is inferred.",
    "Static call candidates are kept separate from runtime observations. Source text requires a verified bundle.",
]


def _uint(value, field: str) -> int:
    if type(value) is not int or not 0 <= value < (1 << 64):
        raise ValueError(f"{field} must be an unsigned 64-bit integer")
    return value


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"


def build_fault_report(capture: dict, *, bundle: SourceBundle | str | None = None,
                       max_events: int = 80, language: str = "en") -> dict:
    """Build a bounded, read-only model from an already decoded capture."""
    if not 1 <= max_events <= 500:
        raise ValueError("max_events must be between 1 and 500")
    if language not in {"en", "ko"}:
        raise ValueError("language must be en or ko")
    if not isinstance(capture, dict):
        raise ValueError("capture must be an object")
    if bundle is not None and not isinstance(bundle, SourceBundle):
        bundle = load_bundle(bundle)
    if bundle is not None:
        bundle.verify()
        bundle.index_rows()
    raw_threads = capture.get("threads", [])
    raw_crashes = capture.get("crashes", [])
    if not isinstance(raw_threads, list) or not isinstance(raw_crashes, list):
        raise ValueError("threads and crashes must be arrays")
    if len(raw_threads) > 64 or len(raw_crashes) > 2:
        raise ValueError("capture exceeds native thread/crash capacity")
    for thread in raw_threads:
        if not isinstance(thread, dict):
            raise ValueError("thread must be an object")
        for key in ("tid", "generation"):
            _uint(thread.get(key), f"thread.{key}")
        for key in ("slot", "dropped_count"):
            _uint(thread.get(key, 0), f"thread.{key}")
        for event in thread.get("events", []):
            if not isinstance(event, dict):
                raise ValueError("event must be an object")
            for key in ("sequence", "type", "function", "callsite", "monotonic_ns", "generation"):
                _uint(event.get(key, thread["generation"] if key == "generation" else 0), f"event.{key}")
    for crash in raw_crashes:
        if not isinstance(crash, dict):
            raise ValueError("crash must be an object")
        for key in ("tid", "thread_generation", "flags", "pc", "fault_address", "monotonic_ns"):
            _uint(crash.get(key, 0), f"crash.{key}")
        if type(crash.get("signal", 0)) is not int:
            raise ValueError("crash.signal must be an integer")
    gaps: list[dict] = []
    threads: list[dict] = []
    edges: list[dict] = []
    addresses: set[int] = set()
    status = int(capture.get("header", {}).get("status", 0))
    if status & (STATUS_PARTIAL | STATUS_DATA_LOSS):
        gaps.append({"reason": "capture_status", "status": status})
    if capture.get("complete") is not True:
        gaps.append({"reason": "capture_completeness_unconfirmed"})
    snapshot = capture.get("snapshot_consistency", {})
    if snapshot.get("stable") is not True or snapshot.get("unstable_records"):
        gaps.append({"reason": "snapshot_unstable_or_unconfirmed",
                     "unstable_records": len(snapshot.get("unstable_records", []))})
    rpc = capture.get("rpc")
    if isinstance(rpc, dict) and rpc.get("complete") is not True:
        gaps.append({"reason": "rpc_capture_incomplete"})
    identities = [(t.get("tid"), t.get("generation")) for t in raw_threads]
    for index, thread in enumerate(raw_threads):
        tid, generation = thread.get("tid"), thread.get("generation")
        key = f"thread-{index}"
        events = thread.get("events", [])
        if not isinstance(events, list) or len(events) > 4096:
            raise ValueError("thread events exceed native ring capacity")
        events = sorted(events, key=lambda e: int(e["sequence"]))
        # A crash timestamp bounds this thread's view; records after that
        # timestamp cannot be presented as pre-crash context.
        matching = [c for c in raw_crashes if (c.get("tid"), c.get("thread_generation")) == (tid, generation)]
        times = [int(c["monotonic_ns"]) for c in matching if c.get("monotonic_ns", 0) > 0]
        cutoff = min(times) if times else None
        pre = [e for e in events if cutoff is None or not e.get("monotonic_ns") or e["monotonic_ns"] <= cutoff]
        start = max(0, len(pre) - max_events)
        shown = []
        stack = []
        previous = None
        local_gaps = []
        retained_edges = []
        for position, event in enumerate(pre):
            seq = int(event["sequence"])
            kind = int(event["type"])
            function = int(event.get("function", 0))
            reasons = []
            if previous is not None and seq != previous + 1:
                reasons.append("sequence_gap")
            if previous is None and seq > 0:
                reasons.append("retained_prefix_missing")
            if event.get("generation", generation) != generation:
                reasons.append("event_generation_mismatch")
            if kind not in (1, 2):
                reasons.append("recorder_marker_or_unknown_event")
            if reasons:
                stack.clear()
                local_gaps.append({"thread": key, "sequence": seq, "reasons": reasons})
            node_id = f"{key}-event-{position}"
            node = {"id": node_id, "kind": {1: "enter", 2: "exit"}.get(kind, "marker"),
                    "sequence": seq, "monotonic_ns": event.get("monotonic_ns"),
                    "function": function, "callsite": int(event.get("callsite", 0)),
                    "depth": len(stack), "gaps_before": reasons}
            if kind == 1 and "event_generation_mismatch" not in reasons:
                if stack:
                    retained_edges.append({"from": stack[-1][1], "to": node_id,
                                           "kind": "observed_nesting"})
                stack.append((function, node_id))
            elif kind == 2:
                if stack and stack[-1][0] == function:
                    stack.pop()
                    node["depth"] = len(stack)
                else:
                    stack.clear()
                    node["gaps_before"].append("unmatched_exit")
                    local_gaps.append({"thread": key, "sequence": seq, "reasons": ["unmatched_exit"]})
            if position >= start:
                shown.append(node)
                if function and kind in (1, 2):
                    addresses.add(function)
            previous = seq
        visible = {n["id"] for n in shown}
        edges.extend(e for e in retained_edges if e["from"] in visible and e["to"] in visible)
        edges.extend({"from": a["id"], "to": b["id"], "kind": "record_order"}
                     for a, b in zip(shown, shown[1:]) if not b["gaps_before"])
        if thread.get("dropped_count", 0):
            local_gaps.append({"thread": key, "reason": "dropped_records", "count": thread["dropped_count"]})
        if identities.count((tid, generation)) != 1:
            local_gaps.append({"thread": key, "reason": "ambiguous_thread_identity"})
        gaps.extend(local_gaps)
        threads.append({"id": key, "slot": thread.get("slot"), "tid": tid, "generation": generation,
                        "dropped_count": thread.get("dropped_count", 0), "retained_events": len(events),
                        "omitted_from_view": start, "post_crash_events": len(events) - len(pre),
                        "events": shown, "gaps": local_gaps,
                        "unmatched_entries": [{"function": fn, "event_id": nid} for fn, nid in stack]})
    crashes = []
    for index, crash in enumerate(raw_crashes):
        flags = int(crash.get("flags", 0))
        pc = int(crash.get("pc", 0)) if flags & 8 else None
        if pc is not None:
            addresses.add(pc)
        candidates = [t for t in threads if (t["tid"], t["generation"]) == (crash.get("tid"), crash.get("thread_generation"))]
        thread = candidates[0] if len(candidates) == 1 else None
        timestamp = int(crash.get("monotonic_ns", 0))
        before = [e for e in thread["events"] if timestamp > 0 and e.get("monotonic_ns", 0)
                  and e["monotonic_ns"] <= timestamp] if thread else []
        last = max(before, key=lambda e: (e["monotonic_ns"], e["sequence"])) if before else None
        item = {"id": f"crash-{index}", "kind": "crash", "flags": flags,
                "signal": crash.get("signal") if flags & 1 else None,
                "signal_name": _signal_name(int(crash["signal"])) if flags & 1 else "unrecorded signal",
                "si_code": crash.get("si_code") if flags & 2 else None,
                "pc": pc, "fault_address": crash.get("fault_address") if flags & 4 else None,
                "tid": crash.get("tid"), "generation": crash.get("thread_generation"),
                "monotonic_ns": timestamp, "thread": thread["id"] if thread else None,
                "last_event": last["id"] if last else None}
        if last:
            edges.append({"from": last["id"], "to": item["id"], "kind": "crash_context"})
        if not thread:
            gaps.append({"reason": "crash_thread_missing_or_ambiguous", "crash": item["id"]})
        if pc is None:
            gaps.append({"reason": "crash_pc_not_recorded", "crash": item["id"]})
        crashes.append(item)
    resolutions = resolve_addresses(capture, sorted(addresses), bundle=bundle)
    resolved = {r["address"]: r for r in resolutions}
    sources = {}
    if bundle:
        for row in resolutions:
            fid = row.get("function_id")
            if row.get("resolved") and fid and fid not in sources:
                source = verified_function_source(fid, bundle)
                source["source"] = "\n".join(source.get("source", "").splitlines()[:80])
                source["display_end_line"] = min(source.get("end_line", 0), source.get("start_line", 1) + 79)
                sources[fid] = source
    for node in [e for t in threads for e in t["events"]] + crashes:
        address = node.get("pc") if node["kind"] == "crash" else node.get("function")
        row = resolved.get(address, {"resolved": False, "reason": "address_not_recorded"})
        node["resolution"] = row
        node["label"] = row.get("symbol") or (node.get("signal_name") if node["kind"] == "crash" else f"0x{address or 0:x}")
        node["source_verified"] = bool(row.get("resolved") and sources.get(row.get("function_id"), {}).get("resolved"))
    return {"schema_version": 1, "kind": "faultdebug-fault-flow", "language": language,
            "capture": {"complete": capture.get("complete"), "status": status,
                        "evidence_status": "limited" if gaps else "capture_complete",
                        "snapshot_consistency": snapshot},
            "target": capture.get("target", {}), "threads": threads, "crashes": crashes,
            "edges": edges, "sources": sources, "gaps": gaps,
            "diagnostics": diagnose(capture, resolutions), "limitations": LIMITATIONS,
            "bundle": {"path": str(bundle.root), "verified": True} if bundle else None}


def render_markdown(model: dict) -> str:
    ko = model["language"] == "ko"
    title = "장애 실행 흐름 보고서" if ko else "Fault execution flow report"
    # Artifact strings are rendered as inert JSON text, never Markdown links.
    def literal(value):
        return json.dumps(value, ensure_ascii=False).replace("`", "\\u0060").replace("<", "\\u003c").replace(">", "\\u003e")
    lines = [f"# {title}", "", f"Evidence: **{model['capture']['evidence_status']}**", "",
             f"Artifact: `{literal(model.get('artifact', {}))}`", "",
             "## 장애 지점" if ko else "## Captured fault sites", ""]
    if not model["crashes"]:
        lines.append("장애 레코드 없음. 장애 지점을 추정하지 않습니다." if ko else "No crash record. A fault location cannot be inferred.")
    for c in model["crashes"]:
        lines.extend([f"- {c['signal_name']} · TID {c['tid']} / generation {c['generation']}",
                      f"  PC: `{hex(c['pc']) if c['pc'] is not None else 'unrecorded'}` · function: `{literal(c['label'])}`",
                      f"  Fault address: `{hex(c['fault_address']) if c['fault_address'] is not None else 'unrecorded'}`",
                      f"  Last observed event: `{c['last_event']}` (temporal context only)"])
    lines.extend(["", "## 관측된 실행 흐름" if ko else "## Observed execution flow", ""])
    for t in model["threads"]:
        lines.extend([f"### TID {t['tid']} / generation {t['generation']}", "",
                      f"Retained: {t['retained_events']} · omitted from view: {t['omitted_from_view']} · dropped: {t['dropped_count']}", "",
                      "| Sequence | Event | Function | Evidence |", "| --- | --- | --- | --- |"])
        for e in t["events"]:
            label = literal(e["label"]).replace("|", "\\u007c")
            reason = ", ".join(e["gaps_before"]) or ("verified source" if e["source_verified"] else e["resolution"].get("reason", "verified binary"))
            lines.append(f"| {e['sequence']} | {e['kind']} | `{label}` | {reason} |")
    lines.extend(["", "## 기록 한계와 확인 사항" if ko else "## Evidence limits and diagnostics", ""])
    for gap in model["gaps"]:
        lines.append(f"- `{literal(gap)}`")
    for d in model["diagnostics"]:
        lines.append(f"- {d['code']}: {d['message']}")
    lines.extend("- " + text for text in model["limitations"])
    lines.extend(["", "## 검증된 소스" if ko else "## Verified source", ""])
    if not model["sources"]:
        lines.append("No verified source snippet available; provide a matching source/binary bundle.")
    for fid, source in model["sources"].items():
        lines.extend([f"### {literal(fid)}", "", f"File: `{literal(source.get('file'))}` · lines {source.get('start_line')}–{source.get('display_end_line')}", ""])
        lines.extend("    " + line for line in source.get("source", "").splitlines())
        lines.append("")
    lines.extend(["", "Interactive flow: open `report.html`. Print / save PDF from the browser.", ""])
    return "\n".join(lines)


def write_fault_report(artifact: Path, output: Path, *, bundle: str | None = None,
                       max_events: int = 80, language: str = "en") -> dict:
    """Validate an FDAR artifact before atomically publishing a new directory."""
    from .report_view import render_html
    if artifact.suffix != ".fault":
        raise ValueError("fault-report requires a checksummed .fault artifact")
    if output.exists():
        raise ValueError("report output already exists; choose a new directory")
    # Hash the same bytes that the decoder validated, avoiding a reread race.
    data = artifact.read_bytes()
    with tempfile.TemporaryDirectory(prefix="faultdebug-input-") as staging:
        captured = Path(staging) / "input.fault"
        captured.write_bytes(data)
        model = build_fault_report(read_artifact(captured), bundle=bundle,
                                   max_events=max_events, language=language)
    model["artifact"] = {"path": str(artifact.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
                         "format": "FDAR", "checksum_verified": True}
    documents = {"report.json": json.dumps(model, ensure_ascii=False, indent=2) + "\n",
                 "report.md": render_markdown(model), "report.html": render_html(model)}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".faultdebug-report-", dir=output.parent))
    try:
        for name, content in documents.items():
            path = temporary / name
            path.write_text(content, encoding="utf-8")
            os.chmod(path, 0o600)
        if output.exists():
            raise ValueError("report output already exists; choose a new directory")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {"output": str(output.resolve()), "files": list(documents),
            "evidence_status": model["capture"]["evidence_status"], "crashes": len(model["crashes"])}
