# External Project Evaluation

This document defines the evidence standard for evaluating faultdebug against an external C/C++ project. It is an evaluation procedure and report template; it does not expand the runtime support contract or turn a local result into a production claim.

## Evaluation identity

Record these fields before running a gate:

| Field | Required value |
| --- | --- |
| External project | Name and source URL or repository identifier |
| Project revision | Full immutable commit, release, or source archive hash |
| faultdebug revision | Full immutable commit or release hash |
| Environment | OS, architecture, kernel, compiler, linker, CMake/Ninja, Python, and dependency versions |
| Scope | Targets, configurations, test cases, and excluded components |
| Evidence directory | Location outside tracked source containing logs, manifests, artifacts, and reports |
| Evaluator | Person or automated job and evaluation timestamp |

A project worktree with uncommitted source changes is not an immutable evaluation revision. If it must be evaluated, record the complete source-tree hash and list the changes.

## Verdict rules

- `PASS`: the stated acceptance evidence exists, is tied to the recorded revisions, and contains no unresolved gate failure within scope.
- `FAIL`: the gate was run and an acceptance condition failed, evidence was rejected, or the observed result contradicts the contract.
- `NOT RUN`: the gate was not run, was intentionally excluded, or required evidence was unavailable. `NOT RUN` is not a pass.

Every gate must include a verdict, exact command or external report reference, evidence paths, and a short limitation. A successful build alone cannot establish runtime tracing, fault capture, source resolution, MCP correctness, reproducibility, or production readiness.

## Gate matrix

### 1. Build integration

**Question:** Can the external project be configured and built with the approved instrumentation integration?

Acceptance evidence:

- Clean configure and build command with the project revision and faultdebug revision recorded.
- Clang 18/CMake/Ninja versions recorded when using the normative Ubuntu 24.04 x86_64 profile.
- Instrumented target binaries, runtime library linkage or explicit preload, compile database, and build manifest are present.
- Build ID and debug information are enabled according to the integration contract.

`PASS` requires every in-scope target to build or an explicitly documented target exclusion. A build that silently falls back to another compiler is `FAIL` for the normative profile.

### 2. Provenance

**Question:** Can every evaluated binary, symbol file, source snapshot, and settings/compile database be matched to the build that produced it?

Acceptance evidence:

- Build manifest with full Build IDs and SHA-256 hashes.
- Immutable source/settings snapshot captured at build time.
- Verification succeeds after changing or moving the current worktree.
- Deliberately mismatched binary, symbol, source, or manifest cases fail with an explicit provenance diagnostic.

Using the current worktree to repair a missing or mismatched saved source is `FAIL`.

### 3. Runtime trace

**Question:** Does the instrumented target publish valid runtime events within the declared bounds?

Acceptance evidence:

- Trace contains committed records with valid ABI version, offsets, capacities, publication markers, generations, and monotonic sequences.
- C, C++17, PIE/ASLR, recursion, and multithread cases are covered when in scope.
- Thread overflow, event eviction, unknown prefixes, and unbalanced exits are surfaced explicitly.
- A normal successful exit is distinguished from a crash or partial termination.

An event count without record validation is insufficient for `PASS`.

### 4. Fault capture

**Question:** Are supported fatal signals captured safely and associated with the correct process/thread metadata?

Acceptance evidence:

- Each in-scope fatal signal has an expected target termination status and a validated `.fault` artifact.
- First valid crash metadata is preserved; nested or repeated faults do not overwrite it.
- Signal, `si_code`, fault address, program counter, TID, and monotonic timestamp validity bits are checked.
- Partial termination without valid crash metadata is reported as partial, not as a successful crash capture.

The existence of a fault file without checksum, length, ABI, and target-status validation is `FAIL`.

### 5. Symbol and source resolution

**Question:** Can captured addresses resolve only against verified binaries, symbols, and saved sources?

Acceptance evidence:

- Module load bias and Build ID are matched to bundled binary evidence.
- Symbol lookup handles PIE and DSO address translation.
- Source lines come from the verified saved source bundle.
- Missing symbols, ambiguous functions, missing source, and Build ID mismatches return structured diagnostics.
- Static call edges are labelled as static evidence and are not presented as executed frames.

