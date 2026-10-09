"""Cross-service reports from verified native captures and separate app evidence.

Application explanations are self-reported evidence, not native runtime facts.
Only an application event matching its capture identity and numeric RPC span
is shown as corroborated; injection configuration is never a report input.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .artifact import decode_artifact
from .bundle import load_bundle
from .fault_report import write_fault_report
from .rpc import process_relations, rpc_trace
from .service_report_view import render_html

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 100_000


def _bounded(path: Path) -> bytes:
    if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Evidence must be a regular bounded file: {path}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(f"Evidence byte budget exceeded: {path}")
    return data


def build_service_report(evidence: Path, *, bundle: Path | None = None) -> dict:
    evidence = evidence.resolve()
    artifacts = sorted(evidence.rglob("*.fault"))
    if not 1 <= len(artifacts) <= 64:
        raise ValueError("Expected 1..64 native captures")
    source_bundle = load_bundle(bundle) if bundle else None
    reports, services, evidence_files = [], [], []
    native_gaps = []
    identities = {}
    spans = {}
    native_rows = {}
    for index, path in enumerate(artifacts):
        data = _bounded(path)
        report = decode_artifact(data)
        if not isinstance(report, dict) or not isinstance(report.get("process"), dict):
            raise ValueError("Native service capture must contain a process object")
        process = report.get("process", {})
        identity = process.get("identity", {})
        if not isinstance(identity, dict):
            raise ValueError("Native service identity must be an object")
        key = (identity.get("session_id"), identity.get("process_id"), identity.get("process_generation"))
        if (not all(key) or not all(isinstance(value, str) for value in key[:2])
                or isinstance(key[2], bool) or not isinstance(key[2], int) or not 1 <= key[2] <= 0xFFFFFFFF
                or key in identities):
            raise ValueError("Service captures require unique explicit session/process/generation identities")
        role = identity.get("role", key[1])
        decoded = rpc_trace(report)
        identities[key] = index
        spans[key] = {(event.get("trace_id_lo"), event.get("rpc_id")) for event in decoded["observed"]}
        native_rows[key] = decoded["observed"]
        reports.append(report)
        services.append({"index": index, "role": role, "process_id": key[1], "generation": key[2],
                         "session_id": key[0], "pid": process.get("pid"), "artifact": path.relative_to(evidence).as_posix(),
                         "rpc_events": len(decoded["observed"]), "signal": report.get("target", {}).get("signal"),
                         "crashes": len(report.get("crashes", [])), "rpc_status": decoded["status"],
                         "native_complete": report.get("complete"),
                         "unresolved": decoded["unresolved"]})
        if report.get("complete") is False:
            native_gaps.append({"reason": "native_capture_incomplete", "service": role,
                                "snapshot_consistency": report.get("snapshot_consistency"),
                                "status": report.get("header", {}).get("status")})
        evidence_files.append({"path": path.relative_to(evidence).as_posix(), "sha256": hashlib.sha256(data).hexdigest(),
                               "kind": "checksummed_native_capture", "bytes": len(data)})
    if len({service["session_id"] for service in services}) != 1:
        raise ValueError("One service report must contain exactly one session")
    events, unresolved, causes = [], list(native_gaps), []
    for path in sorted(evidence.rglob("events.jsonl")):
        data = _bounded(path)
        if data and not data.endswith(b"\n"):
            unresolved.append({"reason": "application_log_truncated", "path": path.relative_to(evidence).as_posix()})
        evidence_files.append({"path": path.relative_to(evidence).as_posix(), "sha256": hashlib.sha256(data).hexdigest(),
                               "kind": "application_self_report", "bytes": len(data)})
        for line_number, line in enumerate(data.splitlines(), 1):
            if len(events) >= MAX_EVENTS:
                raise ValueError("Application event budget exceeded")
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                unresolved.append({"reason": "application_line_invalid", "line": line_number, "path": str(path.name)})
                continue
            if not isinstance(row, dict) or row.get("schema") != 1:
                raise ValueError("Unsupported application event schema")
            key = (row.get("session_id"), row.get("process_id"), row.get("process_generation"))
            if (key not in identities or row.get("service") != services[identities[key]]["role"]
                    or row.get("pid") != services[identities[key]]["pid"]):
                unresolved.append({"reason": "application_identity_unmatched", "line": line_number})
                continue
            for name in ("trace_id", "rpc_id", "parent_rpc_id", "monotonic_ns"):
                value = row.get(name, 0)
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
                    raise ValueError(f"Invalid application {name}")
            if any(isinstance(value, str) and len(value) > 2000 for value in row.values()):
                raise ValueError("Application string budget exceeded")
            row = {**row, "log_path": path.relative_to(evidence).as_posix(), "log_line": line_number,
                   "native_rpc_matched": (row.get("trace_id"), row.get("rpc_id")) in spans[key]}
            events.append(row)
            if row.get("kind") in {"failure", "fault_triggered"}:
                cause = {**row, "evidence_class": "application_self_report",
                         "assessment": "corroborated_rpc" if row["native_rpc_matched"] else "unresolved"}
                source = row.get("source_file", "")
                location = Path(source) if isinstance(source, str) else Path("/")
                source_path = (source_bundle.source_path(location) if source_bundle and not location.is_absolute()
                               and ".." not in location.parts and location.parts else None)
                line = row.get("source_line")
                if source_path and isinstance(line, int) and not isinstance(line, bool):
                    text = source_path.read_text().splitlines()
                    if 1 <= line <= len(text):
                        cause["source"] = {"file": source, "line": line, "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                                           "lines": [{"line": n, "text": text[n - 1]} for n in range(max(1, line - 3), min(len(text), line + 3) + 1)],
                                           "verification": "immutable_bundle_hash"}
                causes.append(cause)
    relations = process_relations(reports)
    unresolved.extend(relations["unresolved"])
    # Join app call labels only to already observed native endpoint pairs.
    calls = []
    for relation in relations["observed"]:
        if relation.get("kind") != "rpc":
            continue
        candidates = [event for event in events if event.get("kind") == "client_begin"
                      and event.get("process_id") == relation.get("from_process_id")
                      and event.get("trace_id") == relation.get("trace_id_lo")
                      and event.get("rpc_id") == relation["rpc_id"]]
        if len(candidates) != 1:
            unresolved.append({"reason": "application_call_label_unmatched", "rpc_id": relation["rpc_id"]})
            continue
        begin = candidates[0]
        ends = [event for event in events if event.get("kind") == "client_end"
                and event.get("process_id") == begin["process_id"] and event.get("trace_id") == begin["trace_id"]
                and event.get("rpc_id") == begin["rpc_id"]]
        call = {**relation, "from_service": begin["service"],
                "to_service": next(service["role"] for service in services if service["process_id"] == relation["to_process_id"]
                                   and service["generation"] == relation["to_process_generation"]),
                "path": begin.get("path"), "request_id": begin.get("request_id"),
                "parent_rpc_id": begin.get("parent_rpc_id"), "started_ns": begin["monotonic_ns"],
                "timeout_ms": begin.get("timeout_ms")}
        receiver = next(key for key in native_rows if key[1] == relation["to_process_id"]
                        and key[2] == relation["to_process_generation"])
        receiver_rows = [event for event in native_rows[receiver] if event.get("trace_id_lo") == begin["trace_id"]
                         and event.get("rpc_id") == begin["rpc_id"] and event.get("direction") == 1]
        receiver_ends = [event for event in receiver_rows if event.get("phase") == "end"]
        call["receiver_begin_observed"] = any(event.get("phase") == "begin" for event in receiver_rows)
        call["receiver_end_observed"] = len(receiver_ends) == 1
        if len(receiver_ends) == 1 and "status" in receiver_ends[0]:
            call["receiver_status"] = receiver_ends[0]["status"]
        call["symptoms"] = [{key: event[key] for key in ("code", "reason", "status", "log_path", "log_line") if key in event}
                            for event in events if event.get("kind") == "symptom" and event.get("rpc_id") == begin["rpc_id"]
                            and event.get("trace_id") == begin["trace_id"] and event.get("process_id") == begin["process_id"]]
        if len(ends) == 1:
            # Status must also be present in the native outbound endpoint.
            endpoint = (begin["session_id"], begin["process_id"], begin["process_generation"])
            native_ends = [event for event in native_rows[endpoint]
                           if (event.get("trace_id_lo") == begin["trace_id"] and event.get("rpc_id") == begin["rpc_id"]
                               and event.get("direction") == 2 and event.get("phase") == "end")]
            if len(native_ends) == 1 and native_ends[0].get("status") == ends[0].get("status"):
                call.update(status=ends[0]["status"], duration_ms=round((ends[0]["monotonic_ns"] - begin["monotonic_ns"]) / 1e6, 2))
            else:
                unresolved.append({"reason": "application_status_not_corroborated", "rpc_id": begin["rpc_id"]})
        calls.append(call)
    calls.sort(key=lambda call: call["started_ns"])
    for cause in causes:
        if cause["assessment"] != "unresolved" and cause.get("kind") == "failure":
            key = (cause["session_id"], cause["process_id"], cause["process_generation"])
            ends = [event for event in native_rows[key] if event.get("trace_id_lo") == cause.get("trace_id")
                    and event.get("rpc_id") == cause.get("rpc_id") and event.get("direction") == 1
                    and event.get("phase") == "end" and event.get("status") == cause.get("status")]
            cause["assessment"] = "corroborated_rpc_status" if len(ends) == 1 else "unresolved_native_status_absent"
        if cause["assessment"] != "unresolved" and cause.get("code") == "payment_native_trap":
            index = identities[(cause["session_id"], cause["process_id"], cause["process_generation"])]
            crashes = [crash for crash in reports[index].get("crashes", [])
                       if cause.get("tid") is not None and crash.get("tid") == cause["tid"]]
            if len(crashes) == 1:
                cause["assessment"] = "corroborated_rpc_and_native_crash"
                cause["native_crash"] = {key: crashes[0][key] for key in ("pc", "tid", "signal", "thread_generation") if key in crashes[0]}
            else:
                cause["assessment"] = "unresolved_matching_native_crash_absent"
    return {"schema": 1, "session_id": services[0]["session_id"], "services": services, "calls": calls,
            "native_relations": relations["observed"],
            "causes": causes, "events": events, "evidence_files": evidence_files, "unresolved": unresolved,
            "limitations": ["Application reasons are self-reported; hashes identify frozen evidence, not authenticity.",
                            "Native function traces cover the C++ boundary module, not Python call stacks.",
                            "Parent RPC IDs come from application propagation; shared trace IDs alone do not establish causality.",
                            "A receiver may finish after the caller times out; caller and receiver statuses are distinct."]}


def render_markdown(model: dict) -> str:
    lines = ["# 쇼핑몰 서비스 장애 보고서", "", f"Session: `{model['session_id']}`", "",
             f"애플리케이션 프로세스 {len(model['services'])}개 · 관측된 RPC 호출 {len(model['calls'])}개", "",
             "## 장애 발생 위치와 이유", ""]
    for cause in model["causes"]:
        lines.extend([f"- **{cause['service']} / {cause.get('code', 'unknown')}**: {cause.get('reason', 'Reason unavailable')}",
                      f"  - 검증 상태: `{cause['assessment']}`; RPC `{cause.get('rpc_id')}`; 요청 `{cause.get('request_id')}`."])
        if cause.get("source"):
            lines.append(f"  - 소스 근거: `{cause['source']['file']}:{cause['source']['line']}` (immutable bundle SHA-256).")
    if not model["causes"]:
        lines.append("관측된 장애 원인 이벤트 없음. 성공 여부는 주문 결과를 별도로 확인해야 합니다.")
    lines.extend(["", "## 실제 서비스 호출", "", "| 요청 | 경로 | HTTP | 시간 ms | RPC |", "|---|---|---:|---:|---|"])
    for call in model["calls"]:
        def safe(value):
            return str(value).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {safe(call.get('request_id'))} | {safe(call['from_service'])} → {safe(call['to_service'])} {safe(call.get('path'))} | {call.get('status', 'unknown')} | {call.get('duration_ms', 'unknown')} | {call['rpc_id']} |")
    lines.extend(["", "## 증거의 한계", ""] + [f"- {line}" for line in model["limitations"]])
    lines.extend(["", f"미해결 증거 항목: {len(model['unresolved'])}. 전체 항목은 report.json과 HTML에서 확인합니다.", "",
                  "## 증거 파일", ""])
    lines.extend(f"- `{row['path']}` — {row['kind']}, SHA-256 `{row['sha256']}`" for row in model["evidence_files"])
    return "\n".join(lines) + "\n"


def write_service_report(evidence: Path, output: Path, *, bundle: Path | None = None) -> dict:
    evidence, output = Path(evidence), Path(output)
    if output.exists():
        raise ValueError("Report output already exists")
    model = build_service_report(evidence, bundle=bundle)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".service-report-", dir=output.parent))
    try:
        for service in model["services"]:
            if service["crashes"]:
                result = write_fault_report(evidence / service["artifact"], temporary / f"fault-{service['index']}", bundle=bundle, language="ko")
                service["fault_report"] = f"fault-{service['index']}/report.html"
                service["fault_report_result"] = {key: value for key, value in result.items() if key != "output"}
        (temporary / "report.json").write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n")
        (temporary / "report.md").write_text(render_markdown(model))
        (temporary / "report.html").write_text(render_html(model))
        for path in temporary.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        os.rename(temporary, output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {"output": str(output), "processes": len(model["services"]), "observed_calls": len(model["calls"]),
            "causes": len(model["causes"]), "unresolved": len(model["unresolved"])}
