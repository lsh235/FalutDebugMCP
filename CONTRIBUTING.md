# Contributing to FaultDebug

Thanks for helping improve FaultDebug. Contributions should preserve the
artifact and evidence contracts, keep collection bounded, and make uncertainty
visible instead of guessing missing data.

## Development environment

The supported development profile is Ubuntu 24.04 x86_64, Python 3.12, Clang
18, CMake 3.20 or newer, and Ninja. Install Python dependencies in an isolated
environment:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

Configure and build the native runtime and fixtures:

```sh
cmake -S . -B build -G Ninja \
  -DCMAKE_C_COMPILER=clang-18 \
  -DCMAKE_CXX_COMPILER=clang++-18 \
  -DFAULTDEBUG_PYTHON_EXECUTABLE="$PWD/.venv/bin/python" \
  -DFAULTDEBUG_BUILD_TESTS=ON
cmake --build build --parallel 2
```

## Validation

Run the named native tests and a launcher-backed smoke suite:

```sh
ctest --test-dir build --output-on-failure
FD_LAUNCHER="$PWD/.venv/bin/fault-debug" \
  .venv/bin/python test/run_tests.py --suite smoke --output test-results/smoke
```

When changing the artifact format, ABI, collector, source bundle, evidence
store, or MCP interface, run the relevant compatibility and malformed-input
checks described in [`test/README.md`](test/README.md). For release-profile
requirements, use the workflow and runner documented in
[`docs/clang18-ci.md`](docs/clang18-ci.md). Report `PASS`, `FAIL`, and
`NOT RUN` separately; a build-only result does not prove runtime behavior or
source-resolution correctness.

## Design and review expectations

- Keep observed runtime events, static candidates, derived relations, and
  unresolved evidence in separate fields.
- Do not infer cross-process causality from names, parent PIDs, shared IDs, or
  timestamps without matching endpoint evidence.
- Preserve explicit dropped-event, partial, provenance, and trust status.
- Keep local artifact roots allowlisted. Never add remote collection or
  credential/payload recording without a separately reviewed design.
- Update user-facing docs and compatibility coverage when commands, output
  fields, or file formats change.

Pull requests should summarize behavior, list validation commands and results,
call out compatibility changes, and state remaining limits. Generated builds,
virtual environments, logs, local fault artifacts, and machine-specific paths
belong outside tracked source files. Never commit credentials, private crash
data, proprietary source, or host-specific absolute paths.

## License

By contributing, you agree that your contribution is provided under the
project's [Apache-2.0 license](LICENSE).
