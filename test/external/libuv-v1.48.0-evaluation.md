# libuv v1.48.0 bounded evaluation

**Overall: PASS for the recorded scope.** This report covers a pinned upstream static-library build, a timer-loop workload, fatal-signal capture, verified symbol/source lookup, and local MCP source/relation calls. It does not establish broad workload coverage or production readiness.

## Evaluation identity

| Field | Value |
| --- | --- |
| Project | libuv, `https://github.com/libuv/libuv.git`, tag `v1.48.0` |
| Project commit | `e9f29cb984231524e3931aa0ae2c5dae1a32884e` |
| FaultDebug commit | `b77fedb65e923d25b71b71dd95ba300ca3651cf8` |
| FaultDebug worktree | Dirty; source/config tree SHA-256 `353c27433d4234cee2a4a61b3577f26b6ba3e9ef4b0e92b14ce8f4fec62711e6` |
| Runtime library SHA-256 | `287bcdc6f5da0ea20fb09a1cb3036f39d1885a5c870da9fb9bf07cb220554de7` |
| Evaluated | 2026-10-01 13:30 UTC |
| Host | Linux x86_64, WSL2 kernel `6.18.40.1-microsoft-standard-WSL2` |
| Tools | Clang 18.1.3, CMake 3.28.3, Ninja 1.11.1, Python 3.12.3, Git 2.43.0, GNU readelf 2.42 |
| Evaluator | `test/external/libuv_v1_48_0.py` |
| Evidence directory | `/tmp/faultdebug-libuv-v1.48.0/evidence-20261001T133036Z-379298/` |
| JSON report | `/tmp/faultdebug-libuv-v1.48.0/report.json` |

The evaluator verified the project commit and clean source checkout before building. The caller supplied checkout is read-only: a separate mismatched-pin check returned `FAIL` with expected and observed SHA values and confirmed the checkout remained at its original commit.

## Gate results

| Gate | Result | Evidence |
| --- | --- | --- |
| Build integration | **PASS** | Separate original and instrumented CMake/Ninja builds and drivers succeeded. The two libuv archives have different SHA-256 values. |
| Provenance | **PASS** | Pinned source commit and clean status verified; original and instrumented driver Build IDs recorded; instrumented binary and compile database used to create the immutable bundle. |
| Runtime trace | **PASS** | Timer-loop workload produced committed events; resolved event functions include `uv_loop_init` and `uv__calloc`. |
| Fault capture | **PASS** | Both drivers reached the fixed SIGABRT path; the instrumented run reported signal 6 in the target summary and verified artifact. Artifact SHA-256: `900f023eb342d2fce857e7586bb210bbb3b5a330af92ecdb3f5a6c8f181b786a`. |
| Symbol and source resolution | **PASS** | Captured addresses resolved against the Build-ID-matched bundled binary and pinned libuv source index; resolved definitions include upstream `src/*.c` files. |
| MCP query | **PASS** | `open_fault`, `get_thread_trace`, `get_function_source`, and `get_call_relations` were invoked. The source call resolved `uv_loop_init`; relation results retain `static_index` evidence class. |
| Reproducibility | **NOT RUN** | This report does not include an independent comparison of two preserved evaluator reports. |
| Overhead and scope | **NOT RUN** | No baseline/instrumented performance study was run. |
| Failure evidence | **NOT RUN** | Malformed artifact, mismatch, and overflow matrix is outside this bounded run. The separate caller-source pin mismatch behavior check is recorded above. |

## Reproduction

Run with the project virtual environment and the pinned source checkout:

```sh
.venv/bin/python test/external/libuv_v1_48_0.py \
  --source /path/to/libuv-v1.48.0 \
  --runtime-dir build \
  --work-dir /tmp/faultdebug-libuv-v1.48.0 \
  --output /tmp/faultdebug-libuv-v1.48.0/report.json
```

The driver schedules a zero-delay libuv timer, enters the event loop, and raises SIGABRT from its callback. The expected signal and `uv_*` source requirement are fixed in the evaluator and are not derived from the observed report. Generated builds, bundle, artifact, and MCP JSON remain under `/tmp`.
