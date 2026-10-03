#!/usr/bin/env python3
"""Validate Python decoding of the fixed native ABI and attempt extension."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from faultdebug.format import (  # noqa: E402
    CRASH, CRASHES_OFFSET, EVENT, HEADER, MODULE, MODULES_OFFSET, RPC_EVENT,
    RPC_HEADER, RPC_MAGIC, RPC_SIDECAR_OFFSET, THREAD, THREAD_RING_STRIDE, FormatError,
    collect_mapping,
)


def main() -> int:
    if HEADER.size != 80 or RPC_HEADER.size != 64 or RPC_EVENT.size != 96:
        raise SystemExit("decoder fixed-width ABI sizes changed")
    total = RPC_SIDECAR_OFFSET + RPC_HEADER.size + RPC_EVENT.size
    buf = bytearray(total)
    buf[:HEADER.size] = HEADER.pack(
        0x31444646, 1, HEADER.size, total, 0, 4096, 64, 256, 2,
        7, 1, 2, 0, HEADER.size, MODULES_OFFSET, CRASHES_OFFSET, 0)
    sidecar = RPC_SIDECAR_OFFSET
    buf[sidecar:sidecar + RPC_HEADER.size] = RPC_HEADER.pack(
        RPC_MAGIC, 1, RPC_HEADER.size, RPC_HEADER.size + RPC_EVENT.size,
        1, 1, 0, 1, 0, RPC_HEADER.size, 0, 0, 0)
    event = RPC_EVENT.pack(1, 9, 10, 11, 12, 100, 0, 13,
                           1, 1, 2, 14, 1, 1, 3, 0)
    event_offset = sidecar + RPC_HEADER.size
    buf[event_offset:event_offset + RPC_EVENT.size] = event
    report = collect_mapping(buf)
    events = report.get("rpc", {}).get("events", [])
    if len(events) != 1 or events[0].get("rpc_id") != 9:
        raise SystemExit("decoder did not expose the committed RPC event")
    if events[0].get("attempt") != 3 or events[0].get("phase") != "begin":
        raise SystemExit("decoder did not expose v0.9 attempt/phase")
    if THREAD_RING_STRIDE != 196648:
        raise SystemExit("decoder physical thread-ring stride changed")

    # A wrapped native ring is physically split at its write cursor. Decoder
    # consumers must receive the committed suffix in chronological order.
    ring_offset = HEADER.size
    module_offset = ring_offset + THREAD_RING_STRIDE
    crashes_offset = module_offset + MODULE.size
    wrapped_size = crashes_offset + CRASH.size
    wrapped = bytearray(wrapped_size)
    wrapped[:HEADER.size] = HEADER.pack(
        0x31444646, 1, HEADER.size, wrapped_size, 0, 4, 1, 1, 1,
        7, 1, 2, 0, ring_offset, module_offset, crashes_offset, 0)
    wrapped[ring_offset:ring_offset + THREAD.size] = THREAD.pack(99, 1, 0, 6, 2, 4, 0)
    for slot, sequence in enumerate((5, 6, 3, 4)):
        event_offset = ring_offset + THREAD.size + slot * EVENT.size
        wrapped[event_offset:event_offset + EVENT.size] = EVENT.pack(
            sequence, sequence, 0, 0, 1 if sequence % 2 else 2, 1, 1, 0)
    wrapped_report = collect_mapping(wrapped)
    wrapped_events = wrapped_report["threads"][0]["events"]
    if [row["sequence"] for row in wrapped_events] != [3, 4, 5, 6]:
        raise SystemExit("decoder did not sort a wrapped thread ring by event sequence")

    truncated_size = HEADER.size + THREAD_RING_STRIDE
    truncated = bytearray(truncated_size)
    truncated[:HEADER.size] = HEADER.pack(
        0x31444646, 1, HEADER.size, truncated_size, 0, 8, 2, 256, 2,
        7, 1, 2, 0, HEADER.size, MODULES_OFFSET, CRASHES_OFFSET, 0)
    try:
        collect_mapping(truncated)
    except FormatError:
        pass
    else:
        raise SystemExit("decoder accepted a mapping truncated inside its physical thread region")
    print("faultdebug-decoder-contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
