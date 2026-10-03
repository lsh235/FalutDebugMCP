"""Restartable SQLite evidence store for local fault artifacts.

The store is deliberately a projection over verified local artifacts.  It
keeps runtime observations, derived relations, static candidates, unresolved
gaps, and hypotheses in separate tables/classes.  Invalid inputs are copied
to a quarantine directory and never become valid evidence rows.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

from .format import collect_file
from .bundle import BundleError, load_bundle, sha256_file
from .inspect import verified_function_source
from .session import SessionDecodeError, session_manifest

SCHEMA_VERSION = 2
INCIDENT_QUERY_SCHEMA_VERSION = 1  # additive v0.9 tables; base store remains schema v2
PAGE_SIZE = 200
TRUST_STATES = {"verified", "unresolved", "quarantined"}
EVIDENCE_CLASSES = {"observed", "derived", "static_candidates", "unresolved", "hypotheses"}


class EvidenceStoreError(ValueError):
    """The store cannot safely accept or query an input."""


class EvidenceValidationError(EvidenceStoreError):
    """The artifact is readable but its declared contract does not match."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(path: Path) -> tuple[str, bytes]:
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), raw


def _bounded_page(page: int, limit: int = PAGE_SIZE) -> tuple[int, int]:
    try:
        page = max(0, int(page))
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise EvidenceStoreError("page and limit must be integers") from exc
    if limit < 1 or limit > 1000:
        raise EvidenceStoreError("limit must be between 1 and 1000")
    return page, limit


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _provenance_values(report: Mapping[str, Any]) -> dict[str, str | None]:
    raw = report.get("provenance")
    provenance = raw if isinstance(raw, Mapping) else {}
    nested_source = provenance.get("source_manifest")
    nested_index = provenance.get("index") or provenance.get("index_manifest")
    nested_binary = provenance.get("binary")

    def value(*keys: str) -> str | None:
        result = _first(provenance, *keys)
        if isinstance(result, Mapping):
            result = result.get("sha256")
        if result is None:
            result = _first(report, *keys)
        if isinstance(result, Mapping):
            result = result.get("sha256")
        return str(result).lower() if isinstance(result, str) and result else None

    build_id = value("build_id")
    module_ids = {
        str(row.get("build_id")).lower()
        for row in report.get("modules", [])
        if isinstance(row, Mapping) and row.get("build_id")
    }
    if build_id is None and len(module_ids) == 1:
        build_id = next(iter(module_ids))
    source_sha = value("source_sha256", "source_manifest_sha256")
    if source_sha is None and isinstance(nested_source, Mapping):
        source_sha = str(nested_source.get("sha256")).lower() if nested_source.get("sha256") else None
    index_sha = value("index_sha256", "compile_commands_sha256")
    if index_sha is None and isinstance(nested_index, Mapping):
        index_sha = str(nested_index.get("sha256")).lower() if nested_index.get("sha256") else None
    binary_sha = value("binary_sha256")
    if binary_sha is None and isinstance(nested_binary, Mapping):
        binary_sha = str(nested_binary.get("sha256")).lower() if nested_binary.get("sha256") else None
    return {"build_id": build_id, "binary_sha256": binary_sha,
            "source_sha256": source_sha, "index_sha256": index_sha}


def _expected_values(expected: Mapping[str, Any] | None, **kwargs: Any) -> dict[str, str | None]:
    result = {key: None for key in ("build_id", "binary_sha256", "source_sha256", "index_sha256")}
    if expected:
        for key in result:
            value = expected.get(key)
            if value is not None:
                result[key] = str(value).lower()
    for key, value in kwargs.items():
        if key in result and value is not None:
            result[key] = str(value).lower()
    return result


