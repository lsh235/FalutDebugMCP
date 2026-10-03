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
        """Return the bounded v1.0 capability and evidence contract."""
        return capability_contract()
    @app.tool()
    def check_store(db: str = "evidence.sqlite3") -> dict:
        """Inspect store health and migration compatibility without writing."""
        path = (root / db).resolve()
        if root.resolve() not in path.parents or path.suffix not in (".sqlite", ".db", ".sqlite3"):
            return {"schema": 2, "status": "error", "read_only": True,
                    "error": {"code": "STORE_PATH_INVALID", "message": "evidence store is outside the allowlisted root"}}
        return EvidenceStore.inspect_health(path)
    @app.tool()
    def open_fault(name: str, bundle: str | None = None) -> dict:
        report = _load(root, name)
        if bundle: report["bundle"] = {"path": str(_bundle(root, bundle).root), "verified": True}
        return report
    @app.tool()
    def get_thread_trace(name: str, tid: int | None = None, page: int = 0) -> dict:
        rows = thread_trace(_load(root, name), tid)
        return {"items": rows[page * 200:(page + 1) * 200], "page": page, "page_size": 200, "total": len(rows)}
    @app.tool()
    def get_rpc_trace(name: str, page: int = 0) -> dict:
        """Return semantic RPC observations and unresolved evidence limits."""
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
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        paths = [_safe_artifact(root, name) for name in names]
        result = collect_artifacts(paths, trace_id=trace_id, correlation_id=correlation_id)
        start = max(0, page) * 200
        result["artifacts"] = result["artifacts"][start:start + 200]; result["page"] = max(0, page); result["page_size"] = 200
        return result
    @app.tool()
    def get_timeline(names: list[str]) -> dict:
        if len(names) > 1000: raise ValueError("maximum 1000 artifacts")
        reports = [collect_file(_safe_artifact(root, name)) for name in names]
        return build_timeline(reports)
    @app.tool()
    def get_process_relations(names: list[str], page: int = 0) -> dict:
        """Join only explicit IPC/RPC endpoint evidence across artifacts."""
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
        """Summarize observed, static-candidate, and unresolved evidence."""
        return evidence_summary([_load(root, name)])
    @app.tool()
    def get_incident_report(names: list[str], page: int = 0) -> dict:
        """Return a read-only incident report with separate evidence classes."""
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
        """Return a read-only session manifest with separate evidence classes."""
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
        """Return read-only process participant metadata for a session."""
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
        """List deterministic session summaries from a read-only evidence store."""
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
        """Return provenance and trust rows for local evidence artifacts."""
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
        """List bounded agent-declared incidents without causal inference."""
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
        """Return only unresolved evidence for an agent-declared incident."""
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
        """Return exact file/line/hash citations from a verified source bundle."""
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
        """Discover and validate bounded artifact spool entries."""
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
        path = (root / name).resolve()
        if root.resolve() not in path.parents or path.suffix not in (".sqlite", ".db") or not path.is_file(): raise ValueError("index is outside the allowlisted root or missing")
        index = ArtifactIndex(path)
        try:
            rows = index.query(trace_id=trace_id, correlation_id=correlation_id, limit=200, offset=max(page, 0) * 200)
            return {"schema": 1, "count": len(rows), "page": max(page, 0), "page_size": 200, "artifacts": rows}
        finally: index.close()
    @app.tool()
    def resolve_addresses(name: str, addresses: list[int], bundle: str | None = None) -> dict:
        if len(addresses) > 1000: raise ValueError("maximum 1000 addresses")
        loaded = _bundle(root, bundle) if bundle else None
        return {"items": resolve_address_records(_load(root, name), addresses, bundle=loaded)}
    @app.tool()
    def get_function_source(name: str, function_id: str, bundle: str | None = None) -> dict:
        _load(root, name)
        loaded = _bundle(root, bundle) if bundle else None
        if loaded is None: raise ValueError("bundle is required for verified source lookup")
        return verified_function_source(function_id, loaded)
    @app.tool()
    def get_call_relations(name: str, function_id: str, direction: str = "outbound", bundle: str | None = None) -> dict:
        _load(root, name)
        loaded = _bundle(root, bundle) if bundle else None
        if loaded is None: raise ValueError("bundle is required for verified call relations")
        return verified_call_relations(function_id, direction, loaded)
    return app
