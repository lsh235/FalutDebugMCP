# Clang 18 build and CI

v0.1.0 supports Ubuntu 24.04 x86_64 with Clang 18, CMake, Ninja, and Python
3.12. The native build enables `CMAKE_EXPORT_COMPILE_COMMANDS` and emits a
GNU Build ID for the runtime and every target passed to
`faultdebug_instrument()`.

On a machine with the Ubuntu repositories available, install the toolchain with:

```sh
sudo apt-get update
sudo apt-get install clang-18 llvm-18-tools cmake ninja-build python3.12
```

When sudo or system installation is unavailable, the repository bootstrap
downloads the same Ubuntu packages and extracts them under the ignored `.tools/`
directory:

```sh
scripts/bootstrap_native.sh
source .tools/env.sh
clang --version
llvm-symbolizer --version
```

Configure and build the supported fixture set with:

```sh
source .tools/env.sh
CC=clang CXX=clang++ cmake -S . -B build-clang -G Ninja \
  -DFAULTDEBUG_BUILD_TESTS=ON
cmake --build build-clang --parallel 2
python3 -m faultdebug.cli run -- build-clang/test/fd_c_chain 16
```

The GitHub Actions workflow in `.github/workflows/ci.yml` keeps the jobs small:
one job compiles Python and builds the sdist/wheel, and one Ubuntu 24.04 job
installs Clang 18 and runs the CMake/runtime smoke. CI disables provenance for
the smoke build so it does not require Python package installation; release
builds should leave provenance enabled.

The scheduled/manual `.github/workflows/v12-release-gate.yml` is the required
v1.2 release-profile workflow. It runs separate core and gRPC profiles on
Ubuntu 24.04, enables source/build provenance, executes the named CTest suite,
replays installed C/C++ and compatibility checks, then builds wheel/sdist and
installs the wheel into a separate environment. The wheel consumer runs outside
the checkout and checks the CLI, doctor, clean and opt-in trace behavior, and
MCP stdio success/error calls. `test/v12_release_gate.py` returns nonzero for a
failed or missing required row; core-profile optional gRPC `NOT RUN` rows stay
visible in the uploaded JSON and do not become `PASS`. Each profile uploads its
report and CTest log even when a required check fails.

The wheel includes both executable compiler wrappers, and the installed doctor
resolves them beside the active CLI. The consumer prefers a separate virtual
environment; hosts without `ensurepip` use a reported install-prefix fallback.
Wheel build isolation is used when available; a host missing `ensurepip` may use
its already provisioned build backend without isolation.
