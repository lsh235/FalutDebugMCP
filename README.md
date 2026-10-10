# FaultDebug

> Turn C/C++ crashes into source-verified execution-flow reports.
> Follow recorded calls across services, inspect the fault location, and see
> which evidence is missing.

[![Native candidate](https://img.shields.io/badge/native-v1.2.0--rc.1-orange)](https://github.com/lsh235/FaultDebugMCP/releases/tag/v1.2.0-rc.1)
[![Release gates](https://img.shields.io/github/actions/workflow/status/lsh235/FaultDebugMCP/v12-release-gate.yml?branch=main&label=release%20gates)](https://github.com/lsh235/FaultDebugMCP/actions/workflows/v12-release-gate.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![Clang 18](https://img.shields.io/badge/Clang-18-orange)](https://clang.llvm.org/)
[![Apache--2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

**Guides:** [English](README.md) · [한국어](README.ko.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

**[Try the interactive demos](https://lsh235.github.io/FaultDebugMCP/)** ·
**[Watch the 42-second walkthrough](https://lsh235.github.io/FaultDebugMCP/assets/demo.webm)** ·
**[Run the fixture locally](#try-the-prebuilt-demo)** ·
[Share feedback](https://github.com/lsh235/FaultDebugMCP/discussions)

![Actual payment crash report with observed service flow](docs/assets/showcase-payment.png)

Explore a [successful checkout](https://lsh235.github.io/FaultDebugMCP/reports/success/report.html),
[payment SIGILL](https://lsh235.github.io/FaultDebugMCP/reports/payment_crash/report.html),
[inventory timeout](https://lsh235.github.io/FaultDebugMCP/reports/inventory_timeout/report.html),
or [native C SIGSEGV](https://lsh235.github.io/FaultDebugMCP/reports/c-sigsegv/report.html).
The online examples are recorded synthetic executions; the local fixture
reproduces real Docker service interactions and native captures.

## Try the prebuilt demo

Requires **Linux x86_64, a local Docker Engine and Docker Compose**. After cloning,
one script downloads the checksummed development demo image, runs eight services
through three outcomes and serves the reports. No host Python, Clang or CMake
installation is needed.

~~~~sh
git clone https://github.com/lsh235/FaultDebugMCP.git
cd FaultDebugMCP
./scripts/try-demo.sh
~~~~

Open **http://127.0.0.1:18870/index.html** when the script prints the report URL.
Ctrl+C stops the report server. The analyzer uses the local Docker socket to
manage its own fixture containers. See [requirements and overrides](docs/showcase/README.md).
The shopping app is Python with an instrumented C++ boundary; these are native
boundary events, not Python stacks. Incomplete captures remain marked incomplete.

## Native tracing and inspection

FaultDebug combines a small C11 runtime, C/C++ build integration, and a Python
CLI/MCP inspector. The runtime records bounded function-entry and function-exit
events while an instrumented program runs. After the target exits, the local
launcher collects and validates the shared-memory trace and may write a
`.fault` artifact for a supported fatal signal or partial termination.

![FaultDebug capture and inspection flow](docs/assets/faultdebug-overview.svg)

FaultDebug is designed to preserve evidence and its limits. It does not guess
missing events, infer causality from process names or shared IDs, or present
static call-graph candidates as observed execution.

## Project status

The native package is **1.2.0rc1**; `v1.2.0-rc.1` is a pre-release candidate.
Main also includes offline service reports and generation-counter fixes.
Current-source core/gRPC and Docker N=8/16 gates pass locally and on GitHub;
see [the current-source validation](docs/v1.3-p0-01.md).
The prebuilt demo is a separate development snapshot, not a stable release.

Final independent acceptance and a fresh 30-minute soak after the generation
fix remain pending. The earlier RC soak was incomplete; its counts and source
scope are in [the historical validation](docs/v1.2-p3-01.md).
See the [v1.3 plan](docs/next-version-v1.3.md) for remaining work.

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

## Why FaultDebug

- Record function-level runtime events in a bounded C11 recorder without
  requiring a tracing daemon or remote service.
- Tie source lookup to captured build inputs, hashes, and module Build IDs so a
  changed checkout is not mistaken for the source that produced an artifact.
- Use a local CLI or read-only MCP server to inspect artifacts and explicitly
  separate observed events, static candidates, and unresolved evidence.
- Keep overflow, incomplete snapshots, and missing optional evidence visible.

Practical examples: [payment process crash](docs/case-studies/payment-crash.md),
[inventory timeout](docs/case-studies/inventory-timeout.md), and
[native C SIGSEGV](docs/case-studies/c-sigsegv.md).

The runtime currently targets Linux on Ubuntu 24.04 x86_64. It is a diagnostic
and forensic aid, not a lossless recorder: inspect artifact completeness and
drop counts before drawing conclusions.

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
git clone https://github.com/lsh235/FaultDebugMCP.git
cd FaultDebugMCP
```

Install the native toolchain and Python environment:

```sh
sudo apt-get update
sudo apt-get install clang-18 llvm-18-tools cmake ninja-build python3.12 python3.12-venv

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

If you prefer [`uv`](https://docs.astral.sh/uv/), replace the three Python
environment/install commands above with the following. The apt-installed
native toolchain is still required for tracing builds:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
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

Create a shareable fault document and interactive execution-flow view:

```sh
.venv/bin/fault-debug fault-report artifacts/fault-<pid>.fault \
  --bundle build/bundle --output reports/incident-001
# Open reports/incident-001/report.html; document: report.md; evidence: report.json
```

The standalone HTML highlights the captured fault PC and retained function
events, supports thread selection, search, dark/light themes, and document
printing to PDF. Gaps, unresolved addresses, and static call candidates remain
explicit. Use `--language ko` for Korean and `--max-events 200` for a larger
window. See the [fault-flow report guide](docs/fault-flow-report.md).

![Captured SIGILL and verified fault source in the execution-flow report](docs/assets/fault-flow-report.png)

Try a larger, real cross-process workload with the
[N-process shopping fault lab](docs/shopping-fault-lab.md): eight core Docker
services plus optional risk workers, concurrent orders, controlled failures,
and a report of observed service-to-service RPC flow and failure evidence.

```sh
docker build -f test/shop/Dockerfile -t faultdebug-shop:dev .
.venv/bin/python test/shop/run.py --processes 16 --requests 24 --concurrency 4 \
  --scenarios success payment_decline --output build/shop-scale
```

![Observed payment crash and HTTP failure propagation across shopping services](docs/assets/shopping-fault-report.png)

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
public issues. To run the MCP inspector in a container with a read-only artifact
mount, see the [Docker MCP guide](docs/mcp-container.md).

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
