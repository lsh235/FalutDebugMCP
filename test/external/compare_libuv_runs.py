#!/usr/bin/env python3
"""Compare two pinned libuv evaluations by declared semantic evidence."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"report root is not an object: {path}")
    return value


def _evidence_root(report: dict[str, Any]) -> Path:
    path = Path(report["evidence"]["mcp_result"]).resolve()
    if not path.is_file() or path.name != "mcp-result.json":
        raise ValueError("evaluation report does not identify a preserved MCP stdio result")
    return path.parent


def _archive_evidence(root: Path, archive: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"evidence archive refuses symlink: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = _sha256(path)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for name, digest in files.items():
                    path = root / name
                    info = tarfile.TarInfo(name)
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
    verified: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            rel = PurePosixPath(member.name)
            if rel.is_absolute() or ".." in rel.parts or not member.isfile():
                raise ValueError(f"unsafe or unexpected tar member: {member.name}")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError(f"archive member could not be read: {member.name}")
            verified[member.name] = hashlib.sha256(stream.read()).hexdigest()
    if verified != files:
        raise ValueError("evidence archive member/hash manifest did not round-trip")
    return {"path": str(archive.resolve()), "sha256": _sha256(archive),
            "member_count": len(files), "file_sha256": files,
            "manifest_verified": True}


def _bundle_inventory(evidence_root: Path) -> dict[str, str]:
    bundle = evidence_root / "bundle"
    if not bundle.is_dir():
        raise ValueError(f"verified source bundle is missing: {bundle}")
    return {path.relative_to(bundle).as_posix(): _sha256(path)
            for path in sorted(bundle.rglob("*"))
            if path.is_file() and path.name != "bundle.json"}


def _bundle_manifest_semantics(evidence_root: Path) -> dict[str, Any]:
    manifest = _json(evidence_root / "bundle" / "bundle.json")
    files = sorted((row.get("kind"), row.get("path"), row.get("sha256"), row.get("size"))
                   for row in manifest.get("files", []))
    binaries = sorted((row.get("path"), row.get("build_id"), row.get("sha256"), row.get("size"))
                      for row in manifest.get("binaries", []))
    return {"kind": manifest.get("kind"), "schema": manifest.get("schema"),
            "index": manifest.get("index"), "index_sha256": manifest.get("index_sha256"),
            "files": files, "binaries": binaries}


def compare_reports(first_path: Path, second_path: Path, archive_dir: Path) -> dict[str, Any]:
    first, second = _json(first_path), _json(second_path)
    roots = [_evidence_root(first), _evidence_root(second)]
    archives = [_archive_evidence(root, archive_dir / f"run-{i}-evidence.tar.gz")
                for i, root in enumerate(roots, 1)]
    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, passed: bool, detail: Any = None) -> None:
        checks[name] = {"status": "PASS" if passed else "FAIL", "detail": detail}

    check("input_evaluations_pass", first.get("status") == second.get("status") == "PASS",
          {"first": first.get("status"), "second": second.get("status")})
    fields = ("project", "tag", "commit", "repository", "faultdebug_commit",
              "faultdebug_worktree_clean", "faultdebug_source_tree_sha256",
              "runtime_library_sha256")
    identities = [{field: row.get("identity", {}).get(field) for field in fields}
                  for row in (first, second)]
    identity_equal = identities[0] == identities[1]
    check("pinned_source_identity_equal", identity_equal, identities)
    check("faultdebug_snapshot_clean", all(row["faultdebug_worktree_clean"] is True
                                            for row in identities),
          [row["faultdebug_worktree_clean"] for row in identities])

    required_gates = ("source_clean", "configure_original", "build_original",
                      "configure_instrumented", "build_instrumented", "library_archives",
                      "build_ids", "link_original_driver", "link_instrumented_driver",
                      "original_runtime", "fault_capture", "external_symbol_source",
                      "mcp_stdio_success_and_error")
    gate_results = []
    for report in (first, second):
        gate_results.append({name: (report.get("checks", {}).get(name) or {}).get("status")
                             for name in required_gates})
    gates_pass = all(all(row.get(name) == "PASS" for name in required_gates)
                     for row in gate_results)
    check("required_evaluation_gates_pass", gates_pass, gate_results)

    archives_by_run = [report["checks"]["library_archives"] for report in (first, second)]
    archive_hashes_match = (archives_by_run[0].get("original_sha256") == archives_by_run[1].get("original_sha256")
                            and archives_by_run[0].get("instrumented_sha256") == archives_by_run[1].get("instrumented_sha256"))
    check("libuv_archive_hashes_equal", archive_hashes_match, archives_by_run)
    build_ids = [report["checks"]["build_ids"] for report in (first, second)]
    check("driver_build_ids_equal",
          build_ids[0].get("original") == build_ids[1].get("original")
          and build_ids[0].get("instrumented") == build_ids[1].get("instrumented"), build_ids)
    runtime = [report["checks"]["original_runtime"] for report in (first, second)]
    crash = [report["checks"]["fault_capture"] for report in (first, second)]
    check("fatal_signal_semantics_equal",
          all(row.get("expected_signal") == 6 and row.get("returncode") == -6 for row in runtime)
          and all(row.get("expected_signal") == row.get("target_signal") == row.get("artifact_signal") == 6
                  for row in crash), {"original": runtime, "instrumented": crash})

    symbols = []
    for report in (first, second):
        rows = report.get("checks", {}).get("external_symbol_source", {}).get("resolved_uv_functions", [])
        symbols.append(sorted({(row.get("symbol"), row.get("file")) for row in rows
                               if row.get("symbol") and row.get("file")}))
    check("libuv_diagnostic_semantics_equal", bool(symbols[0]) and symbols[0] == symbols[1],
          [[{"symbol": name, "file": path} for name, path in rows] for rows in symbols])
    bundle_inventories = [_bundle_inventory(root) for root in roots]
    check("source_bundle_hashes_equal", bundle_inventories[0] == bundle_inventories[1],
          [{"files": len(rows), "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True,
              separators=(",", ":")).encode()).hexdigest()} for rows in bundle_inventories])
    bundle_semantics = [_bundle_manifest_semantics(root) for root in roots]
    check("source_bundle_manifest_equal", bundle_semantics[0] == bundle_semantics[1],
          [{"source_files": len(row["files"]), "binaries": row["binaries"],
            "index_sha256": row["index_sha256"]} for row in bundle_semantics])

    mcp_checks = [report.get("checks", {}).get("mcp_stdio_success_and_error", {}) for report in (first, second)]
    mcp_results = [json.loads((root / "mcp-result.json").read_text(encoding="utf-8")) for root in roots]
    mcp_semantics = [row.get("checks", {}) for row in mcp_results]
    check("mcp_stdio_success_and_error_equal",
          all(row.get("status") == "PASS" for row in mcp_checks)
          and mcp_semantics[0] == mcp_semantics[1], mcp_semantics)
    check("evidence_archives_hash_verified", all(row.get("manifest_verified") for row in archives),
          [{"sha256": row["sha256"], "member_count": row["member_count"]} for row in archives])

    # Deliberately variable values: PIDs, absolute run/evidence paths, report
    # timestamps, artifact SHA-256, event counts, RSS, and timing samples.
    variable_fields_excluded = ["process IDs and run-specific paths", "report timestamps",
                                "absolute source path in bundle binary metadata",
                                "runtime artifact bytes (ASLR/timestamps)", "event counts",
                                "RSS and timing samples"]
    status = "PASS" if all(row["status"] == "PASS" for row in checks.values()) else "FAIL"
    return {"schema": 1, "schema_name": "faultdebug.libuv_repeatability",
            "status": status, "inputs": [{"path": str(path.resolve()), "sha256": _sha256(path)}
                                           for path in (first_path, second_path)],
            "evidence_archives": archives, "checks": checks,
            "variable_fields_excluded_from_semantic_equality": variable_fields_excluded}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    ns = parser.parse_args()
    result = compare_reports(ns.first.resolve(), ns.second.resolve(), ns.archive_dir.resolve())
    ns.output.parent.mkdir(parents=True, exist_ok=True)
    ns.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "report": str(ns.output.resolve())}, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