An unresolved address may be a valid result when the evidence is insufficient; silently guessing is `FAIL`.

### 6. MCP query

**Question:** Do read-only MCP queries return the same verified evidence as the CLI?

Acceptance evidence:

- Tool registration and schema capture for `open_fault`, `get_thread_trace`, `resolve_addresses`, `get_function_source`, and `get_call_relations`.
- Multi-artifact/timeline/index tools are checked when that scope is enabled.
- Artifact and bundle roots are allowlisted; path traversal and malformed bundle cases fail explicitly.
- Source and relation queries require and verify the immutable bundle.
- Output is structured and uses bounded pagination.

An MCP server starting successfully without exercising tool results is `NOT RUN` for query correctness.

### 7. Reproducibility

**Question:** Can an independent evaluator reproduce the same artifact interpretation from the recorded inputs?

Acceptance evidence:

- Exact commands, revisions, environment versions, seeds/configuration, and hashes are recorded.
- A second run or independent evaluator reproduces the same ABI interpretation, Build ID matches, target status, and diagnostic categories.
- Any expected nondeterminism is stated with an accepted comparison rule.

A saved count copied from a prior run without independent execution is not reproducibility evidence.

### 8. Overhead and scope

**Question:** Is runtime overhead measured within the declared project scope and resource limits?

Acceptance evidence:

- Baseline and instrumented runs use the same target, workload, host conditions, and repetition policy.
- CPU, wall time, memory, recorder budget, thread cap, and event capacity are reported.
- Measurements identify warm-up, variance, failures, and excluded workloads.

Do not generalize a fixture measurement to the external project without a representative workload statement. A missing measurement is `NOT RUN`, not zero overhead.

### 9. Failure evidence

**Question:** Are negative paths tested and preserved as evidence?

Acceptance evidence:

- Malformed/truncated artifact, checksum mismatch, ABI mismatch, stale index, missing symbol, missing bundle, Build ID mismatch, path escape, and overflow cases are exercised where applicable.
- Each failure has an expected diagnostic code/message and observed output.
- A failure is not hidden by a generic nonzero status or converted into an empty result.

## External report acceptance: fmt 11.1.4

An external report labelled `fmt 11.1.4` may be accepted as evidence only when it includes the evaluation identity above, a gate-by-gate verdict, and traceable evidence references. Copy the following record into the evaluation report and attach the original report without editing its conclusions:

```text
External report label: fmt 11.1.4
Report version/date:
External project and immutable revision:
faultdebug immutable revision:
Environment:
Scope and exclusions:
Original report path or URL:
Evidence archive/hash:

Gate verdicts:
  build_integration: PASS | FAIL | NOT RUN
  provenance: PASS | FAIL | NOT RUN
  runtime_trace: PASS | FAIL | NOT RUN
  fault_capture: PASS | FAIL | NOT RUN
  symbol_source_resolution: PASS | FAIL | NOT RUN
  mcp_query: PASS | FAIL | NOT RUN
  reproducibility: PASS | FAIL | NOT RUN
  overhead_scope: PASS | FAIL | NOT RUN
  failure_evidence: PASS | FAIL | NOT RUN

For each gate:
  command/report reference:
  evidence files and hashes:
  observed result:
  limitation or exclusion:

Accepted by:
Acceptance date:
Acceptance decision: ACCEPTED | ACCEPTED WITH LIMITS | REJECTED
Reasons and required follow-up:
```

`ACCEPTED` means the report is usable as evidence for its recorded scope and revision. It does not mean the external project has production readiness or that untested gates passed. Any `FAIL` blocks an overall unrestricted acceptance; `NOT RUN` must remain visible in `ACCEPTED WITH LIMITS`.

## Cross-process evidence limits

Artifact metadata such as a shared trace ID, parent PID, or wall-clock proximity does not prove causal order. A timeline may connect processes only when explicit IPC send/receive records match on message identity/channel, endpoint identity, timestamp order, and any declared sequence or cutoff. Missing or ambiguous evidence must be reported as such.
