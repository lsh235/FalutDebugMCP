# Roadmap

This roadmap describes work beyond v0.1.0. It is not a promise of delivery dates.

## Active next version: v1.2.0

The next version focuses on evidence correctness and reproducible adoption.
The implementation plan and acceptance gates are in
[docs/next-version-v1.2.md](docs/next-version-v1.2.md); the fresh v1.1 baseline
and observed failures are in [docs/v1.2-baseline.md](docs/v1.2-baseline.md).

1. **P1-01, P1-02, and P1-03 complete:** fixed physical thread-ring decoding,
   aligned doctor with actual wrapper/runtime behavior, and verified isolated
   negative cases, JSON signal handling, and real MCP/gRPC flows. M1 is complete.
2. **P2-01 complete:** bounded collector readiness and agent receives, prevented
   mixed live event/RPC records from appearing complete, and passed native writer
   stress plus the full 18-test CTest suite.
3. **P2-02 complete:** normal-exit collection is opt-in; paired C++ workload
   samples now bind exact workload output, target/process timing, trace
   completeness, and per-run loss. Clean profiles had zero loss and the forced
   overflow profile reported 25,906 lost records per instrumented run.
4. **P2-03 complete:** two clean-snapshot evaluations of pinned libuv matched
   source/runtime/archive hashes, Build-IDs, SIGABRT and source diagnostics; all
   required MCP calls and the expected path-error passed over stdio. Both
   evidence archives passed member/hash verification.
5. **P3-01 local and hosted gates pass; v1.2.0-rc.1 candidate published.** Core and
   gRPC profiles pass locally and on GitHub Actions, including checkout-free wheel
   CLI/MCP consumers. The current-source 1800-second soak passed its target,
   telemetry, and independent structural oracle checks while preserving an
   explicitly incomplete trace with recorded loss. Independent final acceptance
   remains pending, so the stable v1.2.0 release is not yet accepted.

Planning, baseline, P1, P2-01/02/03, and the local P3 profiles and soak are complete.
The `v1.2.0-rc.1` candidate is published. Independent review and full v1.2.0
release acceptance remain pending. Implementation reports are linked from
[the v1.2 plan](docs/next-version-v1.2.md).
Standalone fault-flow and service-flow reports and the Docker shopping laboratory
are now implemented; their current scope and local validation are documented in
[the shopping validation report](docs/shopping-fault-lab.validation.md).
Dynamic-module lifecycle tracking, automatic general-purpose RPC interceptors,
remote collection, and a continuous live visualization UI remain later workstreams.

## Researched candidate after v1.2 acceptance: v1.3

Research dated **2026-10-11**, based on revision `70d6771`, is in
[the research dossier](docs/next-version-research-2026-10-11.md). The proposed
work items, dependencies, evidence contracts, and acceptance matrix are in
[the v1.3 candidate plan](docs/next-version-v1.3.md). These are planned work,
not completed features or a stable-release declaration.

1. **P0-01 implemented and locally verified:** generation event counters, explicit
   retired-history limitations, and 18 native oracle cases; core/gRPC and Docker
   regressions pass. [Implementation evidence](docs/v1.3-p0-01.md) records the
   current-source results. Hosted revalidation, fresh soak, and final stable
   acceptance remain pending.
2. Preserve full trace IDs and define W3C HTTP context, process/container generation,
   and clock-domain contracts while retaining numeric ABI compatibility.
3. Add real TCP fault injection and restart/retry state oracles to the Docker lab;
   generalize the offline report and expose bounded read-only MCP service-flow queries.
4. Validate N=32 and local kind Kubernetes lifecycle/export, followed by current-source
   scale, shopping soak, packaging, hosted gates, and RC acceptance.
5. Evaluate a pinned OpenTelemetry Demo integration as a separate experimental profile.
   Chaos Mesh and a general remote agent are not prerequisites for the initial work.

The source/runtime generation concern is distinct from the small-capacity decoder
stride bug already fixed in v1.2. Local kind nodes do not establish multi-host support.
Current Docker N=8/16 results do not establish Kubernetes, N=32, or shopping-soak results.

## Stage 1 complete in v0.1.0

- CI/build guidance documents the supported Ubuntu 24.04 x86_64 and Clang 18 toolchain path.
- CLI diagnostics report structured missing-symbol, incomplete-trace, and provenance-mismatch codes.
- Malformed artifact, bundle, checksum, and context inputs have explicit validation paths.
- Process identity and optional trace/correlation context are preserved in backward-compatible artifacts.

## Next stage

- Propagate trace context across cooperating processes through an explicit IPC integration.
- Build a cross-process timeline from synchronization evidence and recorded event cutoffs.
- Provide an optional durable index for larger artifact collections.

