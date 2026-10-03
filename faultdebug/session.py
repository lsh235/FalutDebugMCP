"""Read-only session and participant projections over local artifacts.

The session envelope is an optional v0.7 analysis contract. It never turns a
trace or correlation ID into a runtime causal relation; legacy IDs are kept as
an explicit compatibility identity source. RPC events remain observed,
process joins are derived, static candidates remain separate, and gaps remain
unresolved.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping

from .rpc import incident_report

SESSION_SCHEMA = 1
MAX_ID_LENGTH = 128
MAX_ROLE_LENGTH = 64
SESSION_ID_ENV = "FAULTDEBUG_SESSION_ID"
PROCESS_ID_ENV = "FAULTDEBUG_PROCESS_ID"
PROCESS_GENERATION_ENV = "FAULTDEBUG_PROCESS_GENERATION"
PARENT_PROCESS_ID_ENV = "FAULTDEBUG_PARENT_PROCESS_ID"
PROCESS_ROLE_ENV = "FAULTDEBUG_PROCESS_ROLE"


class SessionIdentityError(ValueError):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(16)}"


def _identity_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_ID_LENGTH:
        raise SessionIdentityError(f"{field} must be a non-empty string of at most {MAX_ID_LENGTH} characters")
    if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in value):
        raise SessionIdentityError(f"{field} must contain printable ASCII only")
    return value


def _optional_identity_id(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    return _identity_id(value, field)


def _identity_generation(value: object) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SessionIdentityError("process_generation must be a positive integer") from exc
    if result < 1 or result > 0xFFFFFFFF:
        raise SessionIdentityError("process_generation must be between 1 and 2^32-1")
    return result


@dataclass(frozen=True)
class ProcessIdentity:
    session_id: str
    process_id: str
    process_generation: int = 1
    parent_process_id: str | None = None
    role: str | None = None

    def __post_init__(self) -> None:
        _identity_id(self.session_id, "session_id")
        _identity_id(self.process_id, "process_id")
        _identity_generation(self.process_generation)
        _optional_identity_id(self.parent_process_id, "parent_process_id")
        if self.role is not None and (
            not isinstance(self.role, str)
            or not self.role
            or len(self.role) > MAX_ROLE_LENGTH
            or any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in self.role)
        ):
            raise SessionIdentityError(f"role must be printable ASCII of at most {MAX_ROLE_LENGTH} characters")

    def session_record(self) -> dict[str, object]:
        return {"schema": SESSION_SCHEMA, "session_id": self.session_id}

    def process_record(self, *, pid: int | None = None, parent_pid: int | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "schema": SESSION_SCHEMA,
            "session_id": self.session_id,
            "process_id": self.process_id,
            "process_generation": self.process_generation,
        }
        if self.parent_process_id is not None:
            result["parent_process_id"] = self.parent_process_id
        if self.role is not None:
            result["role"] = self.role
        if pid is not None:
            result["pid"] = int(pid)
        if parent_pid is not None:
            result["parent_pid"] = int(parent_pid)
        return result


def identity_from_env(identity: Mapping[str, object] | None = None,
                      env: Mapping[str, str] | None = None) -> ProcessIdentity:
    source = os.environ if env is None else env
    supplied = dict(identity or {})
    session_id = supplied.get("session_id") or source.get(SESSION_ID_ENV) or _new_id("session")
    process_id = supplied.get("process_id") or _new_id("process")
    parent_id = supplied.get("parent_process_id")
    if parent_id is None:
        parent_id = source.get(PARENT_PROCESS_ID_ENV) or source.get(PROCESS_ID_ENV)
    generation = supplied.get("process_generation")
    if generation is None:
        generation = source.get(PROCESS_GENERATION_ENV, "1")
    role = supplied.get("role")
    if role is None:
        role = source.get(PROCESS_ROLE_ENV) or None
    return ProcessIdentity(
        session_id=_identity_id(session_id, "session_id"),
        process_id=_identity_id(process_id, "process_id"),
        process_generation=_identity_generation(generation),
        parent_process_id=_optional_identity_id(parent_id, "parent_process_id"),
        role=role,
    )


def identity_to_env(identity: ProcessIdentity, env: MutableMapping[str, str] | None = None) -> MutableMapping[str, str]:
    target = os.environ if env is None else env
    target[SESSION_ID_ENV] = identity.session_id
    target[PROCESS_ID_ENV] = identity.process_id
    target[PROCESS_GENERATION_ENV] = str(identity.process_generation)
    if identity.parent_process_id is None:
        target.pop(PARENT_PROCESS_ID_ENV, None)
    else:
        target[PARENT_PROCESS_ID_ENV] = identity.parent_process_id
    if identity.role is None:
        target.pop(PROCESS_ROLE_ENV, None)
    else:
        target[PROCESS_ROLE_ENV] = identity.role
    return target

SESSION_MANIFEST_SCHEMA_VERSION = 1
_SESSION_KEYS = ("session", "session_manifest")
_MAX_ID_LENGTH = 256
_PARTICIPANT_CONTEXT_KEYS = ("service", "component", "instance")


class SessionDecodeError(ValueError):
    """A session declaration is malformed or cannot be safely combined."""


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_ID_LENGTH:
        raise SessionDecodeError(f"{field} must be a non-empty string of at most {_MAX_ID_LENGTH} characters")
    return value


def _declaration(report: dict[str, Any]) -> tuple[dict[str, Any], str | None, list[str], str | None]:
    present = [(key, report[key]) for key in _SESSION_KEYS if key in report]
    if len(present) > 1:
        raise SessionDecodeError("multiple session declarations are ambiguous")
    declaration: dict[str, Any] = {}
    if present:
        key, value = present[0]
        if not isinstance(value, dict):
            raise SessionDecodeError(f"{key} must be an object")
        declaration = value
        version = declaration.get("schema", declaration.get("version", 1))
        if version != SESSION_MANIFEST_SCHEMA_VERSION:
            raise SessionDecodeError(f"unsupported session manifest schema version: {version!r}")
    process = report.get("process") if isinstance(report.get("process"), dict) else {}
    process_identity = process.get("identity") if isinstance(process.get("identity"), dict) else {}
    process_schema = process.get("schema", process_identity.get("schema"))
    if process_schema is not None and process_schema != SESSION_SCHEMA:
        raise SessionDecodeError(f"unsupported process identity schema version: {process_schema!r}")
    session_id = declaration.get("session_id", report.get("session_id"))
    context = report.get("context") if isinstance(report.get("context"), dict) else {}
    context_session_id = context.get("session_id")
    process_session_id = process.get("session_id", process_identity.get("session_id"))
    if session_id is not None:
        session_id = _string(session_id, "session_id")
    if context_session_id is not None:
        context_session_id = _string(context_session_id, "context.session_id")
    if process_session_id is not None:
        process_session_id = _string(process_session_id, "process.session_id")
    if session_id and context_session_id and session_id != context_session_id:
        raise SessionDecodeError("session declaration conflicts with context.session_id")
    if session_id and process_session_id and session_id != process_session_id:
        raise SessionDecodeError("session declaration conflicts with process.session_id")
    if context_session_id and process_session_id and context_session_id != process_session_id:
        raise SessionDecodeError("context.session_id conflicts with process.session_id")
    session_id = session_id or context_session_id or process_session_id

    expected = declaration.get("expected_participants", [])
    if expected is None:
        expected = []
    if not isinstance(expected, list):
        raise SessionDecodeError("expected_participants must be an array")
    expected_ids = [_string(value, "expected_participants entry") for value in expected]
    if len(set(expected_ids)) != len(expected_ids):
        raise SessionDecodeError("expected_participants contains duplicates")
    participant_id = declaration.get("participant_id")
    context_participant_id = context.get("participant_id")
    if participant_id is not None:
        participant_id = _string(participant_id, "participant_id")
    if context_participant_id is not None:
        context_participant_id = _string(context_participant_id, "context.participant_id")
    if participant_id and context_participant_id and participant_id != context_participant_id:
        raise SessionDecodeError("session declaration conflicts with context.participant_id")
    runtime_participant_id = (process.get("role") or process.get("process_id") or
                              process_identity.get("role") or process_identity.get("process_id"))
    if runtime_participant_id is not None:
        runtime_participant_id = _string(runtime_participant_id, "process participant identity")
    if participant_id and runtime_participant_id and participant_id != runtime_participant_id:
        raise SessionDecodeError("session declaration conflicts with process participant identity")
    participant_id = participant_id or context_participant_id or runtime_participant_id
    return declaration, session_id, expected_ids, participant_id


def _identity(reports: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str], list[str | None]]:
    explicit: list[str] = []
    traces: list[str] = []
    correlations: list[str] = []
    expected: list[str] = []
    participant_ids: list[str | None] = []
    for report in reports:
        _declaration_data, session_id, expected_ids, participant_id = _declaration(report)
        if session_id is not None:
            explicit.append(session_id)
        expected.extend(expected_ids)
        participant_ids.append(participant_id)
        context = report.get("context") if isinstance(report.get("context"), dict) else {}
        if context.get("trace_id") is not None:
            traces.append(_string(context["trace_id"], "context.trace_id"))
        if context.get("correlation_id") is not None:
            correlations.append(_string(context["correlation_id"], "context.correlation_id"))
    for label, values in (("session_id", explicit), ("context.trace_id", traces), ("context.correlation_id", correlations)):
        if len(set(values)) > 1:
            raise SessionDecodeError(f"{label} mismatch across artifacts")
    expected_unique = list(dict.fromkeys(expected))
    if explicit:
        return ({"schema": SESSION_MANIFEST_SCHEMA_VERSION, "session_id": explicit[0], "identity_source": "session.session_id",
                 "compatibility": "explicit", **({"expected_participants": expected_unique} if expected_unique else {})},
                [], participant_ids)
    if traces:
        return ({"schema": SESSION_MANIFEST_SCHEMA_VERSION, "session_id": traces[0], "identity_source": "context.trace_id",
                 "compatibility": "legacy_context", **({"expected_participants": expected_unique} if expected_unique else {})},
                [], participant_ids)
    if correlations:
        return ({"schema": SESSION_MANIFEST_SCHEMA_VERSION, "session_id": correlations[0], "identity_source": "context.correlation_id",
                 "compatibility": "legacy_context", **({"expected_participants": expected_unique} if expected_unique else {})},
                [], participant_ids)
    session = {"schema": SESSION_MANIFEST_SCHEMA_VERSION, "session_id": None, "identity_source": "absent", "compatibility": "unresolved"}
    if expected_unique:
        session["expected_participants"] = expected_unique
    return session, [{"scope": "session", "reason": "session_identity_absent", "status": "evidence_missing"}], participant_ids


def _participant(report: dict[str, Any], index: int, declared_id: str | None,
                 artifact_ref: str | None) -> dict[str, Any]:
    process = report.get("process") if isinstance(report.get("process"), dict) else {}
    process_identity = process.get("identity") if isinstance(process.get("identity"), dict) else {}
    context = report.get("context") if isinstance(report.get("context"), dict) else {}
    participant_id = declared_id or f"artifact:{index}:pid:{process.get('pid', 'unknown')}"
    result: dict[str, Any] = {"participant_id": participant_id, "artifact_index": index}
    if artifact_ref is not None:
        result["artifact_ref"] = str(artifact_ref)
    for key in ("pid", "parent_pid", "executable", "start_monotonic_ns", "process_id",
                "process_generation", "parent_process_id", "role"):
        if key in process:
            result[key] = process[key]
        elif key in process_identity:
            result[key] = process_identity[key]
    target = report.get("target") if isinstance(report.get("target"), dict) else {}
    collector = report.get("collector") if isinstance(report.get("collector"), dict) else {}
    result["target"] = {key: target[key] for key in ("returncode", "signal") if key in target}
    result["collector"] = {key: collector[key] for key in ("ok", "status", "partial", "phase") if key in collector}
    safe_context = {}
    for key in ("session_id", "trace_id", "correlation_id", "participant_id", *_PARTICIPANT_CONTEXT_KEYS):
        if key in context and isinstance(context[key], str) and 0 < len(context[key]) <= _MAX_ID_LENGTH:
            safe_context[key] = context[key]
    if safe_context:
        result["context"] = safe_context
    return result


def _status(unresolved: list[dict[str, Any]], participants: list[dict[str, Any]], observed: dict[str, Any], derived: dict[str, Any]) -> str:
    if not unresolved:
        return "complete"
    if participants or observed.get("rpc_events") or derived.get("process_relations"):
        return "limited"
    return "unresolved"


def session_manifest(reports: list[dict[str, Any]], *, artifact_refs: Iterable[str] | None = None) -> dict[str, Any]:
    """Return a versioned session manifest with evidence classes preserved."""
    if not isinstance(reports, list):
        raise SessionDecodeError("reports must be an array")
    if len(reports) > 1000:
        raise SessionDecodeError("maximum 1000 artifacts")
    if not all(isinstance(report, dict) for report in reports):
        raise SessionDecodeError("reports must contain objects")
    refs = list(artifact_refs or [])
    if refs and len(refs) != len(reports):
        raise SessionDecodeError("artifact_refs must align with reports")
    session, identity_unresolved, participant_ids = _identity(reports)
    incident = incident_report(reports)
    observed = {"rpc_events": incident["observed"].get("rpc_events", [])}
    derived = {"process_relations": incident["observed"].get("process_relations", [])}
    unresolved = list(identity_unresolved) + list(incident.get("unresolved", []))
    participants = [_participant(report, index, participant_ids[index], refs[index] if refs else None)
                    for index, report in enumerate(reports)]
    expected = session.get("expected_participants", [])
    actual_ids = {row["participant_id"] for row in participants if not row["participant_id"].startswith("artifact:")}
    if expected and not actual_ids:
        unresolved.append({"scope": "session", "reason": "participant_identity_unavailable", "expected": expected})
    elif expected:
        missing = [value for value in expected if value not in actual_ids]
        if missing:
            unresolved.append({"scope": "session", "reason": "expected_participants_missing", "missing": missing})
    return {"schema": SESSION_MANIFEST_SCHEMA_VERSION,
            "status": _status(unresolved, participants, observed, derived),
            "session": session, "participants": participants,
            "observed": observed, "derived": derived,
            "static_candidates": incident.get("static_candidates", []),
            "unresolved": unresolved}


def process_participants(reports: list[dict[str, Any]], *, artifact_refs: Iterable[str] | None = None) -> dict[str, Any]:
    """Return only the participant projection and session-level diagnostics."""
    manifest = session_manifest(reports, artifact_refs=artifact_refs)
    return {"schema": manifest["schema"], "status": manifest["status"],
            "session": manifest["session"], "participants": manifest["participants"],
            "unresolved": manifest["unresolved"]}
