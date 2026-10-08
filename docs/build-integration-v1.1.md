# Meson and Bazel wrapper integration (v1.1)

The v1.1 build-system fixtures reuse `scripts/faultdebug-cc`, so source-path
allowlists and exclusions have the same meaning as the Make/autotools wrapper
documented in [selective-instrumentation.md](selective-instrumentation.md).
The include expression is an allowlist; a matching exclude expression wins.
Build systems must pass source paths as ordinary compiler arguments because
the wrapper does not inspect response-file contents.

## Meson

The minimal project in `test/build_systems/meson/` compiles one C++ source, one
allowlisted C source, and one excluded generated C source. Build it with a
FaultDebug runtime already built in `build/`:

```bash
FAULTDEBUG_REAL_CC=clang \
FAULTDEBUG_REAL_CXX=clang++ \
FAULTDEBUG_RUNTIME_DIR="$PWD/build" \
FAULTDEBUG_INSTRUMENT_PROFILE=recommended \
FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX='/src/' \
FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX='/generated/' \
CC="$PWD/scripts/faultdebug-cc" \
CXX="$PWD/scripts/faultdebug-cxx" \
meson setup build-meson test/build_systems/meson
meson compile -C build-meson
build-meson/fd_meson_fixture
```

The expected program output is `42`. The separate C and C++ wrappers select the
matching linker for Meson's sanity checks and executable. Meson should be configured in a fresh
build directory after changing compiler wrapper or selection variables; it
caches the compiler configuration. The fixture is an adoption example, not a
Meson-specific FaultDebug API.

## Bazel prototype

The Bazel fixture uses `genrule` to produce one instrumented object and one
excluded object. This demonstrates wrapper adoption and selective compilation
without claiming a repository-wide Bazel C++ toolchain or runtime-link setup.
The fixture exposes the existing wrapper through a symlink, so it must be run
from its own directory:

```bash
cd test/build_systems/bazel
bazel build --lockfile_mode=off //:instrumented_object //:excluded_object
nm -u bazel-bin/instrumented.o
nm -u bazel-bin/excluded.o
```

The first object must reference `__cyg_profile_func_enter` and
`__cyg_profile_func_exit`; the second must reference neither. A deterministic
check is available from the repository root:

```bash
python3 test/build_systems/test_bazel_fixture.py
```

The optional Make/compiledb integration check uses a temporary project and
validates C/C++ database entries, static indexing, and the actual C++ wrapper:

```bash
.venv/bin/python test/build_systems/test_compiledb_integration.py
```

## Local verification record

| Check | Result | Evidence |
| --- | --- | --- |
| Wrapper contract with fake C/C++ drivers | PASS | `python3 test/build_systems/test_wrapper_contract.py` |
| Bazel 9.2 object fixture and hook inspection | PASS | `python3 test/build_systems/test_bazel_fixture.py` |
| Instrumentation profiles in wrapper and CMake helper | PASS | `python3 test/build_systems/test_instrumentation_profiles.py` (includes legacy and filtered generator-expression cases) |
| Real Meson 1.12.1 configure/build/run with Clang 18 and local runtime | PASS | `/tmp/fd-meson-profile-build3`; output `42`; source object symbols confirm hooks only on `src/` files |
| Optional compiledb 0.10.7, Clang 18, and libclang integration fixture | PASS | C/C++ command extraction, relative-path source indexing, and C++ instrumentation-hook checks |
