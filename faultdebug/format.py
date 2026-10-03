"""Strict decoder for the faultdebug shared-memory ABI.

The decoder never trusts host packing. It validates every offset and publication
marker before exposing records to callers.
"""
from __future__ import annotations

import hashlib
import mmap
import os
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = 0x31444646
ABI_VERSION = 1
MAX_THREADS, MAX_EVENTS, MAX_MODULES = 64, 4096, 256
RPC_MAGIC = 0x31515052
RPC_VERSION = 1
RPC_MAX_EVENTS = 1024
RPC_SIDECAR_FLAG_LOSS = 1
RPC_SIDECAR_FLAG_INCOMPLETE = 2
STATUS_CRASHED = 1 << 1
STATUS_FROZEN = 1 << 2
STATUS_EVENT_OVERFLOW = 1 << 3
STATUS_THREAD_OVERFLOW = 1 << 4
STATUS_MODULE_OVERFLOW = 1 << 5
STATUS_PARTIAL = 1 << 9
STATUS_DATA_LOSS = STATUS_EVENT_OVERFLOW | STATUS_THREAD_OVERFLOW | STATUS_MODULE_OVERFLOW
HEADER = struct.Struct("<IHHIIIIIIQQQQIIII")
THREAD = struct.Struct("<QIIQQII")
EVENT = struct.Struct("<QQQQIIII")
CRASH = struct.Struct("<IIIiQQQQQ8x")
MODULE = struct.Struct("<IIQQQII32s256s")
RPC_HEADER = struct.Struct("<IHHIIQQIIIIQQ")
RPC_EVENT = struct.Struct("<QQQQQQQQIIIIIIII")
THREAD_RING_STRIDE = THREAD.size + MAX_EVENTS * EVENT.size
THREAD_REGION_SIZE = MAX_THREADS * THREAD_RING_STRIDE
MODULES_OFFSET = HEADER.size + THREAD_REGION_SIZE
CRASHES_OFFSET = MODULES_OFFSET + MAX_MODULES * MODULE.size
V1_SHARED_SIZE = CRASHES_OFFSET + 2 * CRASH.size
RPC_SIDECAR_OFFSET = (V1_SHARED_SIZE + 63) & ~63


