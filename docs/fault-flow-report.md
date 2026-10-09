# Fault execution-flow reports

Generate a report after collecting a real `.fault` artifact:

```sh
fault-debug fault-report artifacts/fault-123.fault \
  --output reports/incident-001 --bundle build/bundle --language ko
```

`--bundle` is optional. Without a matching verified source/binary bundle,
addresses can remain unresolved and no current-worktree source text is read.
The output directory must be new. Invalid checksums or bundles fail before a
report is published; existing reports are preserved.

| Output | Purpose |
| --- | --- |
| `report.md` | Incident document with fault facts, event tables, gaps, diagnostics and source excerpts |
| `report.json` | Versioned `faultdebug-fault-flow` model with artifact SHA256 and typed evidence edges |
| `report.html` | Self-contained offline SVG flow explorer and printable document |

Open `report.html` in a browser. It starts on the captured fault's thread and
shows nearby records. Select a node to inspect its address, Build ID, source
file/line, and captured source excerpt. Search by function or address, switch
threads or themes, or show all events included in the report. **Print document /
PDF** prints the full report document, including all report threads and evidence
limits, independently of the current view or search filter.

Use `--language en` (default) or `--language ko`. Machine-readable evidence
codes and technical limitations retain their stable English wording. Each
thread includes the last 80 pre-crash events by default; `--max-events 1..500`
changes this window. View clipping and omitted report events are counted
separately from actual capture loss. A verified function excerpt includes up to
80 lines with its displayed range. These bounds keep the offline report usable;
the original artifact and bundle retain the full evidence.

## What the flow proves

| Display / edge kind | Meaning |
| --- | --- |
| Gray dashed / `record_order` | Consecutive retained records in one thread generation |
| Cyan / `observed_nesting` | Instrumented entry nested inside another retained instrumented entry; select an endpoint to see the connector |
| Red dashed / `crash_context` | Latest retained event at or before the crash timestamp in the matching TID/generation; temporal context only |
| Red node | Signal and PC copied only when the native validity flags mark them valid |
| Amber node / evidence limit | Sequence hole, missing prefix, recorder marker, mismatched exit, ambiguous identity, drop or unstable capture |
| Static candidates in details | Bundle index possibilities; never inserted as runtime arrows |

Nesting does not prove a direct call through uninstrumented code. The last event
does not establish the cause of a signal. Unmatched entries are retained
instrumentation context, not an OS stack unwind. A sequence hole or recorder
marker resets the nesting context; no arrow bridges that missing section. An
event from a different thread generation cannot form a nesting edge. Crash
association requires a unique TID **and** generation match; other threads are
not joined by timestamps. Events after a matched crash timestamp are excluded
from its pre-crash view and counted separately.

`capture_complete` describes capture metadata only, not symbol resolution or
root-cause certainty. Missing completeness/snapshot declarations are treated as
limited evidence. An artifact without a crash record is presented as a trace
with no inferred fault site. Null fault address (`0`) is distinguished from an
unrecorded address by the native validity flags.

New captures publish the registered thread generation in each crash record.
Registration reserves a slot until its generation is initialized; the signal
handler looks up the published TID in bounded shared memory, without dynamic
TLS access. A snapshot of a registration in progress is explicitly unstable.
Older artifacts with generation zero remain unassociated rather than being
silently matched to a reused TID.

## MCP integration

The read-only `get_fault_flow(name, bundle=None, max_events=80)` tool returns the
same bounded model for an artifact under the MCP server's allowlisted root.
Bundle paths use the same allowlist. The tool writes no files. Use the CLI to
export documents. Existing `incident-report` / `report` and
`get_incident_report` continue to report explicit multi-artifact RPC evidence;
this view focuses on function events in a single capture.

For local test evidence, see the [validation record](fault-flow-report-validation.md).

## Design and dependencies

The exploration design draws on [Archify](https://github.com/tt-a1i/archify):
standalone diagrams, themes, node focus, and explicit evidence boundaries.
FaultDebug implements its own Python/inline-SVG renderer; report generation
requires no Archify install, Node.js, network access, CDN, or AI API. This is
not an Archify renderer artifact or an Archify validation certification.

Artifact text is escaped in documents and embedded as inert JSON. The HTML
uses a content security policy blocking network connections. Reports include
captured source and paths when available; share them under the same access
policy as the original fault artifact and source bundle.

## Validation

```sh
PYTHONPATH=. .venv/bin/python test/fault_report_test.py
.venv/bin/python -m build --sdist --wheel
```

The regression suite exercises sequence gaps, recorder markers, unmatched
exits, reused/ambiguous thread identities, event generation mismatch, crash
timestamp and validity flags, capture-loss indicators, display limits,
untrusted text, uint64 values, checksums, CLI files and read-only MCP paths.