class EvidenceStore:
    """SQLite schema v2 store with atomic ingest and deterministic queries."""

    schema_version = SCHEMA_VERSION

    def __init__(self, path: Path, *, quarantine_dir: Path | None = None, readonly: bool = False):
        self.path = Path(path)
        if readonly and not self.path.is_file():
            raise EvidenceStoreError(f"evidence store does not exist: {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir = Path(quarantine_dir) if quarantine_dir else self.path.parent / "quarantine"
        if not readonly:
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        if readonly:
            self.db = sqlite3.connect(f"file:{self.path.resolve()}?mode=ro", uri=True)
        else:
            self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        if readonly:
            version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
            if version != SCHEMA_VERSION:
                self.db.close()
                raise EvidenceStoreError(f"read-only evidence store schema must be {SCHEMA_VERSION}, got {version}")
        else:
            self._migrate()

    def _migrate(self) -> None:
        version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise EvidenceStoreError(f"unsupported evidence store schema version: {version}")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifact (
                artifact_id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                ingested_ns INTEGER NOT NULL,
                session_id TEXT,
                identity_source TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('valid','quarantined')),
                trust_state TEXT NOT NULL CHECK(trust_state IN ('verified','unresolved','quarantined')),
                collector_ok INTEGER,
                collector_status TEXT,
                collector_phase TEXT,
                collector_partial INTEGER,
                process_start_ns INTEGER,
                target_returncode INTEGER,
                target_signal INTEGER
            );
            CREATE TABLE IF NOT EXISTS process (
                process_row_id INTEGER PRIMARY KEY,
                artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
                participant_id TEXT NOT NULL,
                session_id TEXT,
                runtime_process_id TEXT,
                process_generation INTEGER,
                parent_process_id TEXT,
                role TEXT,
                pid INTEGER,
                parent_pid INTEGER,
                executable TEXT,
                start_monotonic_ns INTEGER,
                trust_state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id INTEGER PRIMARY KEY,
                artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
                evidence_class TEXT NOT NULL CHECK(evidence_class IN ('observed','derived','static_candidates','unresolved','hypotheses')),
                kind TEXT NOT NULL,
                sequence INTEGER,
                timestamp_ns INTEGER,
                payload TEXT NOT NULL,
                trust_state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS relation (
                relation_id INTEGER PRIMARY KEY,
                artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
                relation_kind TEXT NOT NULL,
                from_participant TEXT,
                to_participant TEXT,
                timestamp_ns INTEGER,
                payload TEXT NOT NULL,
                trust_state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provenance (
                provenance_id INTEGER PRIMARY KEY,
                artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
                build_id TEXT,
                binary_sha256 TEXT,
                source_sha256 TEXT,
                index_sha256 TEXT,
                declared_artifact_sha256 TEXT,
                trust_state TEXT NOT NULL,
                reason TEXT,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS quarantine (
                quarantine_id INTEGER PRIMARY KEY,
                source_path TEXT NOT NULL,
                sha256 TEXT,
                quarantined_path TEXT,
                reason TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_ns INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS incident (
                incident_id TEXT PRIMARY KEY,
                session_id TEXT,
                trigger_process_id TEXT,
                trigger_signal INTEGER,
                status TEXT,
                phase TEXT,
                partial INTEGER,
                first_seen_ns INTEGER,
                trust_state TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS incident_artifact (
                incident_id TEXT NOT NULL REFERENCES incident(incident_id) ON DELETE CASCADE,
                artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
                evidence_class TEXT,
                PRIMARY KEY(incident_id, artifact_id)
            );
            CREATE TABLE IF NOT EXISTS source_reference (
                source_reference_id INTEGER PRIMARY KEY,
                incident_id TEXT REFERENCES incident(incident_id) ON DELETE CASCADE,
                artifact_id INTEGER NOT NULL REFERENCES artifact(artifact_id) ON DELETE CASCADE,
                function_id TEXT,
                bundle_path TEXT,
                file TEXT,
                line_start INTEGER,
                line_end INTEGER,
                sha256 TEXT,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS artifact_session_idx ON artifact(session_id, process_start_ns, artifact_id);
            CREATE INDEX IF NOT EXISTS artifact_trust_idx ON artifact(trust_state, process_start_ns, artifact_id);
            CREATE INDEX IF NOT EXISTS evidence_artifact_idx ON evidence(artifact_id, evidence_class, timestamp_ns, evidence_id);
            CREATE INDEX IF NOT EXISTS relation_artifact_idx ON relation(artifact_id, timestamp_ns, relation_id);
            CREATE INDEX IF NOT EXISTS provenance_artifact_idx ON provenance(artifact_id, provenance_id);
            CREATE INDEX IF NOT EXISTS incident_session_idx ON incident(session_id, first_seen_ns, incident_id);
            CREATE INDEX IF NOT EXISTS incident_artifact_idx ON incident_artifact(incident_id, artifact_id);
            CREATE INDEX IF NOT EXISTS source_reference_incident_idx ON source_reference(incident_id, source_reference_id);
            """
        )
        # v0.6 ArtifactIndex used a plural ``artifacts`` table.  Keep it intact
        # for compatibility, while copying readable legacy rows into v2.
        if version < SCHEMA_VERSION:
            self._migrate_legacy_rows()
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    @classmethod
    def inspect_health(cls, path: Path) -> dict[str, Any]:
        """Inspect store compatibility without creating or migrating anything."""
        path = Path(path)
        base_tables = {"artifact", "process", "evidence", "relation", "provenance", "quarantine"}
        incident_tables = {"incident", "incident_artifact", "source_reference"}
        if not path.is_file():
            return {"schema": SCHEMA_VERSION, "status": "error", "read_only": True,
                    "path": str(path), "error": {"code": "STORE_MISSING", "message": "evidence store does not exist"}}
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            missing_base = sorted(base_tables - names)
            missing_incident = sorted(incident_tables - names)
            legacy = "artifacts" in names
            base_compatible = version == SCHEMA_VERSION and not missing_base and integrity == "ok"
            migration_required = version < SCHEMA_VERSION or bool(missing_base)
            additive_status = "available" if not missing_incident else "needs_writable_upgrade"
            if integrity != "ok":
                status = "error"
            elif migration_required:
                status = "migration_required"
            elif missing_incident:
                status = "compatible_additive_upgrade"
            else:
                status = "healthy"
            return {
                "schema": SCHEMA_VERSION, "status": status, "read_only": True,
                "path": str(path.resolve()), "user_version": version,
                "base_schema": {"compatible": base_compatible, "required": sorted(base_tables),
                                "missing": missing_base},
                "incident_tables": {"status": additive_status, "required": sorted(incident_tables),
                                    "missing": missing_incident},
                "migration": {"required": migration_required or bool(missing_incident),
                               "legacy_artifact_index": legacy,
                               "action": "open writable EvidenceStore to migrate" if (migration_required or missing_incident) else None},
                "integrity": integrity,
            }
        except (OSError, sqlite3.DatabaseError) as exc:
            return {"schema": SCHEMA_VERSION, "status": "error", "read_only": True,
                    "path": str(path), "error": {"code": "STORE_UNREADABLE", "message": str(exc)}}
        finally:
            if connection is not None:
                connection.close()

    @classmethod
    def health(cls, path: Path) -> dict[str, Any]:
        """Compatibility alias for :meth:`inspect_health`."""
        return cls.inspect_health(path)

    def _migrate_legacy_rows(self) -> None:
        exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='artifacts'").fetchone()
        if not exists:
            return
        rows = self.db.execute("SELECT path,sha256,payload FROM artifacts").fetchall()
        for row in rows:
            try:
                report = json.loads(row["payload"])
                if not isinstance(report, dict):
                    continue
                self._insert_report(Path(row["path"]), report, str(row["sha256"]), 0,
                                    trust_state="unresolved", trust_reason="migrated_legacy_index")
            except (ValueError, TypeError, json.JSONDecodeError):
                continue

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "EvidenceStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _quarantine(self, path: Path, reason: str, detail: str, raw: bytes | None, digest: str | None) -> dict[str, Any]:
        source = str(path.resolve())
        previous = self.db.execute("SELECT artifact_id FROM artifact WHERE path=?", (source,)).fetchone()
        if previous:
            self.db.execute("DELETE FROM artifact WHERE artifact_id=?", (previous["artifact_id"],))
        target: Path | None = None
        if raw is not None:
            stem = path.name.replace("/", "_").replace("\\", "_")
            target = self.quarantine_dir / f"{stem}.{digest or 'unknown'[:16]}.quarantine"
            try:
                if not target.exists():
                    temporary = target.with_suffix(target.suffix + ".tmp")
                    temporary.write_bytes(raw)
                    os.replace(temporary, target)
            except OSError:
                target = None
        self.db.execute("INSERT INTO quarantine(source_path,sha256,quarantined_path,reason,detail,created_ns) VALUES(?,?,?,?,?,?)",
                        (source, digest, str(target) if target else None, reason, detail, time.time_ns()))
        self.db.commit()
        return {"status": "quarantined", "source_path": source, "sha256": digest,
                "quarantined_path": str(target) if target else None, "reason": reason, "detail": detail}

    def _validate(self, report: dict[str, Any], expected: Mapping[str, Any] | None, *, expected_session_id: str | None,
                  expected_process_id: str | None, expected_process_generation: int | None) -> dict[str, Any]:
        provenance_object = report.get("provenance")
        if isinstance(provenance_object, Mapping):
            provenance_schema = _first(provenance_object, "schema", "version")
            if provenance_schema is not None and provenance_schema != 1:
                raise EvidenceValidationError(f"unsupported provenance schema version: {provenance_schema!r}")
        try:
            manifest = session_manifest([report])
        except (SessionDecodeError, ValueError) as exc:
            raise EvidenceValidationError(str(exc)) from exc
        actual_session = manifest["session"].get("session_id")
        if expected_session_id is not None and actual_session != expected_session_id:
            raise EvidenceValidationError("session_id does not match expected value")
        participants = manifest.get("participants", [])
        process = report.get("process") if isinstance(report.get("process"), Mapping) else {}
        identity = process.get("identity") if isinstance(process.get("identity"), Mapping) else {}
        actual_process_id = _first(process, "process_id") or _first(identity, "process_id")
        raw_generation = _first(process, "process_generation") or _first(identity, "process_generation")
        actual_generation = _int_or_none(raw_generation)
        if raw_generation is not None and (actual_generation is None or not 1 <= actual_generation <= 0xFFFFFFFF):
            raise EvidenceValidationError("process_generation must be between 1 and 2^32-1")
        if expected_process_id is not None and actual_process_id != expected_process_id:
            raise EvidenceValidationError("process_id does not match expected value")
        if expected_process_generation is not None and _int_or_none(actual_generation) != int(expected_process_generation):
            raise EvidenceValidationError("process_generation does not match expected value")
        expected_values = _expected_values(expected)
        declared = _provenance_values(report)
        for key, expected_value in expected_values.items():
            if expected_value is not None and declared[key] is not None and declared[key] != expected_value:
                raise EvidenceValidationError(f"{key} does not match expected provenance")
            if expected_value is not None and declared[key] is None:
                raise EvidenceValidationError(f"{key} is missing from artifact provenance")
        return {"manifest": manifest, "provenance": declared, "expected": expected_values,
                "process_id": actual_process_id, "process_generation": _int_or_none(actual_generation),
                "participants": participants}

    def _trust(self, report: Mapping[str, Any], validation: Mapping[str, Any], fdar_verified: bool) -> tuple[str, str]:
        if not fdar_verified:
            return "unresolved", "FDAR checksum unavailable for JSON artifact"
        declared = validation["provenance"]
        expected = validation["expected"]
        required = ("build_id", "binary_sha256", "source_sha256", "index_sha256")
        if not all(expected.get(key) is not None for key in required):
            return "unresolved", "trusted build/source/index provenance was not supplied"
        if not all(declared.get(key) == expected.get(key) for key in required):
            return "unresolved", "provenance is incomplete"
        return "verified", "FDAR checksum and supplied build/source/index provenance match"

    @staticmethod
    def _process_fields(report: Mapping[str, Any]) -> dict[str, Any]:
        process = report.get("process") if isinstance(report.get("process"), Mapping) else {}
        identity = process.get("identity") if isinstance(process.get("identity"), Mapping) else {}
        return {
            "pid": _int_or_none(_first(process, "pid")),
            "parent_pid": _int_or_none(_first(process, "parent_pid")),
            "executable": _first(process, "executable"),
            "start_monotonic_ns": _int_or_none(_first(process, "start_monotonic_ns")),
            "runtime_process_id": _first(process, "process_id") or _first(identity, "process_id"),
            "process_generation": _int_or_none(_first(process, "process_generation") or _first(identity, "process_generation")),
            "parent_process_id": _first(process, "parent_process_id") or _first(identity, "parent_process_id"),
            "role": _first(process, "role") or _first(identity, "role"),
        }

    def _insert_report(self, path: Path, report: dict[str, Any], digest: str, size: int,
                       *, trust_state: str, trust_reason: str, manifest: dict[str, Any] | None = None) -> int:
        manifest = manifest or session_manifest([report])
        session = manifest["session"]
        process_fields = self._process_fields(report)
        collector = report.get("collector") if isinstance(report.get("collector"), Mapping) else {}
        target = report.get("target") if isinstance(report.get("target"), Mapping) else {}
        existing = self.db.execute("SELECT artifact_id FROM artifact WHERE path=?", (str(path.resolve()),)).fetchone()
        if existing:
            self.db.execute("DELETE FROM artifact WHERE artifact_id=?", (existing["artifact_id"],))
        cur = self.db.execute(
            """INSERT INTO artifact(path,sha256,size,ingested_ns,session_id,identity_source,status,trust_state,
               collector_ok,collector_status,collector_phase,collector_partial,process_start_ns,target_returncode,target_signal)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(path.resolve()), digest, size, time.time_ns(), session.get("session_id"),
             session.get("identity_source", "absent"), "valid", trust_state,
             int(bool(collector.get("ok"))) if "ok" in collector else None,
             str(collector.get("status")) if collector.get("status") is not None else None,
             str(collector.get("phase")) if collector.get("phase") is not None else None,
             int(bool(collector.get("partial"))) if "partial" in collector else None,
             process_fields["start_monotonic_ns"], _int_or_none(target.get("returncode")), _int_or_none(target.get("signal"))))
        artifact_id = int(cur.lastrowid)
        agent_collector = collector.get("agent") if isinstance(collector.get("agent"), Mapping) else {}
        incident_id = _first(report, "incident_id") or _first(collector, "incident_id") or _first(agent_collector, "incident_id")
        if isinstance(incident_id, str) and 0 < len(incident_id) <= 256:
            trigger_process_id = _first(collector, "trigger_process_id") or _first(agent_collector, "trigger_process_id")
            trigger_signal = _int_or_none(_first(collector, "trigger_signal") or _first(agent_collector, "trigger_signal"))
            self.db.execute(
                """INSERT INTO incident(incident_id,session_id,trigger_process_id,trigger_signal,status,phase,partial,first_seen_ns,trust_state,payload)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(incident_id) DO UPDATE SET
                   session_id=COALESCE(excluded.session_id,incident.session_id),
                   trigger_process_id=COALESCE(excluded.trigger_process_id,incident.trigger_process_id),
                   trigger_signal=COALESCE(excluded.trigger_signal,incident.trigger_signal),
                   status=COALESCE(excluded.status,incident.status), phase=COALESCE(excluded.phase,incident.phase),
                   partial=COALESCE(excluded.partial,incident.partial),
                   first_seen_ns=CASE WHEN incident.first_seen_ns IS NULL THEN excluded.first_seen_ns
                                     WHEN excluded.first_seen_ns IS NULL THEN incident.first_seen_ns
                                     ELSE MIN(incident.first_seen_ns, excluded.first_seen_ns) END,
                   trust_state=CASE WHEN incident.trust_state='verified' AND excluded.trust_state='verified' THEN 'verified' ELSE 'unresolved' END""",
                (incident_id, session.get("session_id"), trigger_process_id, trigger_signal,
                 _first(collector, "status") or _first(agent_collector, "status"),
                 _first(collector, "phase") or _first(agent_collector, "phase"),
                 int(bool(_first(collector, "partial") if "partial" in collector else _first(agent_collector, "partial")))
                 if ("partial" in collector or "partial" in agent_collector) else None,
                 process_fields["start_monotonic_ns"], trust_state, _json({"collector": collector})))
            self.db.execute("INSERT OR REPLACE INTO incident_artifact(incident_id,artifact_id,evidence_class) VALUES(?,?,?)",
                            (incident_id, artifact_id, report.get("evidence_class")))
        for participant in manifest.get("participants", []):
            self.db.execute(
                """INSERT INTO process(artifact_id,participant_id,session_id,runtime_process_id,process_generation,
                   parent_process_id,role,pid,parent_pid,executable,start_monotonic_ns,trust_state)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (artifact_id, participant.get("participant_id", "unknown"), session.get("session_id"),
                 participant.get("process_id", process_fields["runtime_process_id"]),
                 _int_or_none(participant.get("process_generation", process_fields["process_generation"])),
                 participant.get("parent_process_id", process_fields["parent_process_id"]),
                 participant.get("role", process_fields["role"]), _int_or_none(participant.get("pid", process_fields["pid"])),
                 _int_or_none(participant.get("parent_pid", process_fields["parent_pid"])),
                 participant.get("executable", process_fields["executable"]),
                 _int_or_none(participant.get("start_monotonic_ns", process_fields["start_monotonic_ns"])), trust_state))
        observed = manifest.get("observed", {})
        derived = manifest.get("derived", {})
        candidates = manifest.get("static_candidates", [])
        unresolved = manifest.get("unresolved", [])
        rows: list[tuple[str, str, Any]] = []
        rows.extend(("observed", "rpc", value) for value in observed.get("rpc_events", []))
        # A peer snapshot is runtime evidence when the producer supplies it;
        # its collector phase/partial fields stay inside the payload.
        peer_snapshots = report.get("peer_snapshots", [])
        if isinstance(peer_snapshots, list):
            rows.extend(("observed", "peer_snapshot", value) for value in peer_snapshots)
        if report.get("evidence_class") in {"observed", "incident_snapshot"}:
            # Resident-agent artifacts carry the runtime snapshot marker on
            # the report itself.  Preserve collector phase/partial and the
            # existing process/target metadata without turning it into a
            # causal relation.
            rows.append(("observed", "peer_snapshot", {
                "evidence_class": report.get("evidence_class"),
                "process": report.get("process", {}),
                "target": report.get("target", {}),
                "collector": report.get("collector", {}),
            }))
        rows.extend(("static_candidates", "candidate", value) for value in candidates)
        rows.extend(("unresolved", "gap", value) for value in unresolved)
        hypotheses = report.get("hypotheses", [])
        if isinstance(hypotheses, list):
            rows.extend(("hypotheses", "hypothesis", value) for value in hypotheses)
        for evidence_class, kind, payload in rows:
            timestamp = payload.get("monotonic_ns") if isinstance(payload, Mapping) else None
            if timestamp is None and isinstance(payload, Mapping):
                timestamp = _first(payload, "timestamp_ns", "start_monotonic_ns", "end_monotonic_ns")
            sequence = payload.get("sequence") if isinstance(payload, Mapping) else None
            self.db.execute("INSERT INTO evidence(artifact_id,evidence_class,kind,sequence,timestamp_ns,payload,trust_state) VALUES(?,?,?,?,?,?,?)",
                            (artifact_id, evidence_class, kind, _int_or_none(sequence), _int_or_none(timestamp), _json(payload), trust_state))
        for relation in derived.get("process_relations", []):
            if not isinstance(relation, Mapping):
                continue
            timestamp = _first(relation, "send_timestamp_ns", "timestamp_ns", "receive_timestamp_ns")
            self.db.execute("INSERT INTO relation(artifact_id,relation_kind,from_participant,to_participant,timestamp_ns,payload,trust_state) VALUES(?,?,?,?,?,?,?)",
                            (artifact_id, str(relation.get("kind", "relation")), relation.get("from_pid"), relation.get("to_pid"),
                             _int_or_none(timestamp), _json(relation), trust_state))
        source_references = report.get("source_evidence", report.get("source_references", []))
        if isinstance(source_references, Mapping):
            source_references = [source_references]
        if isinstance(source_references, list):
            for reference in source_references:
                if not isinstance(reference, Mapping):
                    continue
                self.db.execute(
                    """INSERT INTO source_reference(incident_id,artifact_id,function_id,bundle_path,file,line_start,line_end,sha256,payload)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (incident_id if isinstance(incident_id, str) else None, artifact_id,
                     reference.get("function_id"), reference.get("bundle" , reference.get("bundle_path")),
                     reference.get("file"), _int_or_none(reference.get("line_start", reference.get("line"))),
                     _int_or_none(reference.get("line_end", reference.get("line"))), reference.get("sha256"), _json(reference)))
        declared = _provenance_values(report)
        provenance = report.get("provenance") if isinstance(report.get("provenance"), Mapping) else {}
        declared_artifact = _first(provenance, "artifact_sha256") if isinstance(provenance, Mapping) else None
        self.db.execute(
            """INSERT INTO provenance(artifact_id,build_id,binary_sha256,source_sha256,index_sha256,
               declared_artifact_sha256,trust_state,reason,payload) VALUES(?,?,?,?,?,?,?,?,?)""",
            (artifact_id, declared["build_id"], declared["binary_sha256"], declared["source_sha256"],
             declared["index_sha256"], declared_artifact, trust_state, trust_reason, _json(provenance)))
        return artifact_id

    def ingest(self, path: Path, *, expected: Mapping[str, Any] | None = None,
               expected_build_id: str | None = None, expected_session_id: str | None = None,
               expected_process_id: str | None = None, expected_process_generation: int | None = None,
               expected_sha256: str | None = None) -> dict[str, Any]:
        path = Path(path)
        digest: str | None = None
        raw: bytes | None = None
        try:
            digest, raw = _hash(path)
            if expected_sha256 is not None and digest.lower() != str(expected_sha256).lower():
                raise EvidenceValidationError("artifact sha256 does not match expected value")
            report = collect_file(path)
            if not isinstance(report, dict):
                raise EvidenceValidationError("artifact report must be an object")
            expected_values = _expected_values(expected, build_id=expected_build_id)
            validation = self._validate(report, expected_values, expected_session_id=expected_session_id,
                                        expected_process_id=expected_process_id,
                                        expected_process_generation=expected_process_generation)
            fdar_verified = path.suffix == ".fault"
            trust_state, trust_reason = self._trust(report, validation, fdar_verified)
            with self.db:
                artifact_id = self._insert_report(path, report, digest, len(raw), trust_state=trust_state,
                                                  trust_reason=trust_reason, manifest=validation["manifest"])
            return {"status": "ingested", "artifact_id": artifact_id, "path": str(path.resolve()),
                    "sha256": digest, "trust_state": trust_state, "trust_reason": trust_reason}
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._quarantine(path, "invalid_artifact", str(exc), raw, digest)

    def reindex(self, paths: Iterable[Path], **kwargs: Any) -> dict[str, Any]:
        expanded: list[Path] = []
        for candidate in paths:
            candidate = Path(candidate)
            if candidate.is_dir():
                expanded.extend(sorted(candidate.rglob("*.fault")))
                expanded.extend(sorted(candidate.rglob("*.json")))
            else:
                expanded.append(candidate)
        results = [self.ingest(path, **kwargs) for path in sorted(set(expanded), key=lambda item: str(item.resolve()))]
        return {"schema": SCHEMA_VERSION, "count": len(results),
                "ingested": sum(row.get("status") == "ingested" for row in results),
                "quarantined": sum(row.get("status") == "quarantined" for row in results),
                "results": results}

    def _where(self, *, session_id: str | None = None, start_ns: int | None = None,
               end_ns: int | None = None, trust_state: str | None = None) -> tuple[str, list[Any]]:
        clauses = ["a.status='valid'"]
        values: list[Any] = []
        if session_id is None:
            clauses.append("a.session_id IS NULL")
        else:
            clauses.append("a.session_id=?"); values.append(session_id)
        if start_ns is not None:
            clauses.append("a.process_start_ns>=?"); values.append(int(start_ns))
        if end_ns is not None:
            clauses.append("a.process_start_ns<=?"); values.append(int(end_ns))
        if trust_state is not None:
            if trust_state not in TRUST_STATES - {"quarantined"}:
                raise EvidenceStoreError("trust_state must be verified or unresolved for valid artifacts")
            clauses.append("a.trust_state=?"); values.append(trust_state)
        return " AND ".join(clauses), values

    def list_sessions(self, *, start_ns: int | None = None, end_ns: int | None = None,
                      trust_state: str | None = None, page: int = 0, limit: int = PAGE_SIZE) -> dict[str, Any]:
        page, limit = _bounded_page(page, limit)
        clauses = ["a.status='valid'"]
        values: list[Any] = []
        if start_ns is not None:
            clauses.append("a.process_start_ns>=?"); values.append(int(start_ns))
        if end_ns is not None:
            clauses.append("a.process_start_ns<=?"); values.append(int(end_ns))
        if trust_state is not None:
            if trust_state not in TRUST_STATES - {"quarantined"}:
                raise EvidenceStoreError("trust_state must be verified or unresolved")
            clauses.append("a.trust_state=?"); values.append(trust_state)
        where = " AND ".join(clauses)
        total = int(self.db.execute(f"SELECT COUNT(DISTINCT COALESCE(a.session_id, '')) FROM artifact a WHERE {where}", values).fetchone()[0])
        rows = self.db.execute(
            f"""SELECT COALESCE(a.session_id,'') AS session_key,
               MIN(a.session_id) AS session_id, MIN(a.process_start_ns) AS first_start_ns,
               COUNT(*) AS artifact_count,
               SUM(CASE WHEN a.trust_state='verified' THEN 1 ELSE 0 END) AS verified_count,
               MIN(a.identity_source) AS identity_source
               FROM artifact a WHERE {where}
               GROUP BY session_key
               ORDER BY (session_id IS NULL), session_id, first_start_ns, MIN(a.artifact_id)
               LIMIT ? OFFSET ?""", (*values, limit, page * limit)).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["session_id"] = item["session_id"] or None
            item["trust_state"] = "verified" if item["verified_count"] == item["artifact_count"] else "unresolved"
            item.pop("session_key", None)
            items.append(item)
        return {"schema": SCHEMA_VERSION, "sessions": items, "total": total, "page": page, "page_size": limit}

    def _artifact_rows(self, session_id: str | None, *, start_ns: int | None, end_ns: int | None,
                       trust_state: str | None) -> list[sqlite3.Row]:
        where, values = self._where(session_id=session_id, start_ns=start_ns, end_ns=end_ns, trust_state=trust_state)
        return self.db.execute(f"SELECT * FROM artifact a WHERE {where} ORDER BY a.process_start_ns IS NULL, a.process_start_ns, a.artifact_id", values).fetchall()

    def get_session(self, session_id: str | None, *, start_ns: int | None = None, end_ns: int | None = None,
                    trust_state: str | None = None, page: int = 0, limit: int = PAGE_SIZE) -> dict[str, Any]:
        page, limit = _bounded_page(page, limit)
        rows = self._artifact_rows(session_id, start_ns=start_ns, end_ns=end_ns, trust_state=trust_state)
        selected = rows[page * limit:(page + 1) * limit]
        ids = [int(row["artifact_id"]) for row in selected]
        base: dict[str, Any] = {"schema": SCHEMA_VERSION, "session": {"schema": 1, "session_id": session_id},
                                "artifacts": [], "participants": [],
                                "observed": {"rpc_events": [], "peer_snapshots": []},
                                "derived": {"process_relations": []}, "static_candidates": [],
                                "unresolved": [], "hypotheses": [], "provenance": [],
                                "page": page, "page_size": limit, "total_artifacts": len(rows)}
        if not ids:
            return base
        marks = ",".join("?" for _ in ids)
        base["artifacts"] = [dict(row) for row in selected]
        for row in selected:
            if row["identity_source"]:
                base["session"]["identity_source"] = row["identity_source"]
        process_rows = self.db.execute(f"SELECT * FROM process WHERE artifact_id IN ({marks}) ORDER BY artifact_id, process_row_id", ids).fetchall()
        base["participants"] = []
        for row in process_rows:
            item = dict(row)
            # Expose the contract name while retaining the internal row key.
            item["process_id"] = item.get("runtime_process_id")
            base["participants"].append(item)
        evidence_rows = self.db.execute(f"SELECT * FROM evidence WHERE artifact_id IN ({marks}) ORDER BY timestamp_ns IS NULL, timestamp_ns, evidence_id", ids).fetchall()
        for row in evidence_rows:
            payload = json.loads(row["payload"])
            if row["evidence_class"] == "observed":
                base["observed"]["peer_snapshots" if row["kind"] == "peer_snapshot" else "rpc_events"].append(payload)
            elif row["evidence_class"] == "static_candidates":
                base["static_candidates"].append(payload)
            elif row["evidence_class"] == "unresolved":
                base["unresolved"].append(payload)
            elif row["evidence_class"] == "hypotheses":
                base["hypotheses"].append(payload)
        relation_rows = self.db.execute(f"SELECT * FROM relation WHERE artifact_id IN ({marks}) ORDER BY timestamp_ns IS NULL, timestamp_ns, relation_id", ids).fetchall()
        base["derived"]["process_relations"] = [json.loads(row["payload"]) for row in relation_rows]
        prov_rows = self.db.execute(f"SELECT * FROM provenance WHERE artifact_id IN ({marks}) ORDER BY artifact_id, provenance_id", ids).fetchall()
        base["provenance"] = [dict(row) for row in prov_rows]
        return base

    def get_provenance(self, *, session_id: str | None = None, artifact_id: int | None = None,
                       trust_state: str | None = None, page: int = 0, limit: int = PAGE_SIZE) -> dict[str, Any]:
        page, limit = _bounded_page(page, limit)
        clauses = ["a.status='valid'"]
        values: list[Any] = []
        if session_id is None:
            pass
        else:
            clauses.append("a.session_id=?"); values.append(session_id)
        if artifact_id is not None:
            clauses.append("a.artifact_id=?"); values.append(int(artifact_id))
        if trust_state is not None:
            if trust_state not in TRUST_STATES:
                raise EvidenceStoreError("invalid trust_state")
            clauses.append("a.trust_state=?"); values.append(trust_state)
        where = " AND ".join(clauses)
        rows = self.db.execute(f"""SELECT p.*, a.path, a.sha256 AS artifact_sha256, a.session_id
                                   FROM provenance p JOIN artifact a ON a.artifact_id=p.artifact_id
                                   WHERE {where} ORDER BY p.artifact_id, p.provenance_id
                                   LIMIT ? OFFSET ?""", (*values, limit, page * limit)).fetchall()
        total = int(self.db.execute(f"SELECT COUNT(*) FROM provenance p JOIN artifact a ON a.artifact_id=p.artifact_id WHERE {where}", values).fetchone()[0])
        return {"schema": SCHEMA_VERSION, "provenance": [dict(row) for row in rows],
                "total": total, "page": page, "page_size": limit}

    def list_incidents(self, *, session_id: str | None = None, start_ns: int | None = None,
                       end_ns: int | None = None, trust_state: str | None = None,
                       page: int = 0, limit: int = PAGE_SIZE) -> dict[str, Any]:
        self._require_incident_tables()
        page, limit = _bounded_page(page, limit)
        clauses = ["i.incident_id IS NOT NULL", "a.status='valid'"]
        values: list[Any] = []
        if session_id is not None:
            clauses.append("i.session_id=?"); values.append(session_id)
        if start_ns is not None:
            clauses.append("i.first_seen_ns>=?"); values.append(int(start_ns))
        if end_ns is not None:
            clauses.append("i.first_seen_ns<=?"); values.append(int(end_ns))
        if trust_state is not None:
            if trust_state not in {"verified", "unresolved"}:
                raise EvidenceStoreError("trust_state must be verified or unresolved")
            clauses.append("i.trust_state=?"); values.append(trust_state)
        where = " AND ".join(clauses)
        total = int(self.db.execute(f"SELECT COUNT(DISTINCT i.incident_id) FROM incident i JOIN incident_artifact ia ON ia.incident_id=i.incident_id JOIN artifact a ON a.artifact_id=ia.artifact_id WHERE {where}", values).fetchone()[0])
        rows = self.db.execute(
            f"""SELECT i.incident_id,i.session_id,i.trigger_process_id,i.trigger_signal,i.status,
                      i.phase,i.partial,i.first_seen_ns,i.trust_state,COUNT(DISTINCT a.artifact_id) AS artifact_count
                 FROM incident i JOIN incident_artifact ia ON ia.incident_id=i.incident_id
                 JOIN artifact a ON a.artifact_id=ia.artifact_id WHERE {where}
                 GROUP BY i.incident_id ORDER BY i.first_seen_ns IS NULL,i.first_seen_ns,i.incident_id
                 LIMIT ? OFFSET ?""", (*values, limit, page * limit)).fetchall()
        return {"schema": SCHEMA_VERSION, "incidents": [dict(row) for row in rows],
                "total": total, "page": page, "page_size": limit}

    def _incident_artifacts(self, incident_id: str, *, trust_state: str | None = None) -> list[sqlite3.Row]:
        clauses = ["ia.incident_id=?", "a.status='valid'"]
        values: list[Any] = [incident_id]
        if trust_state is not None:
            if trust_state not in {"verified", "unresolved"}:
                raise EvidenceStoreError("trust_state must be verified or unresolved")
            clauses.append("a.trust_state=?"); values.append(trust_state)
        where = " AND ".join(clauses)
        return self.db.execute(f"""SELECT a.*,ia.evidence_class AS incident_evidence_class
                                    FROM incident_artifact ia JOIN artifact a ON a.artifact_id=ia.artifact_id
                                    WHERE {where} ORDER BY a.process_start_ns IS NULL,a.process_start_ns,a.artifact_id""", values).fetchall()

    def _require_incident_tables(self) -> None:
        required = {"incident", "incident_artifact", "source_reference"}
        rows = self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?,?)", tuple(required)).fetchall()
        if {row[0] for row in rows} != required:
            raise EvidenceStoreError("v0.9 incident tables are unavailable; reopen the store writable to migrate")

    def get_incident_slice(self, incident_id: str, *, trust_state: str | None = None,
                           page: int = 0, limit: int = PAGE_SIZE, max_events: int = 1000) -> dict[str, Any]:
        self._require_incident_tables()
        if not isinstance(incident_id, str) or not incident_id or len(incident_id) > 256:
            raise EvidenceStoreError("incident_id must be a bounded non-empty string")
        page, limit = _bounded_page(page, limit)
        incident_row = self.db.execute("SELECT * FROM incident WHERE incident_id=?", (incident_id,)).fetchone()
        if incident_row is None:
            raise EvidenceStoreError("incident not found")
        rows = self._incident_artifacts(incident_id, trust_state=trust_state)
        selected = rows[page * limit:(page + 1) * limit]
        ids = [int(row["artifact_id"]) for row in selected]
        result: dict[str, Any] = {"schema": SCHEMA_VERSION, "incident": dict(incident_row),
                                  "artifacts": [dict(row) for row in selected], "participants": [],
                                  "observed": {"rpc_events": [], "peer_snapshots": []},
                                  "derived": {"process_relations": []}, "static_candidates": [],
                                  "unresolved": [], "hypotheses": [], "source_references": [],
                                  "page": page, "page_size": limit, "total_artifacts": len(rows),
                                  "event_total": 0, "event_truncated": False}
        if not ids:
            return result
        marks = ",".join("?" for _ in ids)
        process_rows = self.db.execute(f"SELECT * FROM process WHERE artifact_id IN ({marks}) ORDER BY artifact_id,process_row_id", ids).fetchall()
        result["participants"] = []
        for row in process_rows:
            item = dict(row); item["process_id"] = item.get("runtime_process_id"); result["participants"].append(item)
        event_rows = self.db.execute(f"SELECT * FROM evidence WHERE artifact_id IN ({marks}) ORDER BY timestamp_ns IS NULL,timestamp_ns,evidence_id", ids).fetchall()
        observed_rows = [row for row in event_rows if row["evidence_class"] == "observed" and row["kind"] != "peer_snapshot"]
        peer_rows = [row for row in event_rows if row["evidence_class"] == "observed" and row["kind"] == "peer_snapshot"]
        non_observed_rows = [row for row in event_rows if row["evidence_class"] != "observed"]
        result["event_total"] = len(observed_rows)
        result["observed_event_total"] = len(observed_rows)
        if len(observed_rows) > max_events:
            observed_rows = observed_rows[:max_events]; result["event_truncated"] = True
            result["unresolved"].append({"scope": "incident", "reason": "event_limit_reached", "limit": max_events})
        for row in peer_rows + observed_rows + non_observed_rows:
            payload = json.loads(row["payload"])
            klass = row["evidence_class"]
            if klass == "observed":
                result["observed"]["peer_snapshots" if row["kind"] == "peer_snapshot" else "rpc_events"].append(payload)
            elif klass == "static_candidates": result["static_candidates"].append(payload)
            elif klass == "unresolved": result["unresolved"].append(payload)
            elif klass == "hypotheses": result["hypotheses"].append(payload)
        relation_rows = self.db.execute(f"SELECT * FROM relation WHERE artifact_id IN ({marks}) ORDER BY timestamp_ns IS NULL,timestamp_ns,relation_id", ids).fetchall()
        result["derived"]["process_relations"] = [json.loads(row["payload"]) for row in relation_rows[:max_events]]
        source_rows = self.db.execute(f"SELECT * FROM source_reference WHERE artifact_id IN ({marks}) ORDER BY source_reference_id LIMIT ?", (*ids, limit)).fetchall()
        result["source_references"] = [dict(row) for row in source_rows]
        return result

    def get_unresolved(self, incident_id: str, *, page: int = 0, limit: int = PAGE_SIZE) -> dict[str, Any]:
        result = self.get_incident_slice(incident_id, page=page, limit=limit)
        return {"schema": result["schema"], "incident": result["incident"],
                "unresolved": result["unresolved"], "page": result["page"],
                "page_size": result["page_size"], "total_artifacts": result["total_artifacts"]}

    def get_source_evidence(self, incident_id: str, bundle_path: Path, *,
                            function_ids: Iterable[str] | None = None, page: int = 0,
                            limit: int = PAGE_SIZE) -> dict[str, Any]:
        self._require_incident_tables()
        if not isinstance(incident_id, str) or not incident_id or len(incident_id) > 256:
            raise EvidenceStoreError("incident_id must be a bounded non-empty string")
        page, limit = _bounded_page(page, limit)
        try:
            bundle = load_bundle(bundle_path)
        except (OSError, ValueError, BundleError, json.JSONDecodeError) as exc:
            raise EvidenceStoreError(f"verified bundle unavailable: {exc}") from exc
        refs = self.db.execute("SELECT * FROM source_reference WHERE incident_id=? ORDER BY source_reference_id", (incident_id,)).fetchall()
        requested = [str(value) for value in (function_ids or [])]
        if len(requested) > 100:
            raise EvidenceStoreError("maximum 100 function_ids")
        for function_id in requested:
            if not any(row["function_id"] == function_id for row in refs):
                refs = list(refs) + [{"function_id": function_id, "bundle_path": None, "file": None,
                                      "line_start": None, "line_end": None, "sha256": None,
                                      "artifact_id": None, "source_reference_id": None}]
        citations: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        for reference in refs:
            function_id = reference["function_id"]
            try:
                if function_id:
                    source = verified_function_source(function_id, bundle)
                    source_file = Path(source["file"])
                    start_line, end_line = int(source["start_line"]), int(source["end_line"])
                else:
                    original = reference["file"]
                    source_file = bundle.source_path(original) if original else None
                    if source_file is None:
                        raise EvidenceStoreError("source file is not present in verified bundle")
                    start_line = int(reference["line_start"] or 1)
                    end_line = int(reference["line_end"] or start_line)
                relative = source_file.resolve().relative_to(bundle.root.resolve()).as_posix()
                entry = next((row for row in bundle.manifest.get("files", []) if row.get("path") == relative), None)
                if entry is None:
                    raise EvidenceStoreError("source citation is absent from bundle manifest")
                actual_hash = sha256_file(source_file)
                if reference["sha256"] and str(reference["sha256"]).lower() != actual_hash:
                    raise EvidenceStoreError("source citation hash mismatch")
                line_count = len(source_file.read_text(errors="replace").splitlines())
                if start_line < 1 or end_line < start_line or end_line > line_count:
                    raise EvidenceStoreError("source citation line range is outside the verified file")
                citations.append({"incident_id": incident_id, "artifact_id": reference["artifact_id"],
                                  "function_id": function_id, "bundle": str(bundle.root), "file": relative,
                                  "line_start": start_line, "line_end": end_line,
                                  "sha256": actual_hash, "manifest_sha256": entry.get("sha256"),
                                  "verified": True})
            except (OSError, ValueError, EvidenceStoreError) as exc:
                unresolved.append({"function_id": function_id, "reason": "source_citation_unresolved", "message": str(exc)})
        total = len(citations)
        start = page * limit
        page_citations = citations[start:start + limit]
        result: dict[str, Any] = {"schema": SCHEMA_VERSION, "incident_id": incident_id,
                                   "bundle": str(bundle.root), "citations": page_citations,
                                   "unresolved": unresolved, "total": total,
                                   "page": page, "page_size": limit,
                                   "resolved": bool(page_citations) and not unresolved}
        if len(page_citations) == 1:
            result.update({key: page_citations[0][key] for key in
                           ("file", "line_start", "line_end", "sha256", "function_id")})
        return result

    def quarantine_rows(self, *, page: int = 0, limit: int = PAGE_SIZE) -> dict[str, Any]:
        page, limit = _bounded_page(page, limit)
        total = int(self.db.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0])
        rows = self.db.execute("SELECT * FROM quarantine ORDER BY created_ns, quarantine_id LIMIT ? OFFSET ?", (limit, page * limit)).fetchall()
        return {"schema": SCHEMA_VERSION, "quarantine": [dict(row) for row in rows], "total": total, "page": page, "page_size": limit}