## v0.2.0 release gates

- Run the external fmt 11.1.4 evaluation in GitHub Actions with Clang 18,
  the compiler wrapper, an instrumented driver, and the independent evaluator.
- Repeat the evaluation from the pinned source revision and preserve the report
  as an Actions artifact. Missing apt, toolchain, Python dependencies, or
  external network must remain `NOT RUN`.
- Add an independent signal matrix covering the supported fatal-signal paths.
- Measure baseline versus instrumented overhead for the declared driver and
  recorder limits. A missing or nonrepresentative measurement is `NOT RUN`.

## v0.3.0 current release

- Added an optional asynchronous gRPC CompletionQueue proxy fixture under
  `test/programs/grpc_proxy/`.
- Added generated protobuf/gRPC C++ sources to the CMake test build when the
  required packages and plugins are installed.
- Added a three-process fault gate covering upstream, proxy, and client
  execution, including a real post-response SIGSEGV and source recovery.
- Added independent artifact, signal-origin, module, sequence, RPC-boundary,
  symbolization, bundle, and clean-shutdown checks.
- Added process-group cleanup for timeout paths and completion-queue failure
  handling for upstream forwarding and graceful shutdown.

The v0.3.0 fixture records application-owned RPC boundary functions. It does
not yet add RPC IDs, metadata propagation, gRPC status events, or semantic
cross-process correlation fields to the shared-memory ABI.

## Later

- Support controlled dynamic module lifecycle tracking with bounded load and unload records.
- Add richer visualization and export formats for verified evidence.

## Next gRPC stage

- The v0.4 optional numeric sidecar and MCP evidence tools provide bounded
  event transport and separate observed/static/unresolved result classes.
- A gRPC interceptor is still future work; the sidecar API must be populated
  by an integration-owned interceptor before RPC method execution can be
  observed automatically.
- Propagate an allowlisted trace ID through metadata without recording payloads
  or credentials.
- Extend the v0.4 MCP output with richer method/status labels only when an
  interceptor supplies corresponding numeric evidence.
- Extend the fixture to streaming RPCs, CompletionQueue failures, retries, and
  multiple worker threads.

## v0.5.0 current release

- CMake and compiler-wrapper builds support source-path include/exclude
  selection while retaining runtime linkage and build provenance. Object-only
  C++ links use the explicit `FAULTDEBUG_LINK_DRIVER` setting.
- CLI/MCP artifact discovery validates bounded local spools and preserves
  malformed entries as explicit failures.
- Bundle verification covers source, index, and binary hashes and rejects
  manifest paths that escape the bundle root.

## v0.6.0 current release

- A read-only CLI/MCP incident report summarizes captured RPC and process
  evidence while keeping observed, static-candidate, and unresolved classes
  separate.
- Status, deadline, retry, and stream fields are reported only when present
  in the artifact contract.
- The asynchronous gRPC fixture records numeric unary begin/end events with
  propagated RPC/trace IDs, directions, statuses, timestamps, and incomplete
  flags. Deadline/response-delay and CompletionQueue worker controls are
  available as fixture options.
- Streaming and retry capability checks remain `NOT RUN`; the fixture has no
  interceptor and the analyzer does not infer global causal order.

## v0.7.0 current release

- Added a bounded optional session declaration with `session_id`,
  `participant_id`, and `expected_participants`.
- Added read-only CLI/MCP session manifests and process participant views.
- Derived process relations, observed RPC events, static candidates, and
  unresolved evidence remain separate; legacy trace/correlation grouping is
  preserved for older artifacts.

## v0.8.0 current release

- Added SQLite evidence store schema v2 for artifact, process, evidence,
  relation, provenance, trust, and quarantine records.
- Ingest verifies local FDAR checksums and validates supplied session/process
  identity and Build ID/binary/source/index provenance expectations.
- Added deterministic session, time-window, trust, and provenance queries,
  restartable reindexing, and migration from the v0.6 metadata index.
- Added read-only MCP and CLI session/provenance queries. Runtime peer
  snapshots remain observed records with collector phase/partial fields; the
  store never infers causal relations from shared session IDs.

## v0.9.0 current release

- Added bounded incident listing and incident slices keyed only by declared
  agent `incident_id` values.
- Preserved observed, derived, static-candidate, unresolved, and hypothesis
  evidence classes, including peer snapshot collector phase/partial fields.
- Added verified bundle source citations with exact file, line, and SHA-256
  references and structured query errors. Incident tables are additive to the
  v0.8 schema-v2 store for compatibility.

## v1.0.0 current release

- Added bounded capability discovery for CLI/MCP clients, including the
  mandatory inspection tools, artifact/store versions, limits, evidence
  classes, supported signal matrix, platform/toolchain, and security scope.