class FormatError(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    total_size: int
    status: int
    event_capacity: int
    thread_capacity: int
    module_capacity: int
    crash_capacity: int
    creator_pid: int
    start_ns: int
    ready_ns: int
    crash_ns: int
    threads_offset: int
    modules_offset: int
    crashes_offset: int


def _range_ok(offset: int, size: int, total: int) -> bool:
    return 0 <= offset <= total and 0 <= size <= total - offset


def parse_header(buf: bytes | mmap.mmap) -> Header:
    if len(buf) < HEADER.size:
        raise FormatError("mapping is shorter than ABI header")
    values = HEADER.unpack_from(buf, 0)
    magic, version, header_size, total, status, evcap, thcap, modcap, crcap, pid, start, ready, crash, toff, moff, coff, _ = values
    if magic != MAGIC or version != ABI_VERSION or header_size < HEADER.size:
        raise FormatError("unsupported ABI magic/version/header size")
    if total < header_size or total > len(buf):
        raise FormatError("invalid total_size")
    if not (1 <= evcap <= MAX_EVENTS and 1 <= thcap <= MAX_THREADS and 1 <= modcap <= MAX_MODULES and 1 <= crcap <= 2):
        raise FormatError("capacity exceeds ABI bounds")
    for off in (toff, moff, coff):
        if not _range_ok(off, 0, total):
            raise FormatError("region offset outside mapping")
    if not (toff <= moff <= coff):
        raise FormatError("regions are not ordered")
    return Header(total, status, evcap, thcap, modcap, crcap, pid, start, ready, crash, toff, moff, coff)


def _published(buf, offset: int) -> bool:
    return struct.unpack_from("<I", buf, offset)[0] == 1


def _sequence_u64(buf: bytes | mmap.mmap, offset: int) -> int:
    return struct.unpack_from("<Q", buf, offset)[0]


def _read_stable_record(buf: bytes | mmap.mmap, offset: int, size: int,
                        publication_offset: int, identity_offset: int = 0) -> tuple[bytes | None, str]:
    """Copy a committed record only when its publication and sequence stay stable."""
    if not _published(buf, offset + publication_offset):
        return None, "unpublished"
    sequence_before = _sequence_u64(buf, offset + identity_offset)
    record = bytes(buf[offset:offset + size])
    published_after = _published(buf, offset + publication_offset)
    sequence_after = _sequence_u64(buf, offset + identity_offset)
    sequence_copy = struct.unpack_from("<Q", record, identity_offset)[0]
    if not published_after or sequence_before != sequence_copy or sequence_copy != sequence_after:
        return None, "changed_during_read"
    return record, "stable"


def _collect_rpc_sidecar(buf: bytes | mmap.mmap, total: int) -> tuple[dict | None, list[dict[str, object]]]:
    """Decode the optional numeric RPC ring appended after the ABI v1 map."""
    if total < RPC_SIDECAR_OFFSET + RPC_HEADER.size:
        return None, []
    values = RPC_HEADER.unpack_from(buf, RPC_SIDECAR_OFFSET)
    magic, version, header_size, sidecar_total, capacity, count, dropped, process_generation, flags, events_offset, _reserved, _r2, _r3 = values
    # A zero-filled tail is the normal ABI v1 case.  Unknown non-zero tails
    # are rejected so a caller cannot mistake an unrelated extension for RPC.
    if magic == 0 and version == 0 and header_size == 0 and sidecar_total == 0:
        return None, []
    if magic != RPC_MAGIC or version != RPC_VERSION or header_size < RPC_HEADER.size:
        raise FormatError("unsupported RPC sidecar magic/version/header size")
    if sidecar_total < header_size or RPC_SIDECAR_OFFSET + sidecar_total > total:
        raise FormatError("RPC sidecar exceeds mapping")
    if not (1 <= capacity <= RPC_MAX_EVENTS):
        raise FormatError("RPC sidecar capacity exceeds ABI bounds")
    if events_offset < header_size or events_offset + capacity * RPC_EVENT.size > sidecar_total:
        raise FormatError("RPC event ring exceeds sidecar")
    events = []
    unstable_records: list[dict[str, object]] = []
    base = RPC_SIDECAR_OFFSET + events_offset
    for i in range(capacity):
        off = base + i * RPC_EVENT.size
        record, state = _read_stable_record(buf, off, RPC_EVENT.size, 84)
        expected = count >= capacity or i < count
        if record is None:
            if state == "changed_during_read" or expected:
                unstable_records.append({"kind": "rpc_event", "slot": i, "reason": state})
            continue
        row = RPC_EVENT.unpack(record)
        phase = ("begin" if row[12] & 1 and not row[12] & 2 else
                 "end" if row[12] & 2 else "event")
        events.append({
            "sequence": row[0], "rpc_id": row[1], "trace_id_hi": row[2], "trace_id_lo": row[3],
            "method_id": row[4], "start_monotonic_ns": row[5], "end_monotonic_ns": row[6],
            "tid": row[7], "process_generation": row[8], "thread_generation": row[9],
            "direction": row[10], "status": row[11], "flags": row[12],
            "phase": phase, "incomplete": bool(row[12] & 4),
            **({"attempt": row[14]} if row[14] else {}),
        })
    after = RPC_HEADER.unpack_from(buf, RPC_SIDECAR_OFFSET)
    if (count, dropped, process_generation, flags) != (after[5], after[6], after[7], after[8]):
        unstable_records.append({"kind": "rpc_header", "reason": "changed_during_read"})
    events.sort(key=lambda event: int(event["sequence"]))
    complete = not bool(flags & (RPC_SIDECAR_FLAG_LOSS | RPC_SIDECAR_FLAG_INCOMPLETE)) and not unstable_records
    return {
        "header": {
            "total_size": sidecar_total, "event_capacity": capacity,
            "event_count": count, "dropped_count": dropped,
            "process_generation": process_generation, "flags": flags,
            "events_offset": events_offset,
        },
        "events": events,
        "complete": complete,
        "snapshot_consistency": {"stable": not unstable_records, "unstable_records": unstable_records},
    }, unstable_records


def collect_mapping(buf: bytes | mmap.mmap) -> dict:
    """Return committed records, marking concurrent writes as partial evidence."""
    h = parse_header(buf)
    if h.threads_offset < HEADER.size or not _range_ok(
        h.threads_offset, THREAD_RING_STRIDE * h.thread_capacity, h.modules_offset
    ):
        raise FormatError("thread region exceeds mapping")
    if not _range_ok(
        h.modules_offset, MODULE.size * h.module_capacity, h.crashes_offset
    ):
        raise FormatError("module region exceeds mapping")
    if not _range_ok(h.crashes_offset, CRASH.size * h.crash_capacity, h.total_size):
        raise FormatError("crash region exceeds mapping")
    threads = []
    unstable_records: list[dict[str, object]] = []
    for i in range(h.thread_capacity):
        off = h.threads_offset + i * THREAD_RING_STRIDE
        thread_before = THREAD.unpack_from(buf, off)
        tid, generation, flags, count, dropped, capacity, _ = thread_before
        capacity = min(capacity or h.event_capacity, h.event_capacity)
        events = []
        for j in range(capacity):
            eo = off + THREAD.size + j * EVENT.size
            record, state = _read_stable_record(buf, eo, EVENT.size, 40)
            expected = count >= capacity or j < count
            if record is None:
                if state == "changed_during_read" or expected:
                    unstable_records.append({"kind": "event", "thread_slot": i,
                                             "event_slot": j, "reason": state})
                continue
            event = EVENT.unpack(record)
            if event[6] != 1 or event[5] != generation:
                continue
            events.append({"sequence": event[0], "monotonic_ns": event[1], "function": event[2], "callsite": event[3], "type": event[4], "generation": event[5]})
        thread_after = THREAD.unpack_from(buf, off)
        if thread_before[:6] != thread_after[:6]:
            unstable_records.append({"kind": "thread_header", "thread_slot": i,
                                     "reason": "changed_during_read"})
        # The native event ring is physically ordered by slot. Once it wraps,
        # slot order is no longer chronological; present committed records by
        # their per-thread sequence while retaining drops/instability above.
        events.sort(key=lambda event: int(event["sequence"]))
        if tid or generation or events or dropped:
            threads.append({"slot": i, "tid": tid, "generation": generation, "flags": flags, "event_count": count, "dropped_count": dropped, "events": events})
    modules = []
    for i in range(h.module_capacity):
        off = h.modules_offset + i * MODULE.size
        if not _published(buf, off):
            continue
        pub, plen, bias, start, end, build_len, build_flags, build_id, raw_path = MODULE.unpack_from(buf, off)
        if plen > len(raw_path):
            raise FormatError("module path length exceeds field")
        if build_len > len(build_id):
            raise FormatError("module build id length exceeds field")
        modules.append({"slot": i, "load_bias": bias, "text_start": start, "text_end": end, "build_id": build_id[:build_len].hex(), "path": raw_path[:plen].decode("utf-8", "replace")})
    crashes = []
    for i in range(h.crash_capacity):
        off = h.crashes_offset + i * CRASH.size
        publication = struct.unpack_from("<I", buf, off)[0]
        if publication == 0:
            continue
        record, state = _read_stable_record(buf, off, CRASH.size, 0, identity_offset=40)
        if record is None:
            unstable_records.append({"kind": "crash", "slot": i, "reason": state})
            continue
        pub, flags, sig, code, addr, pc, tid, ns, gen = CRASH.unpack(record)
        crashes.append({"slot": i, "flags": flags, "signal": sig, "si_code": code, "fault_address": addr, "pc": pc, "tid": tid, "monotonic_ns": ns, "thread_generation": gen})
    rpc, rpc_unstable_records = _collect_rpc_sidecar(buf, h.total_size)
    unstable_records.extend(rpc_unstable_records)
    if struct.unpack_from("<I", buf, 12)[0] != h.status:
        unstable_records.append({"kind": "shared_header", "reason": "status_changed_during_read"})
    snapshot_consistency = {"stable": not unstable_records, "unstable_records": unstable_records}
    rpc_complete = rpc is None or bool(rpc["complete"])
    report = {"header": h.__dict__, "threads": threads, "modules": modules, "crashes": crashes,
              "complete": not bool(h.status & (STATUS_PARTIAL | STATUS_DATA_LOSS)) and
                          not unstable_records and rpc_complete,
              "snapshot_consistency": snapshot_consistency}
    if rpc is not None:
        report["rpc"] = rpc
        # Keep a flat alias convenient for consumers that only need events;
        # the nested header remains the authoritative loss/completeness state.
        report["rpc_events"] = rpc["events"]
    return report


def write_report(report: dict, path: Path) -> str:
    import json
    data = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()

def collect_file(path: Path) -> dict:
    if path.suffix == ".fault":
        from .artifact import read_artifact
        return read_artifact(path)
    if path.suffix == ".json":
        import json
        return json.loads(path.read_text())
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        with mmap.mmap(stream.fileno(), size, access=mmap.ACCESS_READ) as mapping:
            return collect_mapping(mapping)
