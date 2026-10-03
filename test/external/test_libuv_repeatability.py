#!/usr/bin/env python3
"""Contract checks for semantic libuv repeatability and evidence archives."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from compare_libuv_runs import compare_reports  # noqa: E402


def make_report(root: Path, label: str) -> Path:
    evidence = root / label / "evidence"
    (evidence / "bundle" / "source" / "src").mkdir(parents=True)
    (evidence / "bundle" / "source" / "src" / "loop.c").write_text("void uv_loop_init(void) {}\n")
    (evidence / "bundle" / "bundle.json").write_text('{"verified":true}\n')
    mcp = {"status": "PASS", "checks": {
        "initialize": True, "required_tools_listed": True, "open_fault_success": True,
        "get_thread_trace_success": True, "resolve_addresses_success": True,
        "get_function_source_success": True, "get_call_relations_success": True,
        "path_escape_error": True}}
    (evidence / "mcp-result.json").write_text(json.dumps(mcp, sort_keys=True) + "\n")
    identity = {"project": "libuv", "tag": "v1.48.0", "commit": "e9f29cb984231524e3931aa0ae2c5dae1a32884e",
                "repository": "https://github.com/libuv/libuv.git", "faultdebug_commit": "snapshot-commit",
                "faultdebug_worktree_clean": True, "faultdebug_source_tree_sha256": "fd-source-sha",
                "runtime_library_sha256": "runtime-sha"}
    checks = {name: {"status": "PASS"} for name in (
        "source_clean", "configure_original", "build_original", "configure_instrumented",
        "build_instrumented", "link_original_driver", "link_instrumented_driver",
        "external_symbol_source", "mcp_stdio_success_and_error")}
    checks["library_archives"] = {"status": "PASS", "original_sha256": "orig-lib", "instrumented_sha256": "inst-lib"}
    checks["build_ids"] = {"status": "PASS", "original": "orig-id", "instrumented": "inst-id"}
    checks["original_runtime"] = {"status": "PASS", "expected_signal": 6, "returncode": -6}
    checks["fault_capture"] = {"status": "PASS", "expected_signal": 6, "target_signal": 6, "artifact_signal": 6}
    checks["external_symbol_source"] = {"status": "PASS", "resolved_uv_functions": [
        {"symbol": "uv_loop_init", "file": "src/unix/loop.c"}]}
    checks["mcp_stdio_success_and_error"] = {"status": "PASS"}
    report = {"status": "PASS", "identity": identity, "checks": checks,
              "evidence": {"mcp_result": str(evidence / "mcp-result.json")}}
    path = root / f"{label}.json"
    path.write_text(json.dumps(report, sort_keys=True) + "\n")
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="faultdebug-libuv-repeatability-") as tmp:
        root = Path(tmp)
        first = make_report(root, "first")
        second = make_report(root, "second")
        passed = compare_reports(first, second, root / "archives")
        assert passed["status"] == "PASS", passed["checks"]
        assert all(item["manifest_verified"] for item in passed["evidence_archives"])
        altered = json.loads(second.read_text())
        altered["checks"]["fault_capture"]["artifact_signal"] = 11
        second.write_text(json.dumps(altered) + "\n")
        failed = compare_reports(first, second, root / "archives-negative")
        assert failed["checks"]["fatal_signal_semantics_equal"]["status"] == "FAIL"
        assert failed["status"] == "FAIL"
    print("PASS: semantic fields compared and tar members/hash manifests verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
