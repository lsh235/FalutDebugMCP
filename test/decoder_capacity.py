#!/usr/bin/env python3
"""Exercise fixed physical thread-ring offsets at logical event capacities."""
from __future__ import annotations

import os
import mmap
import select
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.format import (
    EVENT,
    HEADER,
    MODULE,
    THREAD,
    THREAD_RING_STRIDE,
    collect_mapping,
)  # noqa: E402
from faultdebug.run import (
    CRASH_CAPACITY,
    EVENT_CAPACITY,
    MODULE_CAPACITY,
    SHM_SIZE,
    THREAD_CAPACITY,
    _runtime_environment,
)  # noqa: E402


def run_with_raw_oracle(binary: Path, event_capacity: int) -> dict[int, set[tuple[int, int, int]]]:
    shm_fd = os.memfd_create("faultdebug-decoder-capacity", os.MFD_CLOEXEC)
    ready_read, ready_write = os.pipe()
    process = None
    try:
        os.ftruncate(shm_fd, SHM_SIZE)
        threads_offset = HEADER.size
        modules_offset = threads_offset + THREAD_CAPACITY * THREAD_RING_STRIDE
        crashes_offset = modules_offset + MODULE_CAPACITY * MODULE.size
        header = HEADER.pack(
            0x31444646,
            1,
            HEADER.size,
            SHM_SIZE,
            0,
            EVENT_CAPACITY,
            THREAD_CAPACITY,
            MODULE_CAPACITY,
            CRASH_CAPACITY,
            os.getpid(),
            time.monotonic_ns(),
            0,
            0,
            threads_offset,
            modules_offset,
            crashes_offset,
            0,
        )
        os.pwrite(shm_fd, header, 0)
        command = [str(binary), "1"]
        env = _runtime_environment(command)
        env.update({
            "FAULTDEBUG_CONFIG": f"events={event_capacity},threads=2",
            "FAULTDEBUG_SHM_FD": str(shm_fd),
            "FAULTDEBUG_READY_FD": str(ready_write),
        })
        env.pop("FAULTDEBUG_DISABLE", None)
        process = subprocess.Popen(
            command,
            env=env,
            pass_fds=(shm_fd, ready_write),
            close_fds=True,
        )
        os.close(ready_write)
        ready_write = -1
        readable, _, _ = select.select([ready_read], [], [], 10)
        ready = os.read(ready_read, 1) if readable else b""
        if ready != b"R":
            process.kill()
            process.wait()
            raise AssertionError(f"native runtime did not become ready: {ready!r}")
        if process.wait(timeout=10) != 0:
            raise AssertionError("native multithreaded fixture did not exit cleanly")

        with mmap.mmap(shm_fd, SHM_SIZE, access=mmap.ACCESS_READ) as mapping:
            physical: dict[int, set[tuple[int, int, int]]] = {}
            for slot in (0, 1):
                ring_offset = threads_offset + slot * THREAD_RING_STRIDE
                thread = THREAD.unpack_from(mapping, ring_offset)
                generation = int(thread[1])
                committed: set[tuple[int, int, int]] = set()
                for index in range(event_capacity):
                    event_offset = ring_offset + THREAD.size + index * EVENT.size
                    event = EVENT.unpack_from(mapping, event_offset)
                    if event[6] == 1 and event[5] == generation:
                        committed.add((int(event[0]), int(event[5]), int(event[4])))
                if not generation or not committed:
                    raise AssertionError(f"raw native slot {slot} is empty: {thread}")
                physical[slot] = committed

            decoded = collect_mapping(mapping)
            decoded_by_slot = {
                int(row["slot"]): {
                    (int(event["sequence"]), int(event["generation"]), int(event["type"]))
                    for event in row["events"]
                }
                for row in decoded["threads"]
            }
        for slot in (0, 1):
            if decoded_by_slot.get(slot) != physical[slot]:
                raise AssertionError(
                    f"slot {slot} differs from raw native records at events={event_capacity}: "
                    f"raw={sorted(physical[slot])}, decoded={sorted(decoded_by_slot.get(slot, set()))}"
                )
        return physical
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        for fd in (ready_read, ready_write, shm_fd):
            if fd >= 0:
                os.close(fd)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: decoder_capacity.py PATH_TO_FD_THREADS")
    binary = Path(sys.argv[1]).resolve()
    if not binary.is_file():
        raise SystemExit(f"native thread fixture is missing: {binary}")

    for event_capacity in (1, 8, 4096):
        raw = run_with_raw_oracle(binary, event_capacity)
        print(
            f"decoder fixed-stride PASS events={event_capacity} "
            f"slots=0,1 raw_events={sum(map(len, raw.values()))}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
