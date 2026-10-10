#!/usr/bin/env python3
"""Verify that concurrently rewritten ABI v1/RPC records stay unresolved."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import faultdebug.format as fmt  # noqa: E402


def make_mapping(*, with_rpc: bool = False) -> tuple[bytearray, int, int | None]:
    total = fmt.RPC_SIDECAR_OFFSET + fmt.RPC_HEADER.size + fmt.RPC_EVENT.size if with_rpc else (
        fmt.HEADER.size + fmt.THREAD_RING_STRIDE + fmt.MODULE.size * fmt.MAX_MODULES + fmt.CRASH.size * 2
    )
    threads = fmt.HEADER.size
    modules = threads + fmt.THREAD_RING_STRIDE
    crashes = modules + fmt.MODULE.size * fmt.MAX_MODULES
    buf = bytearray(total)
    buf[:fmt.HEADER.size] = fmt.HEADER.pack(
        fmt.MAGIC, 1, fmt.HEADER.size, total, 0, 1, 1, fmt.MAX_MODULES, 2,
        7, 1, 2, 0, threads, modules, crashes, 0,
    )
    buf[threads:threads + fmt.THREAD.size] = fmt.THREAD.pack(123, 1, 0, 1, 0, 1, 0)
    event_offset = threads + fmt.THREAD.size
    buf[event_offset:event_offset + fmt.EVENT.size] = fmt.EVENT.pack(1, 100, 0x111, 0x222, 1, 1, 1, 0)
    rpc_offset = None
    if with_rpc:
        sidecar = fmt.RPC_SIDECAR_OFFSET
        buf[sidecar:sidecar + fmt.RPC_HEADER.size] = fmt.RPC_HEADER.pack(
            fmt.RPC_MAGIC, 1, fmt.RPC_HEADER.size, fmt.RPC_HEADER.size + fmt.RPC_EVENT.size,
            1, 1, 0, 1, 0, fmt.RPC_HEADER.size, 0, 0, 0,
        )
        rpc_offset = sidecar + fmt.RPC_HEADER.size
        buf[rpc_offset:rpc_offset + fmt.RPC_EVENT.size] = fmt.RPC_EVENT.pack(
            1, 9, 10, 11, 12, 100, 0, 13, 1, 1, 2, 14, 1, 1, 3, 0,
        )
    return buf, event_offset, rpc_offset


def simulate_native_rewrite(buf: bytearray, offset: int, *, rpc: bool) -> None:
    if rpc:
        old = fmt.RPC_EVENT.unpack_from(buf, offset)
        fmt.struct.pack_into("<I", buf, offset + 84, 0)
        buf[offset:offset + fmt.RPC_EVENT.size] = fmt.RPC_EVENT.pack(
            old[0] + 1, old[1] + 1, old[2], old[3], old[4], old[5] + 1, old[6], old[7],
            old[8], old[9], old[10], old[11], old[12], 0, old[14], old[15],
        )
        fmt.struct.pack_into("<I", buf, offset + 84, 1)
    else:
        old = fmt.EVENT.unpack_from(buf, offset)
        fmt.struct.pack_into("<I", buf, offset + 40, 0)
        buf[offset:offset + fmt.EVENT.size] = fmt.EVENT.pack(
            old[0] + 1, old[1] + 1, old[2] + 1, old[3] + 1,
            old[4] + 1, old[5], 1, 0,
        )
        fmt.struct.pack_into("<I", buf, offset + 40, 1)


def check_event_rewrite() -> None:
    buf, event_offset, _ = make_mapping()
    original_sequence = fmt._sequence_u64
    injected = False

    def rewrite_after_sequence_read(data, offset):
        nonlocal injected
        value = original_sequence(data, offset)
        if offset == event_offset and not injected:
            injected = True
            simulate_native_rewrite(buf, event_offset, rpc=False)
        return value

    fmt._sequence_u64 = rewrite_after_sequence_read
    try:
        report = fmt.collect_mapping(buf)
    finally:
        fmt._sequence_u64 = original_sequence
    assert injected, "event writer interleaving was not injected"
    assert report["threads"][0]["events"] == [], report["threads"]
    assert report["complete"] is False
    assert report["snapshot_consistency"]["stable"] is False
    assert any(row.get("kind") == "event" and row.get("reason") == "changed_during_read"
               for row in report["snapshot_consistency"]["unstable_records"])


def check_rpc_rewrite() -> None:
    buf, _event_offset, rpc_offset = make_mapping(with_rpc=True)
    assert rpc_offset is not None
    original_sequence = fmt._sequence_u64
    injected = False

    def rewrite_after_sequence_read(data, offset):
        nonlocal injected
        value = original_sequence(data, offset)
        if offset == rpc_offset and not injected:
            injected = True
            simulate_native_rewrite(buf, rpc_offset, rpc=True)
        return value

    fmt._sequence_u64 = rewrite_after_sequence_read
    try:
        report = fmt.collect_mapping(buf)
    finally:
        fmt._sequence_u64 = original_sequence
    assert injected, "RPC writer interleaving was not injected"
    assert report["rpc"]["events"] == [], report["rpc"]
    assert report["rpc"]["complete"] is False
    assert report["complete"] is False
    assert any(row.get("kind") == "rpc_event" and row.get("reason") == "changed_during_read"
               for row in report["snapshot_consistency"]["unstable_records"])


def check_generation_aba() -> None:
    buf, offset, _ = make_mapping()
    original = fmt._sequence_u64
    injected = False

    def replace_generation(data, position):
        nonlocal injected
        value = original(data, position)
        if position == offset and not injected:
            injected = True
            # Same publication and sequence, but a different generation.
            fmt.struct.pack_into("<I", data, offset + 36, 2)
        return value

    fmt._sequence_u64 = replace_generation
    try:
        record, state = fmt._read_stable_record(buf, offset, fmt.EVENT.size, 40,
                                               generation_offset=36)
    finally:
        fmt._sequence_u64 = original
    assert injected and record is None and state == "changed_during_read"


def check_retirement_without_status() -> None:
    buf, offset, _ = make_mapping()
    fmt.struct.pack_into("<I", buf, fmt.HEADER.size + 8, 2)
    fmt.struct.pack_into("<I", buf, fmt.HEADER.size + 12,
                         fmt.THREAD_GENERATION_COUNT | fmt.THREAD_HISTORY_RETIRED)
    fmt.struct.pack_into("<I", buf, offset + 36, 2)
    report = fmt.collect_mapping(buf)
    assert report["snapshot_consistency"]["stable"] is True
    assert report["complete"] is False, "retired history was called complete without PARTIAL"
    assert report["threads"][0]["retention"]["retired_generations"] == 1


def main() -> int:
    stable, _, _ = make_mapping()
    stable_report = fmt.collect_mapping(stable)
    assert stable_report["complete"] is True
    assert stable_report["snapshot_consistency"]["stable"] is True
    assert len(stable_report["threads"][0]["events"]) == 1
    overflow, _, _ = make_mapping()
    fmt.struct.pack_into("<I", overflow, 12, fmt.STATUS_EVENT_OVERFLOW)
    assert fmt.collect_mapping(overflow)["complete"] is False, "event loss was marked complete"
    reserved, _, _ = make_mapping()
    fmt.struct.pack_into("<Q", reserved, fmt.HEADER.size, (1 << 64) - 1)
    in_progress = fmt.collect_mapping(reserved)
    assert in_progress["threads"] == [], "reserved registration leaked a thread identity"
    assert in_progress["complete"] is False
    assert any(row.get("reason") == "registration_in_progress"
               for row in in_progress["snapshot_consistency"]["unstable_records"])
    check_event_rewrite()
    check_rpc_rewrite()
    check_generation_aba()
    check_retirement_without_status()
    print("snapshot-consistency-contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
