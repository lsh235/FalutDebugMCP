#!/usr/bin/env python3
"""Exercise concurrent event/RPC wrap and thread-slot reuse during live reads."""
from __future__ import annotations

import argparse
import json
import mmap
import os
import pathlib
import select
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.format import HEADER, MAGIC, MODULE, THREAD_RING_STRIDE  # noqa: E402
from faultdebug.run import (  # noqa: E402
    CRASH_CAPACITY,
    EVENT_CAPACITY,
    MODULE_CAPACITY,
    SHM_SIZE,
    THREAD_CAPACITY,
    _runtime_environment,
)
from faultdebug.format import collect_mapping  # noqa: E402

STATUS_EVENT_OVERFLOW = 1 << 3


def run_stress(binary: pathlib.Path, output: pathlib.Path) -> dict[str, object]:
    shm_fd = os.memfd_create("faultdebug-live-snapshot-stress", os.MFD_CLOEXEC)
    ready_read, ready_write = os.pipe()
    process: subprocess.Popen | None = None
    snapshots: list[dict] = []
    try:
        os.ftruncate(shm_fd, SHM_SIZE)
        threads_offset = HEADER.size
        modules_offset = threads_offset + THREAD_CAPACITY * THREAD_RING_STRIDE
        crashes_offset = modules_offset + MODULE_CAPACITY * MODULE.size
        initial_header = HEADER.pack(
            MAGIC, 1, HEADER.size, SHM_SIZE, 0, EVENT_CAPACITY, THREAD_CAPACITY,
            MODULE_CAPACITY, CRASH_CAPACITY, os.getpid(), time.monotonic_ns(), 0, 0,
            threads_offset, modules_offset, crashes_offset, 0,
        )
        os.pwrite(shm_fd, initial_header, 0)
        command = [str(binary), "3"]
        env = _runtime_environment(command)
        env.update({
            "FAULTDEBUG_CONFIG": "events=8,threads=2",
            "FAULTDEBUG_SHM_FD": str(shm_fd),
            "FAULTDEBUG_READY_FD": str(ready_write),
        })
        env.pop("FAULTDEBUG_DISABLE", None)
        process = subprocess.Popen(command, env=env, pass_fds=(shm_fd, ready_write), close_fds=True)
        os.close(ready_write)
        ready_write = -1
        readable, _, _ = select.select([ready_read], [], [], 8)
        ready = os.read(ready_read, 1) if readable else b""
        if ready != b"R":
            raise AssertionError(f"native snapshot stress target did not become ready: {ready!r}")

        start = time.monotonic()
        with mmap.mmap(shm_fd, SHM_SIZE, access=mmap.ACCESS_READ) as mapping:
            while len(snapshots) < 300 and time.monotonic() - start < 1.5:
                snapshots.append(collect_mapping(mapping))
                time.sleep(0.003)
            returncode = process.wait(timeout=15)
            if returncode != 0:
                raise AssertionError(f"native stress target exited {returncode}")
            final_report = collect_mapping(mapping)

        if len(snapshots) < 20:
            raise AssertionError(f"too few live snapshots were collected: {len(snapshots)}")
        if not int(final_report["header"]["status"]) & STATUS_EVENT_OVERFLOW:
            raise AssertionError("small event ring did not disclose native event overflow")
        if final_report["complete"] is not False:
            raise AssertionError("overflowed live snapshot was incorrectly marked complete")
        rpc = final_report.get("rpc") or {}
        rpc_header = rpc.get("header") or {}
        if int(rpc_header.get("dropped_count", 0)) <= 0 or rpc.get("complete") is not False:
            raise AssertionError(f"RPC ring did not disclose wrap/loss: {rpc}")

        generations = {
            (int(thread["slot"]), int(thread["generation"]))
            for report in snapshots
            for thread in report.get("threads", [])
        }
        reused_slots = sorted({slot for slot, generation in generations if generation > 1})
        if not reused_slots:
            raise AssertionError(f"stress run did not observe a reused thread slot: {sorted(generations)}")

        unstable_snapshots = 0
        for report in snapshots:
            consistency = report.get("snapshot_consistency") or {}
            rpc_consistency = (report.get("rpc") or {}).get("snapshot_consistency") or {}
            if not consistency.get("stable", True):
                unstable_snapshots += 1
                if report.get("complete") is not False:
                    raise AssertionError("unstable event snapshot retained complete=true")
            if not rpc_consistency.get("stable", True) and (report.get("rpc") or {}).get("complete") is not False:
                raise AssertionError("unstable RPC snapshot retained complete=true")

        result = {
            "status": "PASS",
            "snapshots": len(snapshots),
            "unstable_snapshots": unstable_snapshots,
            "reused_thread_slots": reused_slots,
            "thread_generations_observed": len(generations),
            "event_dropped_by_thread": sum(int(row.get("dropped_count", 0)) for row in final_report["threads"]),
            "rpc_event_count": int(rpc_header.get("event_count", 0)),
            "rpc_dropped_count": int(rpc_header.get("dropped_count", 0)),
            "final_complete": final_report["complete"],
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        for fd in (ready_read, ready_write, shm_fd):
            if fd >= 0:
                os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    result = run_stress(ns.binary.resolve(), ns.output.resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
