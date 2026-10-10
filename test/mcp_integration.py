#!/usr/bin/env python3
"""Direct FastMCP ToolManager integration check against a verified bundle."""
from __future__ import annotations
import argparse, json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.mcp_server import make_server

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--root", type=Path, required=True); p.add_argument("--artifact", required=True); p.add_argument("--bundle", required=True); p.add_argument("--function-id", required=True); ns = p.parse_args()
    server = make_server(ns.root); tools = server._tool_manager._tools
    expected = {"get_capabilities", "check_store", "open_fault", "get_thread_trace", "get_rpc_trace", "get_process_relations", "get_evidence_summary", "get_incident_report", "get_session_manifest", "get_process_participants", "list_sessions", "get_session", "get_provenance", "list_incidents", "get_incident_slice", "get_source_evidence", "get_unresolved", "discover_artifacts", "resolve_addresses", "get_function_source", "get_call_relations"}
    assert expected <= set(tools), sorted(tools)
    descriptions = {name: (tools[name].description or "").strip() for name in expected}
    assert all(len(description) >= 30 for description in descriptions.values()), {
        name: description for name, description in descriptions.items() if len(description) < 30
    }
    opened = tools["open_fault"].fn(ns.artifact, ns.bundle)
    assert opened["bundle"]["verified"] is True
    trace = tools["get_thread_trace"].fn(ns.artifact, None, 0)
    assert "items" in trace and "total" in trace
    rpc = tools["get_rpc_trace"].fn(ns.artifact, 0)
    assert {"observed", "static_candidates", "unresolved"} <= rpc.keys()
    relations = tools["get_process_relations"].fn([ns.artifact], 0)
    assert {"observed", "static_candidates", "unresolved"} <= relations.keys()
    summary = tools["get_evidence_summary"].fn(ns.artifact)
    assert {"observed", "static_candidates", "unresolved"} <= summary.keys()
    incident = tools["get_incident_report"].fn([ns.artifact], 0)
    assert {"observed", "static_candidates", "unresolved", "fields"} <= incident.keys()
    session = tools["get_session_manifest"].fn([ns.artifact], 0)
    assert {"session", "participants", "observed", "derived", "static_candidates", "unresolved"} <= session.keys()
    participants = tools["get_process_participants"].fn([ns.artifact], 0)
    assert {"session", "participants", "unresolved"} <= participants.keys()
    discovered = tools["discover_artifacts"].fn()
    assert {"artifacts", "count", "valid", "invalid", "page", "page_size"} <= discovered.keys()
    assert discovered["count"] >= 1 and discovered["valid"] >= 1
    resolved = tools["resolve_addresses"].fn(ns.artifact, [1], ns.bundle)
    assert len(resolved["items"]) == 1 and "resolved" in resolved["items"][0]
    source = tools["get_function_source"].fn(ns.artifact, ns.function_id, ns.bundle)
    assert source["resolved"] and source["source"]
    static_relations = tools["get_call_relations"].fn(ns.artifact, ns.function_id, "outbound", ns.bundle)
    assert static_relations["direction"] == "outbound" and "relations" in static_relations
    print(json.dumps({"status": "PASS", "tools": sorted(expected), "source_file": source["file"], "relations": len(static_relations["relations"]), "discovered": discovered["count"]}, sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
