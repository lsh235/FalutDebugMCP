# Fixture and runner contract

The fixtures are deliberately independent of the recorder implementation. They
provide cross-translation-unit C11/C++17 call chains, recursion, real x86-64
fault instructions, thread pressure, ring wrapping, thread-slot reuse, and a
startup-linked module. Build flags are `-O0 -g -fno-lto`, disabled sibling-call
optimization, frame pointers, PIE, and linker Build IDs. Runtime helper frames
must be excluded by the product's own policy; fixture functions remain
`noinline` and use volatile side effects.

Run from the repository root:

```sh
python3 test/run_tests.py --suite smoke --output test-results/smoke
FD_LAUNCHER='/path/to/fault-debug' python3 test/run_tests.py \
  --suite acceptance --output test-results/acceptance
FD_LAUNCHER='/path/to/fault-debug' python3 test/run_tests.py \
  --suite soak --output test-results/soak
```

`FD_LAUNCHER` is required to claim runtime PASS. Without it, the runner builds
the fixtures and records the execution checks as `NOT RUN`; it never substitutes
direct execution for launcher/collector validation. Reports are JSON and retain
commands, stderr, return codes, durations, limits, and per-check status. Failed
run directories are preserved.

The smoke, acceptance, and soak runners return 0 for `PASS`, 1 for `FAIL`, and
2 for `NOT RUN`. Acceptance also checks each malformed artifact in isolation
after a normal-control oracle pass. A `NOT RUN` row remains visible in the JSON
report and never counts as a successful validation.

The acceptance suite uses genuine faults: `mprotect(PROT_NONE)`/load for
`SIGSEGV`, a file mapping load beyond EOF for `SIGBUS`, `ud2` for `SIGILL`, an
x86 `divl` with zero divisor for `SIGFPE`, and `abort()` for `SIGABRT`. The
launcher must validate signal origin (`si_code`), PC, and fault-address validity
where applicable. A normal clean run must have no fault file; a separate chain
run may terminate after the completed chain to inspect events before a fault.

## Asynchronous gRPC proxy gate

When the optional C++ gRPC fixture is present, run its integration gate with:

```sh
python3 test/grpc_proxy_test.py \
  --build-dir build \
  --output test-results/grpc-proxy
```

The gate builds the `fd_grpc_async_proxy` target when necessary, starts the
asynchronous upstream server and synchronous client as ordinary processes,
and launches only the proxy through `faultdebug run`. The default scenario
causes the proxy to dereference a null pointer after its downstream
CompletionQueue response; this preserves a real SIGSEGV in the proxy process
while the client still receives the response. The resulting `.fault` file and
JSON report are retained. The gate also runs a clean `max-calls=1` pass and
requires that it exits normally without creating a fault file. Set
`FAULTDEBUG_GRPC_PROXY_BINARY` when the executable is outside the normal CMake
build tree. `--direct` is available for debugging a manually supplied target;
the normal three-process orchestration is required for the proxy proof.

The report has separate `PASS`, `FAIL`, and `NOT RUN` states. Its independent
FDAR checks validate the checksum, crash signal and program counter, captured
module range, generation and sequence fields, enter/exit prefixes, and
retained function addresses. It also independently resolves and checks the
four application-owned RPC boundary functions (`received`, `forwarded`,
`response`, and `fault_after_response`). Source resolution is independently attempted with
`llvm-symbolizer`; the FaultDebug bundle/inspect result is retained only as
corroborating evidence and is not used as the test oracle. Missing gRPC tools,
the CMake build tree, or the fixture binary produce `NOT RUN` so an absent
optional dependency cannot be mistaken for a successful integration test.

## v0.2.0 external clean-copy gate

`v020_external_gate.py` requires an external clone and explicit commands. It
copies the clone to a new temporary directory and runs every command there.
Commands are shell strings and may use `{root}`, `{build}`, `{binary}`, and
`{artifact}` placeholders. Relative `--binary` and `--artifact` paths resolve
below the clean copy. Absolute paths are accepted only when they are inside the
supplied source clone, preventing accidental reads from the original checkout.

Example:

```sh
.venv/bin/python test/v020_external_gate.py \
  --source /tmp/fmt-clone \
  --build-command 'cmake -S {root} -B {build} -G Ninja && cmake --build {build} -j2' \
  --run-command 'faultdebug run --artifact-dir {build}/artifacts -- {binary}' \
  --binary build/fmt-test \
  --artifact build/artifacts/fault.fault \
  --mcp-result build/mcp-result.json \
  --evaluator-command 'python3 /path/to/independent_evaluator.py --artifact {artifact} --binary {binary}' \
  --output /tmp/fd-v020/report.json
```

If the clone, binary, artifact, or evaluator tool is unavailable, the report is
`NOT RUN`; expected values are never generated from analyzer output.

## v1.2 collector wait and snapshot consistency checks

