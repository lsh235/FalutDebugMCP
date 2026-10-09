from __future__ import annotations
import argparse, json
from .run import run_command
from .index import build_index
from .bundle import create_bundle
from .aggregate import ArtifactIndex, build_timeline, collect_artifacts
from .context import ContextError, context_from_env, merge_context
from .discovery import inspect_spool
from .rpc import incident_report
from .session import process_participants, session_manifest

def main() -> int:
    p = argparse.ArgumentParser(prog="faultdebug")
    sub = p.add_subparsers(dest="action", required=True)
    run = sub.add_parser("run", help="launch and collect an instrumented target")
    run.add_argument("--timeout", type=float)
    run.add_argument("--artifact-dir")
    run.add_argument("--collect-success", action="store_true",
                     help="write a trace artifact after a successful target exit")
    run.add_argument("--trace-id")
    run.add_argument("--correlation-id")
    run.add_argument("--session-id", help="stable session identifier shared by local daemon artifacts")
    run.add_argument("--process-id", help="explicit process identity; generated when omitted")
    run.add_argument("--process-generation", type=int, default=1)
    run.add_argument("--process-role", help="bounded application role label")
    run.add_argument("--agent-socket", help="opt into the resident local collector agent")
    run.add_argument("--context-json", help="optional JSON object stored as correlation context")
    run.add_argument("command", nargs=argparse.REMAINDER)
    run.set_defaults(func=run_command)
    ix = sub.add_parser("index", help="index a compilation database")
    ix.add_argument("compdb", type=str)
    ix.add_argument("-o", "--output", required=True)
    ix.set_defaults(func=lambda n: (build_index(__import__('pathlib').Path(n.compdb), __import__('pathlib').Path(n.output)) and 0))
    bun = sub.add_parser("bundle", help="create a verified immutable source/binary bundle")
    bun.add_argument("--source-root", required=True, type=__import__('pathlib').Path)
    bun.add_argument("--index", required=True, type=__import__('pathlib').Path)
    bun.add_argument("--binary", action="append", default=[], type=__import__('pathlib').Path)
    bun.add_argument("--output", required=True, type=__import__('pathlib').Path)
    def bundle_cmd(n):
        b = create_bundle(n.source_root, n.output, index=n.index, binaries=n.binary)
        print(json.dumps({"bundle": str(b.root), "files": len(b.files), "verified": True}, sort_keys=True)); return 0
    bun.set_defaults(func=bundle_cmd)
    coll = sub.add_parser("collect", help="collect metadata from multiple fault artifacts")
    coll.add_argument("artifacts", nargs="+", type=__import__('pathlib').Path)
    coll.add_argument("--trace-id")
    coll.add_argument("--correlation-id")
    def collect_cmd(n):
        result = collect_artifacts(n.artifacts, trace_id=n.trace_id, correlation_id=n.correlation_id)
        print(json.dumps(result, sort_keys=True)); return 0
    coll.set_defaults(func=collect_cmd)
    incident = sub.add_parser("incident-report", aliases=["report"], help="report observed RPC and unresolved incident evidence")
    incident.add_argument("artifacts", nargs="+", type=__import__('pathlib').Path)
    def incident_cmd(n):
        from .format import collect_file
        result = incident_report([collect_file(path) for path in n.artifacts])
        print(json.dumps(result, sort_keys=True)); return 0
    incident.set_defaults(func=incident_cmd)
    session = sub.add_parser("session-manifest", aliases=["session"], help="build a read-only multi-artifact session manifest")
    session.add_argument("artifacts", nargs="+", type=__import__('pathlib').Path)
    def session_cmd(n):
        from .format import collect_file
        reports = [collect_file(path) for path in n.artifacts]
        print(json.dumps(session_manifest(reports, artifact_refs=[str(path) for path in n.artifacts]), sort_keys=True)); return 0
    session.set_defaults(func=session_cmd)
    participants = sub.add_parser("process-participants", aliases=["participants"], help="list session process participants")
    participants.add_argument("artifacts", nargs="+", type=__import__('pathlib').Path)
    def participants_cmd(n):
        from .format import collect_file
        reports = [collect_file(path) for path in n.artifacts]
        print(json.dumps(process_participants(reports, artifact_refs=[str(path) for path in n.artifacts]), sort_keys=True)); return 0
    participants.set_defaults(func=participants_cmd)
    discover = sub.add_parser("artifact-discover", aliases=["discover"], help="discover and validate artifacts in a spool")
    discover.add_argument("root", type=__import__('pathlib').Path)
    discover.add_argument("--pattern", default="fault-*.fault")
    discover.add_argument("--include-json", action="store_true")
    discover.add_argument("--no-recursive", action="store_true")
    discover.add_argument("--limit", type=int, default=10000)
    discover.set_defaults(func=lambda n: (print(json.dumps(inspect_spool(n.root, pattern=n.pattern, include_json=n.include_json, recursive=not n.no_recursive, limit=n.limit), sort_keys=True)) or 0))
    spool = sub.add_parser("spool", help="verify and ingest completed .fault files into a bounded local spool")
    spool.add_argument("artifacts", nargs="+", type=__import__('pathlib').Path)
    spool.add_argument("--root", required=True, type=__import__('pathlib').Path)
    spool.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    spool.add_argument("--max-files", type=int, default=1000)
    spool.add_argument("--redact-context-id", action="append", default=[])
    def spool_cmd(n):
        from .spool import ArtifactSpool
        store = ArtifactSpool(n.root, max_bytes=n.max_bytes, max_files=n.max_files,
                              redact_context_ids=n.redact_context_id)
        copied = [str(store.ingest(path)) for path in n.artifacts]
        print(json.dumps({"spool": str(n.root), "ingested": copied, "stats": store.stats()}, sort_keys=True))
        return 0
    spool.set_defaults(func=spool_cmd)
    tl = sub.add_parser("timeline", help="build an evidence-only cross-process timeline")
    tl.add_argument("artifacts", nargs="+", type=__import__('pathlib').Path)
    def timeline_cmd(n):
        from .format import collect_file
        print(json.dumps(build_timeline([collect_file(path) for path in n.artifacts]), sort_keys=True)); return 0
    tl.set_defaults(func=timeline_cmd)
    ai = sub.add_parser("artifact-index", help="add/query a restartable SQLite artifact index")
    ai.add_argument("--db", required=True, type=__import__('pathlib').Path)
    ai.add_argument("artifacts", nargs="*", type=__import__('pathlib').Path)
    ai.add_argument("--trace-id")
    ai.add_argument("--correlation-id")
    ai.add_argument("--offset", type=int, default=0)
    ai.add_argument("--limit", type=int, default=200)
    def artifact_index_cmd(n):
        index = ArtifactIndex(n.db)
        try:
            added = index.add(n.artifacts) if n.artifacts else 0
            rows = index.query(trace_id=n.trace_id, correlation_id=n.correlation_id, limit=n.limit, offset=n.offset)
            print(json.dumps({"schema": 1, "added": added, "count": len(rows), "artifacts": rows}, sort_keys=True)); return 0
        finally: index.close()
    ai.set_defaults(func=artifact_index_cmd)
    def _expected_provenance(path):
        if path is None: return {}
        value = json.loads(path.read_text())
        if not isinstance(value, dict): raise SystemExit("--expected-provenance must contain a JSON object")
        return value
    ein = sub.add_parser("evidence-ingest", help="ingest verified artifacts into a schema-v2 evidence store")
    ein.add_argument("artifacts", nargs="+", type=__import__('pathlib').Path)
    ein.add_argument("--db", required=True, type=__import__('pathlib').Path)
    ein.add_argument("--expected-provenance", type=__import__('pathlib').Path)
    ein.add_argument("--build-id")
    ein.add_argument("--session-id")
    ein.add_argument("--process-id")
    ein.add_argument("--process-generation", type=int)
    ein.add_argument("--sha256")
    def evidence_ingest_cmd(n):
        from .evidence_store import EvidenceStore
        expected = _expected_provenance(n.expected_provenance)
        with EvidenceStore(n.db) as store:
            rows = [store.ingest(path, expected=expected, expected_build_id=n.build_id,
                                 expected_session_id=n.session_id, expected_process_id=n.process_id,
                                 expected_process_generation=n.process_generation, expected_sha256=n.sha256) for path in n.artifacts]
        print(json.dumps({"schema": 2, "count": len(rows), "results": rows}, sort_keys=True)); return 0
    ein.set_defaults(func=evidence_ingest_cmd)
    eri = sub.add_parser("evidence-reindex", help="restartably discover and reindex local artifacts")
    eri.add_argument("paths", nargs="+", type=__import__('pathlib').Path)
    eri.add_argument("--db", required=True, type=__import__('pathlib').Path)
    eri.add_argument("--expected-provenance", type=__import__('pathlib').Path)
    eri.add_argument("--build-id")
    eri.add_argument("--session-id")
    eri.add_argument("--process-id")
    eri.add_argument("--process-generation", type=int)
    eri.add_argument("--sha256")
    def evidence_reindex_cmd(n):
        from .evidence_store import EvidenceStore
        expected = _expected_provenance(n.expected_provenance)
        with EvidenceStore(n.db) as store:
            result = store.reindex(n.paths, expected=expected, expected_build_id=n.build_id,
                                   expected_session_id=n.session_id, expected_process_id=n.process_id,
                                   expected_process_generation=n.process_generation, expected_sha256=n.sha256)
        print(json.dumps(result, sort_keys=True)); return 0
    eri.set_defaults(func=evidence_reindex_cmd)
    es = sub.add_parser("evidence-sessions", help="list sessions from a schema-v2 evidence store")
    es.add_argument("--db", required=True, type=__import__('pathlib').Path)
    es.add_argument("--start-ns", type=int); es.add_argument("--end-ns", type=int)
    es.add_argument("--trust-state", choices=["verified", "unresolved"]); es.add_argument("--page", type=int, default=0)
    es.set_defaults(func=lambda n: _evidence_query(n, "list_sessions"))
    ese = sub.add_parser("evidence-session", help="read one session from a schema-v2 evidence store")
    ese.add_argument("--db", required=True, type=__import__('pathlib').Path); ese.add_argument("--session-id")
    ese.add_argument("--start-ns", type=int); ese.add_argument("--end-ns", type=int)
    ese.add_argument("--trust-state", choices=["verified", "unresolved"]); ese.add_argument("--page", type=int, default=0)
    ese.set_defaults(func=lambda n: _evidence_query(n, "get_session"))
    ep = sub.add_parser("evidence-provenance", help="read provenance/trust from a schema-v2 evidence store")
    ep.add_argument("--db", required=True, type=__import__('pathlib').Path); ep.add_argument("--session-id"); ep.add_argument("--artifact-id", type=int)
    ep.add_argument("--trust-state", choices=["verified", "unresolved"]); ep.add_argument("--page", type=int, default=0)
    ep.set_defaults(func=lambda n: _evidence_query(n, "get_provenance"))
    cap = sub.add_parser("capabilities", help="show the bounded v1.0 capability contract")
    def capabilities_cmd(_n):
        from .capabilities import get_capabilities
        print(json.dumps(get_capabilities(), sort_keys=True)); return 0
    cap.set_defaults(func=capabilities_cmd)
    doctor = sub.add_parser("doctor", help="check local Python, compiler, wrapper, and runtime setup")
    doctor.add_argument("--json", action="store_true", help="print the full versioned JSON report")
    def doctor_cmd(n):
        from .doctor import collect_doctor_report, doctor_json, format_doctor_report
        report = collect_doctor_report()
        print(doctor_json(report) if n.json else format_doctor_report(report))
        return {"PASS": 0, "FAIL": 1, "NOT RUN": 2}[report["status"]]
    doctor.set_defaults(func=doctor_cmd)
    bench = sub.add_parser("benchmark", help="compare baseline and instrumented process wall time")
    bench.add_argument("--baseline", required=True, type=__import__('pathlib').Path)
    bench.add_argument("--instrumented", required=True, type=__import__('pathlib').Path)
    bench.add_argument("--repeats", type=int, default=10)
    bench.add_argument("--warmups", type=int, default=2)
    bench.add_argument("--timeout", type=float)
    bench.add_argument("--cwd", type=__import__('pathlib').Path)
    bench.add_argument("--operations", type=int,
                       help="known operations completed by each process invocation, for throughput")
    bench.add_argument("--expected-result-line",
                       help="exact one-line target output expected on every warmup and measurement run")
    bench.add_argument("--artifact-dir", type=__import__('pathlib').Path,
                       help="base directory for per-run artifacts; pass {artifact_dir} in command args")
    bench.add_argument("--output", type=__import__('pathlib').Path,
                        help="atomically save/replace the schema-versioned JSON report at this path")
    bench.add_argument("command_args", nargs=argparse.REMAINDER,
                       help="identical arguments passed to both binaries; place after --")
    def benchmark_cmd(n):
        from .benchmark import benchmark_json, run_benchmark, write_benchmark_report
        args = list(n.command_args)
        if args[:1] == ["--"]:
            args = args[1:]
        try:
            report = run_benchmark(n.baseline, n.instrumented, args, repeats=n.repeats,
                                   warmups=n.warmups, timeout=n.timeout, cwd=n.cwd,
                                   operations=n.operations, artifact_dir=n.artifact_dir,
                                   expected_result_line=n.expected_result_line)
        except (FileNotFoundError, NotADirectoryError, PermissionError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        if n.output:
            write_benchmark_report(n.output, report)
        encoded = benchmark_json(report)
        print(encoded)
        return 1 if report["status"] == "FAIL" else 0
    bench.set_defaults(func=benchmark_cmd)
    eh = sub.add_parser("evidence-health", help="inspect evidence-store compatibility without writing")
    eh.add_argument("--db", required=True, type=__import__('pathlib').Path)
    def evidence_health_cmd(n):
        from .evidence_store import EvidenceStore
        print(json.dumps(EvidenceStore.inspect_health(n.db), sort_keys=True)); return 0
    eh.set_defaults(func=evidence_health_cmd)
    ei = sub.add_parser("evidence-incidents", help="list agent-declared incident groups")
    ei.add_argument("--db", required=True, type=__import__('pathlib').Path); ei.add_argument("--session-id")
    ei.add_argument("--start-ns", type=int); ei.add_argument("--end-ns", type=int)
    ei.add_argument("--trust-state", choices=["verified", "unresolved"]); ei.add_argument("--page", type=int, default=0)
    ei.set_defaults(func=lambda n: _evidence_query(n, "list_incidents"))
    eis = sub.add_parser("evidence-incident", help="read one bounded incident evidence slice")
    eis.add_argument("--db", required=True, type=__import__('pathlib').Path); eis.add_argument("--incident-id", required=True)
    eis.add_argument("--trust-state", choices=["verified", "unresolved"]); eis.add_argument("--page", type=int, default=0)
    eis.set_defaults(func=lambda n: _evidence_query(n, "get_incident_slice"))
    eu = sub.add_parser("evidence-unresolved", help="read unresolved evidence for one incident")
    eu.add_argument("--db", required=True, type=__import__('pathlib').Path); eu.add_argument("--incident-id", required=True); eu.add_argument("--page", type=int, default=0)
    eu.set_defaults(func=lambda n: _evidence_query(n, "get_unresolved"))
    ese = sub.add_parser("evidence-sources", help="cite verified source lines for one incident")
    ese.add_argument("--db", required=True, type=__import__('pathlib').Path); ese.add_argument("--incident-id", required=True)
    ese.add_argument("--bundle", required=True, type=__import__('pathlib').Path); ese.add_argument("--function-id", action="append", default=[])
    ese.add_argument("--page", type=int, default=0)
    ese.set_defaults(func=lambda n: _evidence_query(n, "get_source_evidence"))
    def _evidence_query(n, operation):
        from .evidence_store import EvidenceStore
        with EvidenceStore(n.db) as store:
            if operation == "list_sessions": result = store.list_sessions(start_ns=n.start_ns, end_ns=n.end_ns, trust_state=n.trust_state, page=n.page)
            elif operation == "get_session": result = store.get_session(n.session_id, start_ns=n.start_ns, end_ns=n.end_ns, trust_state=n.trust_state, page=n.page)
            elif operation == "get_provenance": result = store.get_provenance(session_id=n.session_id, artifact_id=n.artifact_id, trust_state=n.trust_state, page=n.page)
            elif operation == "list_incidents": result = store.list_incidents(session_id=n.session_id, start_ns=n.start_ns, end_ns=n.end_ns, trust_state=n.trust_state, page=n.page)
            elif operation == "get_incident_slice": result = store.get_incident_slice(n.incident_id, trust_state=n.trust_state, page=n.page)
            elif operation == "get_unresolved": result = store.get_unresolved(n.incident_id, page=n.page)
            else: result = store.get_source_evidence(n.incident_id, n.bundle, function_ids=n.function_id, page=n.page)
        print(json.dumps(result, sort_keys=True)); return 0
    mcp = sub.add_parser("mcp", help="serve read-only diagnostics over MCP stdio")
    mcp.add_argument("--root", required=True)
    def serve(n):
        from .mcp_server import make_server
        make_server(__import__('pathlib').Path(n.root)).run(transport="stdio")
        return 0
    mcp.set_defaults(func=serve)
    agent = sub.add_parser("agent", help="run the opt-in resident local collector agent")
    agent.add_argument("--socket", required=True, type=__import__('pathlib').Path)
    agent.add_argument("--spool-root", required=True, type=__import__('pathlib').Path)
    agent.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    agent.add_argument("--max-files", type=int, default=1000)
    agent.add_argument("--status-path", type=__import__('pathlib').Path)
    def agent_cmd(n):
        from .agent import serve as serve_agent
        return serve_agent(n.socket, n.spool_root, max_bytes=n.max_bytes, max_files=n.max_files,
                           status_path=n.status_path)
    agent.set_defaults(func=agent_cmd)
    ins = sub.add_parser("inspect", help="inspect a captured fault artifact")
    ins.add_argument("artifact")
    ins.add_argument("--bundle")
    ins.add_argument("--tid", type=int)
    ins.add_argument("--address", action="append", default=[], type=lambda value: int(value, 0))
    ins.add_argument("--function-id", help="look up source from the verified bundle index")
    def inspect_cmd(n):
        import json
        from pathlib import Path
        from .format import collect_file
        from .inspect import diagnose, resolve_addresses, thread_trace, verified_function_source
        report = collect_file(Path(n.artifact))
        result = {"target": report.get("target"), "collector": report.get("collector"), "crashes": report.get("crashes", [])}
        if n.tid is not None: result["threads"] = thread_trace(report, n.tid)
        resolutions = resolve_addresses(report, n.address, bundle=n.bundle) if n.address else []
        if n.address: result["addresses"] = resolutions
        if n.function_id:
            if not n.bundle: raise SystemExit("--function-id requires --bundle")
            result["function"] = verified_function_source(n.function_id, n.bundle)
        result["diagnostics"] = diagnose(report, resolutions)
        print(json.dumps(result, sort_keys=True)); return 0
    ins.set_defaults(func=inspect_cmd)
    flow = sub.add_parser("fault-report", help="create a document and standalone interactive runtime fault-flow report")
    flow.add_argument("artifact", type=__import__('pathlib').Path)
    flow.add_argument("--bundle", help="verified source/binary bundle")
    flow.add_argument("--output", required=True, type=__import__('pathlib').Path,
                      help="new directory for report.md, report.json and report.html")
    flow.add_argument("--max-events", type=int, default=80, help="last 1–500 pre-crash events per thread")
    flow.add_argument("--language", choices=["en", "ko"], default="en")
    def fault_report_cmd(n):
        from .fault_report import write_fault_report
        try:
            result = write_fault_report(n.artifact, n.output, bundle=n.bundle,
                                        max_events=n.max_events, language=n.language)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SystemExit(f"fault-report: {exc}") from exc
        print(json.dumps(result, sort_keys=True)); return 0
    flow.set_defaults(func=fault_report_cmd)
    service_flow = sub.add_parser("service-report", help="report observed service RPC flow with separate application evidence")
    service_flow.add_argument("evidence", type=__import__('pathlib').Path)
    service_flow.add_argument("--output", required=True, type=__import__('pathlib').Path)
    service_flow.add_argument("--bundle", type=__import__('pathlib').Path)
    def service_flow_cmd(n):
        from .service_report import write_service_report
        try:
            result = write_service_report(n.evidence, n.output, bundle=n.bundle)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SystemExit(f"service-report: {exc}") from exc
        print(json.dumps(result, sort_keys=True)); return 0
    service_flow.set_defaults(func=service_flow_cmd)
    ns = p.parse_args()
    if ns.action == "run" and ns.command[:1] == ["--"]: ns.command = ns.command[1:]
    if ns.action == "run":
        try:
            context = context_from_env()
        except ContextError as exc:
            raise SystemExit(str(exc)) from exc
        if ns.context_json:
            extra = json.loads(ns.context_json)
            if not isinstance(extra, dict): raise SystemExit("--context-json must be a JSON object")
            context = merge_context(context, extra)
        # Explicit identifiers are the highest-precedence boundary metadata.
        if ns.trace_id: context["trace_id"] = ns.trace_id
        if ns.correlation_id: context["correlation_id"] = ns.correlation_id
        ns.context = merge_context(context)
    return ns.func(ns)

if __name__ == "__main__":
    raise SystemExit(main())