- Added read-only SQLite health/compatibility checks with explicit integrity,
  migration, and additive incident-table status.
- Documented upgrade and support boundaries while preserving v0.8/v0.9 APIs and
  evidence-class separation.

## v1.1.0 adoption and tooling backlog

The v1.1.0 work is complete. Ownership below is by implementation role; the
coordinator owns cross-workstream integration and release acceptance. A local
or synthetic check only passes the named scope in its row.

| Work item | Owner role | Dependency | Acceptance gate | Current evidence and status |
| --- | --- | --- | --- | --- |
| Read-only `doctor` CLI and environment report | Tooling owner | Python 3.12 environment, packages, Clang 18, wrappers, runtime | CLI reports tool/package/runtime checks as `PASS`, `FAIL`, or `NOT RUN`; JSON/text output and exit-code contract are exercised | Pinned `.venv/bin/python -m faultdebug.cli doctor --json` **PASS** (12/0/0 PASS/FAIL/NOT RUN). Bare `/usr/bin/python3` invocation **FAIL** on missing `libclang`, `pyelftools`, and `mcp`; use the pinned environment. Doctor contract checks **PASS**. |
| Baseline/instrumented benchmark CLI | Tooling owner; external C++ workload owner | Two runnable binaries, declared workload; artifact directory for artifact metrics | Repeated paired runs report wall time and available CPU/RSS/throughput/artifact/loss metrics; unavailable metrics stay `NOT RUN`; operation count is independent of measured output | CLI contract and synthetic artifact checks **PASS**. Representative synchronized 32-thread C++ call benchmark **PASS** with 2 warmups and 7 paired measurements; direct recorder check **PASS**, 33 thread records and 100,290 events with `dropped_count=0`. Artifact-size and decoded-loss CLI metrics **NOT RUN** because normal runs emit no artifact. Timings are descriptive with no threshold; see `test/external/cpp-call-benchmark-v1.1.md` and raw checked-in JSON `test/external/cpp_call_benchmark_v1_1.json`. |
| Meson and Bazel wrapper adoption fixtures | Build-integration owner | FaultDebug compiler wrappers and runtime; Meson and Bazel toolchains | Meson configure/build/run plus named profile matrix; Bazel fixture object inspection confirms allowlisted hooks and excluded-object behavior | Fake-driver wrapper contract **PASS**; Bazel 9.2 fixture and object hook inspection **PASS**; wrapper/CMake named instrumentation profile matrix **PASS**; real Meson 1.12.1 configure/build/run with Clang 18 and local runtime **PASS**. Evidence and commands: `docs/build-integration-v1.1.md`. |
| Pinned external libuv source evaluation | External-corpus owner | Pinned libuv source, Clang 18, FaultDebug runtime, project Python dependencies | Original and instrumented builds; expected fatal-signal artifact; Build-ID-bound `uv_*` source resolution and MCP source/relation results | Bounded libuv v1.48.0 evaluation **PASS** at commit `e9f29cb984231524e3931aa0ae2c5dae1a32884e`. Performance study and independent report comparison **NOT RUN**. See `test/external/libuv-v1.48.0-evaluation.md`; its raw JSON remains local and is not distributed with the source tree. |
| Cross-workstream integration and v1.1.0 release acceptance | Coordinator | Completion of tooling, build-integration, and external-project gates | Re-run the integrated acceptance set; resolve mandatory failures and retain every unavailable gate as `NOT RUN`; obtain independent audit before release | Integrated acceptance **PASS (7/7)**; CTest **PASS (10/10)**; wheel build **PASS**; targeted v1.0 package-metadata check for version 1.1.0 **PASS**. Independent audit **PASS**, including the corrected benchmark Markdown/JSON consistency check. Graph/index coverage **NOT RUN** because codebase-memory tools were unavailable. Bounded libuv v1.48.0 source/build/trace/source-resolution/MCP gates **PASS**, while its performance study and independent report comparison remain **NOT RUN**. v1.1.0 release acceptance **COMPLETE**. |

The independent audit recorded **PASS** and the v1.1.0 release acceptance gate
is **COMPLETE**. The explicitly listed `NOT RUN` items remain outside the
completed acceptance scope.

## Current boundaries

The v0.8 collector provides bounded local registration and an optional
resident local-agent peer snapshot path; remote or multi-host coordination is
not supported. It does not infer causal order between processes, and static
call edges do not prove runtime execution. Missing, overwritten, or ambiguous
events remain unresolved. Stack repair from static graphs, automatic source
identity from the current worktree, remote execution, encrypted transport,
and production service isolation remain outside the current release scope.