The CTest gates `fd_python_collector_agent_bounded`,
`fd_python_snapshot_consistency`, and `fd_python_snapshot_stress` cover the
collector readiness deadline, an accepted idle Unix-socket peer, deterministic
event/RPC write interleavings, and native event/RPC ring wrap with live mmap
reads and thread-slot reuse. The stress fixture uses deliberately small rings;
it verifies that observed unstable records and loss never leave the report
marked complete. It is a short race/contract check and does not replace the
1800-second release soak.

## v1.2 paired benchmark evidence

The paired C++ call workload and opt-in normal-exit trace contract are covered by
`test/doctor_benchmark.py` and the external matrix driver
`test/external/cpp_call_benchmark_v1_1.py`. The P2-02 result documents the four
workloads, exact independent checksum contract, per-sample artifact identity,
timing split, and declared overflow result in
[`docs/v1.2-p2-02.md`](../docs/v1.2-p2-02.md).

## v1.2 pinned libuv repeatability

`test/external/libuv_v1_48_0.py` evaluates the pinned v1.48.0 source, while
`test/external/compare_libuv_runs.py` compares two preserved reports, validates
their source/build/signal/MCP semantics, and creates hash-verified evidence
archives. The stdio gate uses the external artifact for five required tools and
an allowlist error case. See [`docs/v1.2-p2-03.md`](../docs/v1.2-p2-03.md) for
the two run identities, hashes, and limits.

## v1.2 required release gate

Run the provenance-enabled core profile with:

```sh
CC=clang-18 CXX=clang++-18 python3 test/v12_release_gate.py \
  --profile core --build-dir build-v12-core \
  --install-prefix build-v12-core/install \
  --work-dir build-v12-core/release-work \
  --output output/v12-core/report.json
```

Use `--profile grpc` to require the optional gRPC fixture and scenario rows.
The workflow `.github/workflows/v12-release-gate.yml` runs both profiles on a
schedule and by manual dispatch. It uploads JSON reports and CTest logs on both
success and failure. The gate builds and installs a wheel into a separate
environment, changes working directory outside the checkout, then verifies the
installed CLI, doctor, ordinary and opt-in trace behavior, and MCP stdio.
The consumer prefers a separate virtual environment. Hosts without `ensurepip`
use a reported install-prefix fallback; wheel build isolation likewise falls
back only when the host cannot create its temporary build environment.

## v0.8 session and collector gate

Run the independent v0.8 checks from the repository root:

```sh
python3 test/v08_validation.py --output test-results/v08
python3 test/v08_validation.py --build-dir build --grpc-build-dir build-grpc-check \
  --output test-results/v08-full
```

The gate launches two peer processes and a third process that writes a partial
SIGSEGV artifact. It expects one explicit peer RPC relation, a shared session
identity with three distinct participants, and no relation inferred from the
crasher or shared identity. It also starts the resident agent and launches
three Python targets through `faultdebug.run`: two peers are snapshotted over
the Unix socket/SCM_RIGHTS API while the third crashes, then the agent is
restarted and its generation and retained spool are checked. Spool rotation,
page-union and SQLite reopen behavior, schema-v2 evidence-store pagination,
trust states, and corruption quarantine are checked independently. The v0.7
regression gate is replayed when requested. A missing optional build-only
regression remains `NOT RUN`; no help-token or module-presence shortcut is
counted as `PASS`.

## v0.9 MCP and semantic gRPC gate

Run with the project environment so the MCP SDK is available:

```sh
.venv/bin/python test/v09_validation.py --grpc-build-dir build \
  --output test-results/v09
```

The gate performs real MCP stdio `initialize`, `tools/list`, and `tools/call`
requests. It verifies the bounded page-2 incident slice (`100` returned from
`500` independently generated events), keeps observed/static/unresolved
evidence in separate fields, and checks source file, line range, and SHA-256
against the immutable bundle manifest. The gRPC oracle executes deadline,
two-worker, streaming, and retry paths when the v0.9 fixture binary advertises
them; a general build without the optional gRPC binary reports those optional
checks as `NOT RUN`. A gRPC binary must be run with its matching runtime
directory, for example the `build` tree supplied to the command.

## v1.0 install and release gate

The v1.0 gate consumes an installed prefix through a separate CMake project.
It builds C and C++ targets with the installed `FaultDebugLegacy.cmake`
module, checks normal termination, runs a real null-store SIGSEGV through the
launcher, verifies artifact hashes and source/index bundle citations, then
executes the capability CLI, MCP `get_capabilities`/`check_store` exchange,
legacy-store migration, malformed-artifact quarantine, native CTest, and the
v0.9 regression gate.

```sh
prefix=$(mktemp -d)
.venv/bin/python test/v10_validation.py \
  --python .venv/bin/python \
  --build-dir build \
  --grpc-build-dir build \
  --install-prefix "$prefix" \
  --ctest-dir build \
  --output test-results/v10
```

The report records `PASS`, `FAIL`, or `NOT RUN` per gate, tool versions,
configuration paths, SHA-256 values, signal/incident metadata, bounded trace
counts, and source citation hashes. Keep the interpreter inside the virtual
environment so libclang and the MCP SDK are available.
