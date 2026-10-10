#!/usr/bin/env python3
"""Compare current native thread generations with an independent raw-slot oracle."""
from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from faultdebug import format as fmt
from faultdebug.fault_report import build_fault_report
from faultdebug.run import SHM_SIZE, _runtime_environment

# Literal ABI v1 offsets/sizes, deliberately independent of decoder constants.
THREAD_BASE, RING_STRIDE, THREAD_BYTES, EVENT_BYTES = 80, 196648, 40, 48
RAW_THREAD = struct.Struct("<QIIQQII")
RAW_EVENT = struct.Struct("<QQQQIIII")


def sample(binary: Path, capacity: int, workers: int, width: int = 1,
           mode: str = "normal", seed_generation: int = 0) -> tuple[dict, dict]:
    fd = os.memfd_create("faultdebug-thread-generation", os.MFD_CLOEXEC)
    ready_read, ready_write = os.pipe()
    process = None
    try:
        os.ftruncate(fd, SHM_SIZE)
        os.pwrite(fd, fmt.HEADER.pack(fmt.MAGIC, 1, 80, SHM_SIZE, 0, 4096, 64, 256, 2,
                                    os.getpid(), time.monotonic_ns(), 0, 0,
                                    80, 12585552, 12669520, 0), 0)
        if seed_generation:
            os.pwrite(fd, struct.pack("<I", seed_generation), THREAD_BASE + 8)
        command = [str(binary), str(workers), mode, str(width)]
        env = _runtime_environment(command)
        env.update(FAULTDEBUG_CONFIG=f"events={capacity},threads={width}",
                   FAULTDEBUG_SHM_FD=str(fd), FAULTDEBUG_READY_FD=str(ready_write))
        env.pop("FAULTDEBUG_DISABLE", None)
        process = subprocess.Popen(command, env=env, pass_fds=(fd, ready_write),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(ready_write)
        ready_write = -1
        if not select.select([ready_read], [], [], 10)[0] or os.read(ready_read, 1) != b"R":
            raise AssertionError("native generation fixture did not become ready")
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == (-signal.SIGILL if mode == "fault" else 0), stderr
        if mode != "fault":
            assert stdout.decode().strip() == f"workers={workers} width={width}", stdout
        raw = os.pread(fd, SHM_SIZE, 0)
        physical = []
        for slot in range(width):
            offset = THREAD_BASE + slot * RING_STRIDE
            tid, generation, flags, count, dropped, cap, _ = RAW_THREAD.unpack_from(raw, offset)
            events = [RAW_EVENT.unpack_from(raw, offset + THREAD_BYTES + i * EVENT_BYTES)
                      for i in range(capacity)]
            retained = sorted((e for e in events if e[6] == 1 and e[5] == generation),
                              key=lambda e: e[0])
            physical.append({"slot": slot, "tid": tid, "generation": generation,
                             "flags": flags, "event_count": count, "dropped_count": dropped,
                             "capacity": cap, "records": [list(e) for e in retained]})
        with mmap.mmap(fd, SHM_SIZE, access=mmap.ACCESS_READ) as mapping:
            decoded = fmt.collect_mapping(mapping)
        oracle = {"capacity": capacity, "workers": workers, "width": width, "mode": mode,
                  "returncode": process.returncode, "mapping_sha256": hashlib.sha256(raw).hexdigest(),
                  "physical": physical}
        return decoded, oracle
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        for value in (fd, ready_read, ready_write):
            if value >= 0:
                os.close(value)


def verify(decoded: dict, oracle: dict) -> None:
    capacity, workers, width, mode = (oracle[k] for k in ("capacity", "workers", "width", "mode"))
    assert decoded["snapshot_consistency"]["stable"] is True, decoded["snapshot_consistency"]
    assert len(decoded["threads"]) == width
    by_slot = {t["slot"]: t for t in decoded["threads"]}
    per_generation = 26 if mode == "wrap" else 2
    prior_generation_count = 26 if mode in {"wrap", "retired-overflow"} else 2
    for physical in oracle["physical"]:
        thread = by_slot[physical["slot"]]
        generation = workers // width
        expected_count = 1 if mode == "fault" else per_generation
        assert physical["generation"] == generation, physical
        assert physical["event_count"] == expected_count, physical
        expected_drops = ((generation - 1) * max(0, prior_generation_count - capacity)
                          + max(0, expected_count - capacity))
        assert physical["dropped_count"] == expected_drops, physical
        actual = [[e["sequence"], e["monotonic_ns"], e["function"], e["callsite"],
                   e["type"], e["generation"], 1, 0] for e in thread["events"]]
        assert actual == physical["records"], (thread, physical)
        assert len(actual) == min(expected_count, capacity), physical
        assert all(row[5] == generation for row in actual)
        retention = thread["retention"]
        assert retention["event_count_scope"] == "current_generation"
        assert retention["dropped_count_scope"] == "slot_lifetime"
        assert retention["retired_generations"] == generation - 1
    expected_complete = workers == width and per_generation <= capacity and mode != "fault"
    assert decoded["complete"] is expected_complete, decoded
    if workers > width:
        assert decoded["header"]["status"] & fmt.STATUS_PARTIAL
        model = build_fault_report(decoded)
        assert any(g.get("reason") == "retired_thread_generations" for g in model["gaps"])
    if mode == "fault":
        crash, = decoded["crashes"]
        assert crash["signal"] == signal.SIGILL
        match = [t for t in decoded["threads"] if
                 (t["tid"], t["generation"]) == (crash["tid"], crash["thread_generation"])]
        assert len(match) == 1 and match[0]["events"], crash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expect-regression", action="store_true")
    args = parser.parse_args()
    binary = args.binary.resolve()
    results = []
    cases = ([(8, 80, 1, "normal")] if args.expect_regression else
             [(cap, count, 1, "normal") for cap in (1, 8, 4096) for count in (1, 80, 10000)] +
             [(8, 80, 2, "normal"), (4096, 128, 64, "normal"),
              (8, 80, 1, "wrap"), (4096, 80, 1, "wrap"),
              (8, 80, 1, "retired-overflow")] +
             [(cap, 80, 1, "fault") for cap in (1, 8, 4096)])
    for cap, count, width, mode in cases:
        decoded, oracle = sample(binary, cap, count, width, mode)
        if args.expect_regression:
            assert decoded["snapshot_consistency"]["stable"] is False
            assert oracle["physical"][0]["event_count"] == 2 * count
            assert len(oracle["physical"][0]["records"]) == 2
            status = "REPRODUCED"
        else:
            verify(decoded, oracle)
            status = "PASS"
        results.append({"status": status, "oracle": oracle, "decoded": decoded})
        print(f"thread-generation {status}: events={cap} workers={count} slots={width} mode={mode}")
    if not args.expect_regression:
        decoded, oracle = sample(binary, 8, 1, seed_generation=0xFFFFFFFF)
        assert decoded["complete"] is False
        assert decoded["header"]["status"] & fmt.STATUS_THREAD_OVERFLOW
        assert oracle["physical"][0]["generation"] == 0xFFFFFFFF
        assert not oracle["physical"][0]["records"], "exhausted generation was reused"
        results.append({"status": "PASS", "case": "generation_exhaustion", "oracle": oracle, "decoded": decoded})
        print("thread-generation PASS: uint32 generation exhaustion is disclosed without aliasing")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"status": "REPRODUCED" if args.expect_regression else "PASS",
                                      "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                                      "cases": results}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
