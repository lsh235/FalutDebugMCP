# Fault-flow report validation - 2026-10-09

This records local verification of the unreleased report feature on Linux
x86_64, Python 3.12 and Clang 18. It is not final v1.2 release acceptance or an
independent root-cause audit.

| Check | Result | Evidence |
| --- | --- | --- |
| Python report regressions | PASS | 13 checks covering evidence edges, gaps, validity flags, reuse, injection escaping, uint64, bounds, checksum, bundle tampering and read-only MCP |
| Native build | PASS | `cmake --build build --parallel 2` |
| CTest | PASS | 22/22, including crash generation and registration-in-progress decoder regression |
| Compilation index regression | PASS | `test/index_linkage.py` |
| sdist / wheel build | PASS | `python -m build --sdist --wheel --no-isolation` |
| Wheel consumer | PASS | Wheel installed in an isolated target under `/tmp`; CLI invoked outside the repository generated all three report files |
| Real fault report | PASS | `fd_c_chain 16 fault`: SIGILL, 34 function events, generation 1, 18 verified source functions, `terminal_fault`, `test/programs/c_chain/main.c:4:89` |
| Browser interaction | PASS | Search found two `terminal_fault` nodes; full view showed 35 nodes; node selection exposed a nesting connector and verified source; keyboard focus survived Enter |
| Themes and desktop layout | PASS | Chromium screenshots inspected at 1440x900, 1600x1000 and 1920x1080 |
| Mobile layout | PASS | 390x844: no page overflow, horizontal scrolling confined to the flow viewport |
| Browser console / offline resources | PASS | Zero console errors/warnings; zero external resource requests |
| Printed PDF | PASS | Five pages rendered and visually inspected; full report table and source excerpts present |
| Independent fault/root-cause review | NOT RUN | Report does not infer or certify root cause |

The real artifact explicitly reports incomplete RPC capture after the fatal
signal. Its report therefore remains **limited**, even though the collector
succeeded, the function thread dropped no events, and the snapshot was stable.
Unmatched ENTER records reflect the interruption; they are not an OS unwind.

The initial CTest invocation used a cached system Python without project
dependencies and failed the environment diagnostic. Reconfiguring with the
project's `.venv/bin/python` resolved the setup difference; the final complete
CTest run passed. Initial PDF heading placement and mobile overflow findings
were corrected and rechecked.

The first hosted CI run exposed a fresh-install dependency incompatibility:
MCP 1.9.4 imports `eval_type_backport`, removed in Pydantic 2.14. The local
environment had Pydantic 2.13.5. Project metadata now constrains Pydantic to
`>=2.7.2,<2.14`, preserving the pinned MCP SDK without patching third-party code
or skipping the MCP test. See the [Pydantic change record](https://pydantic.dev/docs/validation/latest/get-started/changelog/#v2140a1-2026-05-22)
and [MCP 1.9.4 dependencies](https://github.com/modelcontextprotocol/python-sdk/blob/v1.9.4/pyproject.toml).

## Reproduce

```sh
cmake -S . -B build \
  -DFAULTDEBUG_PYTHON_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure --parallel 2
.venv/bin/python test/fault_report_test.py
.venv/bin/python test/index_linkage.py
.venv/bin/python -m build --sdist --wheel --no-isolation
.venv/bin/python -m faultdebug.cli run --artifact-dir artifacts \
  -- build/test/fd_c_chain 16 fault
# Expected fatal-signal exit: 132; use the artifact path returned above.
.venv/bin/python -m faultdebug.cli fault-report artifacts/fault-<pid>.fault \
  --bundle build/bundle --output reports/incident-001 --language ko
```

Create the matching source/index/binary bundle as described in the README
before the final command. Open `report.html`, select the fault node, then use
Print document / PDF. Korean screenshot verification used a local Noto CJK
font configuration; the report ships no remote font dependency.

The checked-in preview image comes from the repository's own public C fixture.
Raw artifacts, bundles, local screenshots and the PDF are excluded from the
commit. Existing unrelated `output/` content is preserved.
