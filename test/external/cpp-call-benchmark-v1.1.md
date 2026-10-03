# v1.1 non-faulting C++ function-call benchmark

**Run status: PASS for the declared workload and protocol.** The paired benchmark CLI completed all warmups and measurements, both binaries produced the same independently counted workload result through `faultdebug run`, and the separate direct trace inspection recorded no dropped events. Timing results are descriptive; no speed or overhead threshold was applied.

## Workload and environment

The fixed C++17 workload starts 32 workers behind a POSIX barrier. Each worker executes 500 iterations of the call chain `step -> combine -> leaf`, for 48,000 counted calls per process. Worker-local state makes the final checksum deterministic. The source SHA-256 is `e7cf67e81305ed166d6eb072cf98b7e06487e8921e1b66448e031030539b65dd`.

| Field | Value |
| --- | --- |
| Host | Linux x86_64, WSL2 kernel `6.18.40.1-microsoft-standard-WSL2` |
| Compiler | Clang 18.1.3 (`.tools/bin/clang++`) |
| Python | 3.12.3 (`.venv/bin/python`) |
| GNU nm / readelf | Binutils 2.42 |
| FaultDebug runtime SHA-256 | `287bcdc6f5da0ea20fb09a1cb3036f39d1885a5c870da9fb9bf07cb220554de7` |
| Work directory | `$WORK_DIR` (local to the original validation run) |
| Full checked-in report | `test/external/cpp_call_benchmark_v1_1.json` |
| Raw CLI report | `$WORK_DIR/benchmark-cli.json` (not distributed; SHA-256 `1696baac713b0526f45ec16cb0ef4b162ae2b9ccb568dcc39386d7aae7de92f3`) |

The checked-in JSON keeps the measurements and commands but replaces
machine-specific repository and temporary-directory prefixes with `$REPO` and
`$WORK_DIR`. Those path tokens are descriptive placeholders; the original
host-local binaries and raw CLI report are not distributed.

## Build and recorder checks

The baseline was compiled with Clang 18 at `-O0 -g`, with sibling-call optimization and LTO disabled, and linked to the runtime so both variants use the same launcher handshake. The instrumented binary was built through `scripts/faultdebug-cxx` with the same optimization/debug settings. `nm -D` found neither instrumentation hook in the baseline and both `__cyg_profile_func_enter` and `__cyg_profile_func_exit` in the instrumented binary.

| Check | Result | Evidence |
| --- | --- | --- |
| Baseline and instrumented build | **PASS** | Both commands exited 0 and both binaries have distinct Build IDs. |
| Hook selection | **PASS** | No hooks in baseline; both expected hooks in instrumented binary. |
| Paired smoke through `faultdebug run` | **PASS** | Both exited normally and printed `threads=32 iterations_per_thread=500 function_calls=48000 checksum=9655063894456135093`. |
| Direct in-memory trace | **PASS** | 33 thread records, 100,290 retained event records, `dropped_count=0`; runtime status flags `1` (`READY` only); target signal is null; no artifact was written for normal exit. |
| Paired benchmark commands | **PASS** | 2 warmups per target and 7 alternating measurement pairs; 14/14 measured commands exited 0. |
| Artifact-size and decoded-loss CLI metrics | **NOT RUN** | The workload exits normally and the benchmark invocation has no artifact-directory placeholder. Direct in-memory trace counters above provide the no-drop check for this run. |

## Binaries

| Variant | Build ID | SHA-256 |
| --- | --- | --- |
| Baseline | `6c6dbb21c04cbc55b26c3587f70e40679f8b60e0` | `b3cbde4ab778933524cbc77138c83d50fa056f40bf295be1f91def551c3d4bc0` |
| Instrumented | `c28b289744043a6c77d65f1df9f1151c54ac03fc` | `78bb6900183cadb5c9b8e722a7c50d6b5271c143a7d9f5435251d647e23659a` |

Both workload binaries were retained under `$WORK_DIR`. The checked-in JSON
contains their recorded commands with path prefixes normalized to `$WORK_DIR`.

## Measurements

The benchmark CLI launches each variant through a small runner that invokes `faultdebug run`; the measured process time includes the Python launcher and collector handshake for both variants. GNU `/usr/bin/time` supplied user-plus-system CPU time and peak RSS. Throughput is the known 48,000 calls divided by measured process wall time.

| Metric | Baseline p50 | Instrumented p50 | Baseline p95 | Instrumented p95 |
| --- | ---: | ---: | ---: | ---: |
| Wall time (ms) | 113.711307 | 113.690469 | 113.889746 | 163.805025 |
| CPU time (ms) | 70 | 100 | 70 | 120 |
| Peak RSS (bytes) | 34,709,504 | 75,943,936 | 34,869,248 | 75,988,992 |
| Counted calls per second | 422,121.61 | 422,198.98 | 422,271.43 | 422,481.64 |

The instrumented-to-baseline wall-time p50 ratio is `0.9998167464560054`. The instrumented p95 includes a `163.805025 ms` outlier. These measurements include launcher and thread startup costs, and describe only this workload on this host.

## Excluded pilot

An earlier 500,000-iteration single-thread pilot reached runtime status flags `9` (`READY | EVENT_OVERFLOW`) with the 4,096-event per-thread ring. It had no artifact on normal exit, so an artifact-decoded loss count was unavailable. That pilot is excluded from the clean-trace performance evidence above; the final 32-worker workload holds all worker slots at the barrier and records zero dropped events.

## Reproduction

```sh
WORK_DIR="${TMPDIR:-/tmp}/faultdebug-cpp-call-benchmark"
.venv/bin/python test/external/cpp_call_benchmark_v1_1.py \
  --work-dir "$WORK_DIR" \
  --runtime-dir build \
  --python .venv/bin/python \
  --repeats 7 \
  --warmups 2 \
  --output "$WORK_DIR/report.json"
```
