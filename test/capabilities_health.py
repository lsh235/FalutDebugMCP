#!/usr/bin/env python3
"""v1.0 capability and read-only store-health contract checks."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.capabilities import CAPABILITY_MAX_BYTES, get_capabilities
from faultdebug.evidence_store import EvidenceStore, SCHEMA_VERSION


def main() -> int:
    contract = get_capabilities()
    required = {"open_fault", "get_thread_trace", "resolve_addresses",
                "get_function_source", "get_call_relations"}
    assert set(contract["required_tools"]) == required
    assert {"list_incidents", "get_incident_slice", "get_source_evidence", "get_unresolved"} <= set(contract["v09_tools"])
    assert contract["store_versions"]["base_schema"] == SCHEMA_VERSION
    assert set(contract["evidence_classes"]) == {"observed", "derived", "static_candidates", "unresolved", "hypotheses"}
    assert len(json.dumps(contract, separators=(",", ":")).encode()) <= CAPABILITY_MAX_BYTES
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        missing = EvidenceStore.inspect_health(root / "missing.sqlite3")
        assert missing["status"] == "error" and missing["error"]["code"] == "STORE_MISSING"
        db = root / "evidence.sqlite3"
        with EvidenceStore(db):
            pass
        health = EvidenceStore.inspect_health(db)
        assert health["status"] == "healthy" and health["read_only"] is True
        assert health["incident_tables"]["status"] == "available"
        before = db.read_bytes()
        assert EvidenceStore.inspect_health(db)["status"] == "healthy"
        assert db.read_bytes() == before
        legacy_v08 = root / "v08.sqlite3"
        connection = sqlite3.connect(legacy_v08)
        for table in ("artifact", "process", "evidence", "relation", "provenance", "quarantine"):
            connection.execute(f"CREATE TABLE {table} (id INTEGER)")
        connection.execute("PRAGMA user_version=2")
        connection.commit(); connection.close()
        additive = EvidenceStore.inspect_health(legacy_v08)
        assert additive["status"] == "compatible_additive_upgrade"
        assert additive["migration"]["required"] is True
        assert additive["incident_tables"]["status"] == "needs_writable_upgrade"
        cli = subprocess.run([sys.executable, "-m", "faultdebug.cli", "capabilities"], cwd=ROOT,
                             check=True, capture_output=True, text=True)
        assert json.loads(cli.stdout)["contract_version"] == "1.0"
        health_cli = subprocess.run([sys.executable, "-m", "faultdebug.cli", "evidence-health", "--db", str(db)],
                                    cwd=ROOT, check=True, capture_output=True, text=True)
        assert json.loads(health_cli.stdout)["status"] == "healthy"
    print("capabilities-health-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
