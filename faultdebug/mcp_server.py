"""Read-only MCP facade over captured artifacts."""
import json
from pathlib import Path
from .format import collect_file
from .bundle import BundleError, load_bundle
from .inspect import (resolve_addresses as resolve_address_records, thread_trace,
                      verified_call_relations, verified_function_source)
from .aggregate import ArtifactIndex, build_timeline, collect_artifacts
from .rpc import evidence_summary, incident_report, process_relations, rpc_trace
from .session import process_participants, session_manifest
from .discovery import inspect_spool
from .evidence_store import EvidenceStore, EvidenceStoreError
from .capabilities import get_capabilities as capability_contract

def _load(root: Path, name: str) -> dict:
    path = (root / name).resolve()
    if root.resolve() not in path.parents or path.suffix not in (".fault", ".json"):
        raise ValueError("artifact is outside the allowlisted root")
    if not path.is_file(): raise ValueError(f"artifact not found: {name}")
    return collect_file(path)

def _safe_artifact(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if root.resolve() not in path.parents or path.suffix not in (".fault", ".json") or not path.is_file():
        raise ValueError("artifact is outside the allowlisted root or missing")
    return path


def _safe_store(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if root.resolve() not in path.parents or path.suffix not in (".sqlite", ".db", ".sqlite3") or not path.is_file():
        raise ValueError("evidence store is outside the allowlisted root or missing")
    return path


def _bundle(root: Path, name: str):
    path = (root / name).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise ValueError("bundle is outside the allowlisted root")
    try: return load_bundle(path)
    except BundleError as exc: raise ValueError(str(exc)) from exc

def make_server(root: Path):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("official mcp Python SDK is required") from exc
    app = FastMCP("faultdebug")
    @app.tool()
    def get_capabilities() -> dict:
        """Describe supported artifacts, evidence classes, limits, and local-only behavior."""
        return capability_contract()
    @app.tool()
    def check_store(db: str = "evidence.sqlite3") -> dict:
        """Check a SQLite evidence store's schema and health without creating or migrating it.

        Args:
            db: Store filename beneath the configured artifact root. Must end in
                .sqlite, .db, or .sqlite3.
        """
        path = (root / db).resolve()
        if root.resolve() not in path.parents or path.suffix not in (".sqlite", ".db", ".sqlite3"):
            return {"schema": 2, "status": "error", "read_only": True,
                    "error": {"code": "STORE_PATH_INVALID", "message": "evidence store is outside the allowlisted root"}}
        return EvidenceStore.inspect_health(path)
    @app.tool()
    def open_fault(name: str, bundle: str | None = None) -> dict:
        """Decode one .fault or .json capture beneath the configured artifact root.

        Args:
            name: Relative capture filename; absolute paths and parent traversal are rejected.
            bundle: Optional verified source-bundle directory beneath the same root.
        """
        report = _load(root, name)
        if bundle: report["bundle"] = {"path": str(_bundle(root, bundle).root), "verified": True}
        return report
    @app.tool()
    def get_thread_trace(name: str, tid: int | None = None, page: int = 0) -> dict:
        """Return one capture's recorded thread events in pages of 200.

        Args:
            name: Relative .fault or .json capture filename.
            tid: Optional operating-system thread ID to filter by.
            page: Zero-based page number.
        """
        rows = thread_trace(_load(root, name), tid)
        return {"items": rows[page * 200:(page + 1) * 200], "page": page, "page_size": 200, "total": len(rows)}
    @app.tool()
    def get_fault_flow(name: str, bundle: str | None = None, max_events: int = 80) -> dict:
        """Return a bounded runtime fault-flow model without writing reports.

        Instrumented nesting, record order, static candidates and uncertainty
        remain distinct. Bundle paths stay within the allowlisted root.
        """
        from .fault_report import build_fault_report
        return build_fault_report(_load(root, name), bundle=_bundle(root, bundle) if bundle else None,
                                  max_events=max_events)
    @app.tool()
    def get_rpc_trace(name: str, page: int = 0) -> dict:
        """Return recorded RPC observations, static candidates, and unresolved limits.

        Args:
            name: Relative .fault or .json capture filename.
            page: Zero-based page number; observed events are returned 200 at a time.
        """
        decoded = rpc_trace(_load(root, name))
        page = max(0, page)
        decoded["total"] = len(decoded["observed"])
        start = page * 200
        decoded["observed"] = decoded["observed"][start:start + 200]
        decoded["page"] = page
        decoded["page_size"] = 200
        return decoded
    @app.tool()
    def collect_faults(names: list[str], trace_id: str | None = None, correlation_id: str | None = None, page: int = 0) -> dict:
        """Group up to 1,000 captures by explicit trace or correlation identifiers.

        Results distinguish observations, static candidates, and unresolved data;
        shared names or timestamps alone are not treated as causal links.
        Args:
            names: Relative capture filenames beneath the configured root.
            trace_id: Optional exact trace identifier filter.
            correlation_id: Optional exact correlation identifier filter.
            page: Zero-based page number; results contain at most 200 captures.
        """
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        paths = [_safe_artifact(root, name) for name in names]
        result = collect_artifacts(paths, trace_id=trace_id, correlation_id=correlation_id)
        start = max(0, page) * 200
        result["artifacts"] = result["artifacts"][start:start + 200]; result["page"] = max(0, page); result["page_size"] = 200
        return result
    @app.tool()
    def get_timeline(names: list[str]) -> dict:
        """Build a bounded timeline from up to 1,000 captures in recorded time order.

        Args:
            names: Relative .fault or .json capture filenames beneath the configured root.
        """
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        reports = [collect_file(_safe_artifact(root, name)) for name in names]
        return build_timeline(reports)
    @app.tool()
    def get_process_relations(names: list[str], page: int = 0) -> dict:
        """Join only explicit IPC/RPC endpoint evidence across up to 1,000 captures.

        Process identity or temporal proximity alone does not prove causality.
        Args:
            names: Relative capture filenames beneath the configured root.
            page: Zero-based page number; observations are returned 200 at a time.
        """
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        result = process_relations([collect_file(_safe_artifact(root, name)) for name in names])
        page = max(0, page)
        result["total"] = len(result["observed"])
        start = page * 200
        result["observed"] = result["observed"][start:start + 200]
        result["page"] = page
        result["page_size"] = 200
        return result
    @app.tool()
    def get_evidence_summary(name: str) -> dict:
        """Summarize one capture without merging observed, static, or unresolved evidence.

        Args:
            name: Relative .fault or .json capture filename.
        """
        return evidence_summary([_load(root, name)])
    @app.tool()
    def get_incident_report(names: list[str], page: int = 0) -> dict:
        """Create a read-only incident projection from up to 1,000 captures.

        The report keeps recorded RPC observations, static candidates, and
        unresolved evidence separate. RPC observations are paged by 200.
        Args:
            names: Relative capture filenames beneath the configured root.
            page: Zero-based RPC observation page.
        """
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        result = incident_report([collect_file(_safe_artifact(root, name)) for name in names])
        page = max(0, page)
        events = result["observed"]["rpc_events"]
        result["observed"]["rpc_events"] = events[page * 200:(page + 1) * 200]
        result["page"] = page
        result["page_size"] = 200
        result["total_rpc_events"] = len(events)
        return result
    @app.tool()
    def get_session_manifest(names: list[str], page: int = 0) -> dict:
        """Build a read-only session manifest from up to 1,000 captures.

        Participants are returned in pages of 200; inferred session grouping is
        not proof of cross-process causality.
        Args:
            names: Relative capture filenames beneath the configured root.
            page: Zero-based participant page.
        """
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        reports = [collect_file(_safe_artifact(root, name)) for name in names]
        result = session_manifest(reports, artifact_refs=names)
        page = max(0, page)
        participants = result["participants"]
        result["participants"] = participants[page * 200:(page + 1) * 200]
        result["page"] = page
        result["page_size"] = 200
        result["total_participants"] = len(participants)
        return result
    @app.tool()
    def get_process_participants(names: list[str], page: int = 0) -> dict:
        """List process metadata observed in up to 1,000 captures, in pages of 200.

        Args:
            names: Relative capture filenames beneath the configured root.
            page: Zero-based participant page.
        """
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        reports = [collect_file(_safe_artifact(root, name)) for name in names]
        result = process_participants(reports, artifact_refs=names)
        page = max(0, page)
        participants = result["participants"]
        result["participants"] = participants[page * 200:(page + 1) * 200]
        result["page"] = page
        result["page_size"] = 200
        result["total_participants"] = len(participants)
        return result
    @app.tool()
    def list_sessions(db: str = "evidence.sqlite3", start_ns: int | None = None,
                      end_ns: int | None = None, trust_state: str | None = None,
                      page: int = 0) -> dict:
        """List sessions from an existing evidence store using read-only access.

        Args:
            db: Existing .sqlite, .db, or .sqlite3 file beneath the root.
            start_ns: Optional inclusive lower bound for recorded monotonic time.
            end_ns: Optional inclusive upper bound for recorded monotonic time.
            trust_state: Optional exact trust-state filter.
            page: Zero-based page number.
        """
        store = EvidenceStore(_safe_store(root, db), readonly=True)
        try:
            return store.list_sessions(start_ns=start_ns, end_ns=end_ns,
                                       trust_state=trust_state, page=page)
        except (EvidenceStoreError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        finally:
            store.close()
    @app.tool()
    def get_session(session_id: str | None, db: str = "evidence.sqlite3",
                    start_ns: int | None = None, end_ns: int | None = None,
                    trust_state: str | None = None, page: int = 0) -> dict:
        """Read one session projection, or list sessions when session_id is null.

        Args:
            session_id: Exact session identifier, or null to use the supplied filters.
            db: Existing evidence-store filename beneath the root.
            start_ns: Optional inclusive lower time bound.
            end_ns: Optional inclusive upper time bound.
            trust_state: Optional exact trust-state filter.
            page: Zero-based page number.
        """
        """Return one session projection without merging evidence classes."""
        store = EvidenceStore(_safe_store(root, db), readonly=True)
        try:
            return store.get_session(session_id, start_ns=start_ns, end_ns=end_ns,
                                     trust_state=trust_state, page=page)
        except (EvidenceStoreError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        finally:
            store.close()
    @app.tool()
    def get_provenance(db: str = "evidence.sqlite3", session_id: str | None = None,
                       artifact_id: int | None = None, trust_state: str | None = None,
                       page: int = 0) -> dict:
        """Read provenance and trust rows for artifacts in an existing evidence store.

        Args:
            db: Existing evidence-store filename beneath the root.
            session_id: Optional exact session identifier.
            artifact_id: Optional exact numeric artifact row ID.
            trust_state: Optional exact trust-state filter.
            page: Zero-based page number.
        """
        store = EvidenceStore(_safe_store(root, db), readonly=True)
        try:
            return store.get_provenance(session_id=session_id, artifact_id=artifact_id,
                                        trust_state=trust_state, page=page)
        except (EvidenceStoreError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        finally:
            store.close()
    @app.tool()
    def list_incidents(db: str = "evidence.sqlite3", session_id: str | None = None,
                       start_ns: int | None = None, end_ns: int | None = None,
                       trust_state: str | None = None, page: int = 0) -> dict:
        """List agent-declared incident rows without inferring root cause or causality.

        Args:
            db: Existing evidence-store filename beneath the root.
            session_id: Optional exact session identifier.
            start_ns: Optional inclusive lower time bound.
            end_ns: Optional inclusive upper time bound.
            trust_state: Optional exact trust-state filter.
            page: Zero-based page number.
        """
        try:
            store = EvidenceStore(_safe_store(root, db), readonly=True)
            try:
                return store.list_incidents(session_id=session_id, start_ns=start_ns,
                                            end_ns=end_ns, trust_state=trust_state, page=page)
            finally:
                store.close()
        except (EvidenceStoreError, ValueError) as exc:
            return {"schema": 2, "error": {"code": "INCIDENT_QUERY_ERROR", "message": str(exc)}}
    @app.tool()
    def get_incident_slice(incident_id: str, db: str = "evidence.sqlite3",
                           trust_state: str | None = None, page: int = 0) -> dict:
        """Read bounded process, artifact, event, and source rows for one incident.

        Args:
            incident_id: Exact incident identifier already present in the store.
            db: Existing evidence-store filename beneath the root.
            trust_state: Optional exact trust-state filter.
            page: Zero-based page number.
        """
        """Return bounded process/artifact/event/source evidence for one incident."""
        try:
            store = EvidenceStore(_safe_store(root, db), readonly=True)
            try:
                return store.get_incident_slice(incident_id, trust_state=trust_state, page=page)
            finally:
                store.close()
        except (EvidenceStoreError, ValueError) as exc:
            return {"schema": 2, "error": {"code": "INCIDENT_QUERY_ERROR", "message": str(exc)}}
    @app.tool()
    def get_unresolved(incident_id: str, db: str = "evidence.sqlite3", page: int = 0) -> dict:
        """Read only unresolved evidence rows associated with one declared incident.

        Args:
            incident_id: Exact incident identifier already present in the store.
            db: Existing evidence-store filename beneath the root.
            page: Zero-based page number.
        """
        try:
            store = EvidenceStore(_safe_store(root, db), readonly=True)
            try:
                return store.get_unresolved(incident_id, page=page)
            finally:
                store.close()
        except (EvidenceStoreError, ValueError) as exc:
            return {"schema": 2, "error": {"code": "INCIDENT_QUERY_ERROR", "message": str(exc)}}
    @app.tool()
    def get_source_evidence(incident_id: str, bundle: str,
                            db: str = "evidence.sqlite3",
                            function_ids: list[str] | None = None, page: int = 0) -> dict:
        """Return source citations only when paths and hashes verify against a bundle.

        Args:
            incident_id: Exact incident identifier already present in the store.
            bundle: Relative source-bundle directory beneath the configured root.
            db: Existing evidence-store filename beneath the root.
            function_ids: Optional exact function identifiers to narrow the result.
            page: Zero-based page number.
        """
        try:
            loaded = _bundle(root, bundle)
            store = EvidenceStore(_safe_store(root, db), readonly=True)
            try:
                return store.get_source_evidence(incident_id, loaded.root,
                                                 function_ids=function_ids, page=page)
            finally:
                store.close()
        except (EvidenceStoreError, ValueError) as exc:
            return {"schema": 2, "error": {"code": "SOURCE_EVIDENCE_ERROR", "message": str(exc)}}
    @app.tool()
    def discover_artifacts(pattern: str = "fault-*.fault", include_json: bool = False, page: int = 0) -> dict:
        """Find and validate artifact files directly under the configured root.

        Args:
            pattern: Filename glob applied within the root; it cannot escape the root.
            include_json: Also include JSON artifacts when true.
            page: Zero-based page number; results are returned 200 at a time.
        """
        result = inspect_spool(root, pattern=pattern, include_json=include_json, limit=10000)
        page = max(0, page)
        result["total"] = len(result["artifacts"])
        start = page * 200
        result["artifacts"] = result["artifacts"][start:start + 200]
        result["page"] = page
        result["page_size"] = 200
        return result
    @app.tool()
    def query_artifact_index(name: str, trace_id: str | None = None, correlation_id: str | None = None, page: int = 0) -> dict:
        """Query an existing SQLite artifact index by exact trace/correlation ID.

        Args:
            name: Relative .sqlite or .db filename beneath the configured root.
            trace_id: Optional exact trace identifier.
            correlation_id: Optional exact correlation identifier.
            page: Zero-based page number; returns at most 200 rows.
        """
        path = (root / name).resolve()
        if root.resolve() not in path.parents or path.suffix not in (".sqlite", ".db") or not path.is_file(): raise ValueError("index is outside the allowlisted root or missing")
        index = ArtifactIndex(path)
        try:
            rows = index.query(trace_id=trace_id, correlation_id=correlation_id, limit=200, offset=max(page, 0) * 200)
            return {"schema": 1, "count": len(rows), "page": max(page, 0), "page_size": 200, "artifacts": rows}
        finally: index.close()
    @app.tool()
    def resolve_addresses(name: str, addresses: list[int], bundle: str | None = None) -> dict:
        """Resolve up to 1,000 recorded addresses against capture module identities.

        Args:
            name: Relative .fault or .json capture filename.
            addresses: Numeric instruction addresses to resolve.
            bundle: Optional verified source-bundle directory beneath the root.
        """
        if len(addresses) > 1000: raise ValueError("maximum 1000 addresses")
        loaded = _bundle(root, bundle) if bundle else None
        return {"items": resolve_address_records(_load(root, name), addresses, bundle=loaded)}
    @app.tool()
    def get_function_source(name: str, function_id: str, bundle: str | None = None) -> dict:
        """Return exact source lines for a function from a verified source bundle.

        Source is unavailable unless the bundle's build identity and file hashes verify.
        Args:
            name: Relative .fault or .json capture filename.
            function_id: Exact compiler-derived function identifier.
            bundle: Required source-bundle directory beneath the configured root.
        """
        _load(root, name)
        loaded = _bundle(root, bundle) if bundle else None
        if loaded is None: raise ValueError("bundle is required for verified source lookup")
        return verified_function_source(function_id, loaded)
    @app.tool()
    def get_call_relations(name: str, function_id: str, direction: str = "outbound", bundle: str | None = None) -> dict:
        """Return static source call candidates around a function; these are not runtime proof.

        Args:
            name: Relative .fault or .json capture filename.
            function_id: Exact compiler-derived function identifier.
            direction: Either outbound or inbound.
            bundle: Required verified source-bundle directory beneath the root.
        """
        _load(root, name)
        loaded = _bundle(root, bundle) if bundle else None
        if loaded is None: raise ValueError("bundle is required for verified call relations")
        return verified_call_relations(function_id, direction, loaded)
    return app
