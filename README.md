# FaultDebug

FaultDebug is a local C/C++ fault-evidence recorder and inspection toolkit. A
small C11 runtime records bounded function-entry and function-exit events while
an instrumented program runs. The Python launcher collects the shared-memory
trace after the program exits, validates it, and writes a `.fault` artifact
when a supported fatal signal or partial termination occurs.

FaultDebug is designed to preserve evidence and its limits. It does not guess
missing events, infer causality from process names or shared IDs, or present
static call-graph candidates as observed execution.

## Project status

The package and native project version remain **1.1.0**. Work toward v1.2 is in
progress; this source tree is not a v1.2 release. Local core and gRPC release
profiles, both GitHub-hosted required profiles, and the 30-minute soak have
passed. An independent acceptance review has not run yet. The soak trace was
incomplete and records event loss; see the [v1.2 plan](docs/next-version-v1.2.md)
and [validation report](docs/v1.2-p3-01.md) for scope and limits.

## What it provides

- **Bounded runtime tracing:** per-thread event rings, committed-record checks,
  module identity, signal metadata, and explicit overflow/partial status.
- **Post-exit collection:** the launcher owns the shared-memory descriptor and
  readiness handshake; collection happens after the target exits.
- **Verified source lookup:** immutable source snapshots, compile databases,
  Build IDs, and hashes are checked before source-backed inspection.
- **Local evidence workflows:** CLI and read-only MCP tools for artifact
  inspection, process/session grouping, evidence-store queries, and explicitly
  supported RPC/IPC relationships.
- **Build integration:** CMake helpers and compiler wrappers for C/C++ builds,
  including opt-in source-selection profiles.

Normal successful runs do not write a fault artifact unless
`--collect-success` is requested. A crash artifact may still be incomplete;
check its trace, dropped-event, snapshot, and collector status before relying on
it.

## Supported environment

The documented support target is Ubuntu 24.04 x86_64 with Python 3.12, Clang
18, CMake 3.20 or newer, and Ninja. The recorder is C11; the native fixtures
also exercise C++17. Other platforms and compiler versions are outside the
current support commitment.

Python dependencies are pinned in [`pyproject.toml`](pyproject.toml):
`libclang`, `pyelftools`, and the MCP SDK. Fault artifacts, source bundles, and
the MCP interface are local-only. Remote transport and encryption are not
provided.

## Quick start

Clone the repository:

```sh
git clone https://github.com/lsh235/FalutDebugMCP.git
cd FalutDebugMCP
```

Install the native toolchain and Python environment:

```sh
sudo apt-get update
sudo apt-get install clang-18 llvm-18-tools cmake ninja-build python3.12 python3.12-venv

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

Configure and build the runtime plus the native fixtures:

```sh
cmake -S . -B build -G Ninja \
  -DCMAKE_C_COMPILER=clang-18 \
  -DCMAKE_CXX_COMPILER=clang++-18 \
  -DFAULTDEBUG_PYTHON_EXECUTABLE="$PWD/.venv/bin/python" \
  -DFAULTDEBUG_BUILD_TESTS=ON
cmake --build build --parallel 2
```

Check the local environment and run a fixture:

```sh
.venv/bin/fault-debug doctor
.venv/bin/fault-debug capabilities
.venv/bin/fault-debug run --artifact-dir artifacts -- build/test/fd_c_chain 16
```

The normal fixture exits successfully and does not create a `.fault` file.
To exercise a SIGSEGV capture, run:

```sh
.venv/bin/fault-debug run --artifact-dir artifacts -- build/test/fd_signals 11
```

The target's SIGSEGV produces the usual signal-based shell status (139) and a
`fault-<pid>.fault` artifact under `artifacts/`. The artifact is evidence of
the recorded run, not a guarantee that every event was retained.

For builds without system packages, see the repository's
[Clang 18 setup](docs/clang18-ci.md). For the complete validation matrix, see
[`test/README.md`](test/README.md).

## Inspecting and sharing evidence

Inspect an artifact locally:

```sh
.venv/bin/fault-debug inspect artifacts/fault-<pid>.fault
```

Source and call-relation lookup requires a verified bundle. Create an index
from the CMake compilation database and bundle the captured source and target
binary:

```sh
.venv/bin/fault-debug index build/compile_commands.json -o build/index.json
.venv/bin/fault-debug bundle \
  --source-root build/faultdebug-source-snapshot/files \
  --index build/index.json \
  --binary build/test/fd_c_chain \
  --output build/bundle
.venv/bin/fault-debug inspect artifacts/fault-<pid>.fault --bundle build/bundle
```

Bundles bind source and index data to the binary Build ID and hashes. Missing
or mismatched inputs fail explicitly; the current worktree is not substituted
for missing captured source.

The MCP server uses stdio and restricts artifact access to the configured root.
For MCP clients that accept the common `mcpServers` configuration shape, use
absolute paths for the installed CLI and artifact directory:

```json
{
  "mcpServers": {
    "faultdebug": {
      "command": "/absolute/path/to/.venv/bin/fault-debug",
      "args": ["mcp", "--root", "/absolute/path/to/artifacts"]
    }
  }
}
```

The server is read-only. It does not upload artifacts or contact a remote
service. Do not expose sensitive fault artifacts, bundles, or source paths in
public issues.

## Evidence rules

FaultDebug keeps these result classes separate:

- **Observed:** committed runtime records and explicitly matching RPC/IPC
  endpoints present in the captured evidence.
- **Static candidates:** possibilities from source or compilation data; these
  are not proof that a function executed.
- **Unresolved:** missing, ambiguous, partial, malformed, or untrusted evidence.

A shared trace ID, parent PID, function name, or timestamp alone does not prove
cross-process causality. The semantic RPC sidecar is optional and versioned;
older artifacts remain readable and report unavailable RPC evidence as
unresolved. See the [RPC evidence contract](docs/rpc-analysis-v1.md) and
[artifact format](docs/format.md).

## Development

Run the named native tests and launcher acceptance suite:

```sh
ctest --test-dir build --output-on-failure
FD_LAUNCHER="$PWD/.venv/bin/fault-debug" \
  .venv/bin/python test/run_tests.py --suite smoke --output test-results/smoke
```

Changes to artifact, ABI, source-bundle, or MCP contracts should include
malformed-input and compatibility coverage. The v1.2 profile runner and
scheduled/manual GitHub Actions workflow are documented in
[`docs/clang18-ci.md`](docs/clang18-ci.md). Report files, build trees, and
`.fault` artifacts are generated locally and are not part of the source upload.

Before opening a pull request, read
[`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`SECURITY.md`](SECURITY.md). The project is licensed under
[Apache-2.0](LICENSE); third-party notices are in [`NOTICE`](NOTICE).

## Documentation

- [v1.2 development plan and acceptance gates](docs/next-version-v1.2.md)
- [v1.2 baseline and reproduction commands](docs/v1.2-baseline.md)
- [v1.0 capability and support contract](docs/v1.0.md)
- [CMake, Meson, Bazel, and wrapper integration](docs/build-integration-v1.1.md)
- [Selective instrumentation profiles](docs/selective-instrumentation.md)
- [Local evidence store](docs/evidence-store-v080.md)
- [Session manifests](docs/session-manifest.md)
- [Incident queries](docs/incident-query-v090.md)
- [Roadmap](ROADMAP.md)
