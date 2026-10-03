# External evaluation: fmt 11.1.4

This is a recorded external-project evaluation for the tagged `fmt` 11.1.4
source tree. It records local evidence only; it does not claim that fmt or
faultdebug is production-ready.

## Evaluation identity

| Field | Recorded value |
| --- | --- |
| External project | fmt 11.1.4 |
| Immutable source revision | `123913715afeb8a437e6388b4473fcc4753e1c9a` (`11.1.4`) |
| Source files | 132 files in the evaluated source tree, excluding `.git` |
| faultdebug revision | `4c2d1fc` (evaluation code) |
| Environment | Ubuntu 24.04, x86_64, Clang 18.1.3 evaluation profile, CMake 3.28.3, Ninja 1.11.1, Python 3.12.3 |
| Scope | C++ driver calling fmt, original and instrumented builds, runtime trace, artifact decoding, verified bundle lookup, and direct FastMCP ToolManager calls |
| Evidence | `/tmp/fd-fmt-evaluation-final4/report.json`, `/tmp/fd-fmt-mcp-result-final4.json`, `/tmp/fd-fmt-eval-build/`, and `/tmp/faultdebug-fmt-driver/` |

The evidence files remain outside the repository and are referenced by path;
they are not copied into the release tree.

## Build and provenance evidence

The original driver was built at
`/tmp/fd-fmt-eval-build/fmt-driver-original` with Build ID
`c0ed88f8cabb815c1c57cb58c048c7db29a49fb3`. The instrumented driver was built
at `/tmp/fd-fmt-eval-build/fmt-driver-instrumented` with Build ID
`b0e7005500083595d81a50d60b0f5425cb5694b7`. The report records that the
instrumented artifact Build ID matches the bundled binary and that the two
Build IDs are distinct. Their SHA-256 values are, respectively,
`cc78a7cc79f66a2672813d532ae1434b630a7134b265ef77e9a0ff06cc84e93a` and
`4927caff095518fa754dd18aacce6c79c767d9024faf7f9f24a8556e4b6209ea`.

The evaluated source and compile database were indexed with libclang. Header
and inline definitions under the project root were included. Duplicate USRs
prefer the `cursor.is_definition()` row, so the implementation in
`include/fmt/format-inl.h` is selected over a declaration in a base header.

## Gate results

| Gate | Verdict | Evidence and limitation |
| --- | --- | --- |
| Build integration | PASS | `report.json` records distinct original/instrumented Build IDs and a valid artifact. The report covers the driver target, not every fmt build configuration. |
| Provenance | PASS | Build ID agreement and verified bundle lookup are recorded in `report.json`; binary and source hashes are retained in the external bundle manifest. This is limited to the evaluated driver and bundle. |
| Runtime trace | PASS | The decoded report contains 170 events with valid artifact decoding and the MCP trace result reports the same event count. This is one driver workload. |
| Fault capture | PASS | `/tmp/fd-fmt-artifacts-final2/fault-2438736.fault` decoded with collector status `7`, target `signal=4` (`SIGILL`), target `returncode=-4`, and 170 retained events with no dropped records. This validates the evaluated SIGILL path only; it does not establish every supported signal. |
| Symbol/source resolution | PASS | `get_function_source` returns the verified saved `include/fmt/format-inl.h` implementation at lines 1452–1459 for `vformat_to`; `resolve_addresses` resolves a matching instrumented address with the verified Build ID. |
| MCP query | PASS | Direct ToolManager evidence registers and exercises `open_fault`, `get_thread_trace`, `resolve_addresses`, `get_function_source`, and `get_call_relations`; no required tool is missing. |
| Reproducibility | NOT RUN | The recorded commands and hashes identify the inputs, but an independent second evaluator run is not included. |
| Overhead and scope | NOT RUN | No representative baseline/instrumented performance measurement was recorded. |
| Failure evidence | NOT RUN | General malformed-input coverage exists in the project test suite, but this external report does not attach a complete negative-path matrix for fmt. |

The evaluator report `/tmp/fd-fmt-evaluation-final4/report.json` has overall
status `PASS` for the checks it defines. Its SHA-256 is
`411f5f0be6c1f5fe336dce9e7336d728f3395e486f5dc6c852867634582a087f`.
The MCP result `/tmp/fd-fmt-mcp-result-final4.json` has SHA-256
`54f3aec7cbe27a62e3e62d1e0fad333aaf631fbb7b2af25f7cac9f26a19a2174`.

## MCP source and relation result

The source query used the verified bundle and the deduplicated index row for
`fmt::v11::detail::vformat_to`. It returned:

```text
resolved: true
file: .../source/include/fmt/format-inl.h
start_line: 1452
end_line: 1459
```

The MCP call-relation query reported one resolved relation for
`vformat_to`. The captured index also retains one explicitly unresolved
indirect/virtual edge as separate static evidence; it is not counted as a
resolved relation or presented as an executed call.

## Reproduction references

The following commands describe the input locations used by the evaluation;
they expect those external inputs to exist and do not create tracked output:

```sh
git -C /tmp/faultdebug-external rev-parse HEAD
sha256sum /tmp/fd-fmt-eval-build/fmt-driver-original \
  /tmp/fd-fmt-eval-build/fmt-driver-instrumented
cat /tmp/fd-fmt-evaluation-final4/report.json
cat /tmp/fd-fmt-mcp-result-final4.json
```

## SIGTRAP limitation

The driver contains a deliberate `raise(SIGTRAP)` mode, but this evaluation
does not count that mode as a successful fault-capture gate. No claim is made
here that SIGTRAP produces the same first-crash metadata and artifact status as
the validated normal-trace path. SIGTRAP behavior requires a dedicated
signal-path run and remains `NOT RUN` for this external report.
