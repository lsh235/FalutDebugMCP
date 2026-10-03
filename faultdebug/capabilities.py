"""Stable, bounded capability contract for CLI and MCP clients."""
from __future__ import annotations

import json
from typing import Any

CAPABILITY_CONTRACT_VERSION = 1
CAPABILITY_MAX_BYTES = 16 * 1024


def get_capabilities() -> dict[str, Any]:
    """Return the supported local artifact, store, and evidence contract."""
    result: dict[str, Any] = {
        "schema": CAPABILITY_CONTRACT_VERSION,
        "contract_version": "1.0",
        "artifact_versions": {
            "fdar": 1, "shared_memory_abi": 1, "semantic_rpc": 1,
            "session_manifest": 1, "incident_query": 1,
        },
        "store_versions": {"base_schema": 2, "incident_tables": "additive-1"},
        "required_tools": [
            "open_fault", "get_thread_trace", "resolve_addresses",
            "get_function_source", "get_call_relations",
        ],
        "additional_tools": [
            "get_capabilities", "check_store", "get_rpc_trace",
            "get_process_relations", "get_evidence_summary", "get_incident_report",
            "get_session_manifest", "get_process_participants", "list_sessions",
            "get_session", "get_provenance",
        ],
        "v09_tools": [
            "list_incidents", "get_incident_slice", "get_source_evidence",
            "get_unresolved",
        ],
        "limits": {
            "artifacts_per_query": 1000,
            "page_size": 200,
            "max_source_function_ids": 100,
            "max_incident_observed_events": 1000,
            "max_rpc_events": 1024,
            "max_artifact_id_length": 256,
        },
        "evidence_classes": [
            "observed", "derived", "static_candidates", "unresolved", "hypotheses",
        ],
        "supported_signals": ["SIGILL", "SIGSEGV", "SIGBUS", "SIGFPE", "SIGABRT"],
        "platform_toolchain": {
            "platform": "Ubuntu 24.04 x86_64",
            "runtime": "C11",
            "python": "3.12",
            "clang": "18",
            "build": ["CMake", "Ninja"],
            "mcp_transport": "stdio",
        },
        "security": {
            "local_artifacts_only": True,
            "remote_transport": False,
            "encryption": False,
            "source_lookup": "verified_bundle_only",
        },
    }
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > CAPABILITY_MAX_BYTES:
        raise RuntimeError("capability contract exceeds bounded response size")
    return result
