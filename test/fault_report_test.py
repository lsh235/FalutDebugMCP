#!/usr/bin/env python3
"""Fault-flow evidence oracles, document safety and CLI publication checks."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from faultdebug.artifact import write_artifact
from faultdebug.fault_report import build_fault_report, write_fault_report
from faultdebug.mcp_server import make_server
from faultdebug.report_view import render_html
from faultdebug.bundle import create_bundle


def capture():
    return {"complete": True, "header": {"status": 0},
            "snapshot_consistency": {"stable": True, "unstable_records": []},
            "modules": [], "threads": [{"tid": 7, "generation": 2, "slot": 0, "dropped_count": 0,
              "events": [{"sequence": i, "monotonic_ns": (i + 1) * 10, "type": kind,
                          "function": fn, "callsite": 0, "generation": 2}
                         for i, kind, fn in [(0, 1, 100), (1, 1, 200), (2, 2, 200)]]}],
            "crashes": [{"flags": 15, "tid": 7, "thread_generation": 2,
                         "pc": 207, "fault_address": 0, "signal": 11, "si_code": 1, "monotonic_ns": 40}]}


class FaultReportTests(unittest.TestCase):
    def test_retired_history_is_separate_from_ring_drops(self):
        raw = capture()
        raw["threads"][0]["flags"] = 3
        model = build_fault_report(raw)
        retirement = [g for g in model["gaps"] if g.get("reason") == "retired_thread_generations"]
        self.assertEqual(len(retirement), 1)
        self.assertEqual(retirement[0]["count"], 1)
        self.assertIsNone(retirement[0]["retired_event_count"])
        self.assertEqual(model["capture"]["evidence_status"], "limited")
        self.assertFalse(any(g.get("reason") == "dropped_records" for g in model["gaps"]))

    def test_observed_nesting_and_fault_context_are_distinct(self):
        model = build_fault_report(capture())
        self.assertIn({"from": "thread-0-event-0", "to": "thread-0-event-1", "kind": "observed_nesting"}, model["edges"])
        self.assertEqual(model["crashes"][0]["last_event"], "thread-0-event-2")
        self.assertEqual(model["crashes"][0]["fault_address"], 0)
        self.assertEqual(model["threads"][0]["unmatched_entries"][0]["function"], 100)
        self.assertFalse(any(e["kind"] == "root_cause" for e in model["edges"]))

    def test_gap_clears_stack_and_does_not_bridge(self):
        raw = capture()
        raw["threads"][0]["events"][1]["sequence"] = 5
        raw["threads"][0]["events"][2]["sequence"] = 6
        model = build_fault_report(raw)
        self.assertFalse(any(e["kind"] == "observed_nesting" for e in model["edges"]))
        self.assertEqual(model["capture"]["evidence_status"], "limited")
        self.assertIn("sequence_gap", model["threads"][0]["events"][1]["gaps_before"])

    def test_marker_and_mismatched_exit_clear_context(self):
        for kind in (3, 4, 5, 99, 2):
            raw = capture()
            raw["threads"][0]["events"][1]["type"] = kind
            raw["threads"][0]["events"][2]["type"] = 1
            model = build_fault_report(raw)
            self.assertFalse(any(e["kind"] == "observed_nesting" for e in model["edges"]))

    def test_thread_generation_and_identity_ambiguity(self):
        raw = capture()
        raw["crashes"][0]["thread_generation"] = 3
        model = build_fault_report(raw)
        self.assertIsNone(model["crashes"][0]["thread"])
        self.assertFalse(any(e["kind"] == "crash_context" for e in model["edges"]))
        raw = capture()
        raw["threads"].append(deepcopy(raw["threads"][0]))
        self.assertIsNone(build_fault_report(raw)["crashes"][0]["thread"])

    def test_event_generation_mismatch_cannot_nest(self):
        raw = capture()
        raw["threads"][0]["events"][1]["generation"] = 3
        model = build_fault_report(raw)
        self.assertFalse(any(e["kind"] == "observed_nesting" for e in model["edges"]))

    def test_crash_timestamp_and_pc_validity(self):
        raw = capture()
        raw["crashes"][0]["monotonic_ns"] = 15
        raw["crashes"][0]["flags"] = 3
        model = build_fault_report(raw)
        self.assertIsNone(model["crashes"][0]["pc"])
        self.assertIsNone(model["crashes"][0]["fault_address"])
        self.assertEqual(model["threads"][0]["post_crash_events"], 2)
        self.assertEqual(model["crashes"][0]["last_event"], "thread-0-event-0")
        raw["crashes"][0]["monotonic_ns"] = 0
        self.assertIsNone(build_fault_report(raw)["crashes"][0]["last_event"])

    def test_bounds_and_display_omission_are_not_capture_loss(self):
        raw = capture()
        raw["threads"][0]["events"] = []
        raw["crashes"] = []
        self.assertEqual(build_fault_report(raw)["capture"]["evidence_status"], "capture_complete")
        raw = capture()
        model = build_fault_report(raw, max_events=1)
        self.assertEqual(model["threads"][0]["omitted_from_view"], 2)
        self.assertEqual(len(model["threads"][0]["events"]), 1)
        self.assertFalse(any(e["kind"] == "observed_nesting" for e in model["edges"]))
        for limit in (0, 501):
            with self.assertRaises(ValueError):
                build_fault_report(raw, max_events=limit)

    def test_capture_loss_sources_are_explicit(self):
        for change, reason in [(lambda r: r["header"].update(status=1 << 4), "capture_status"),
                              (lambda r: r["threads"][0].update(dropped_count=5), "dropped_records"),
                              (lambda r: r.update(complete=False), "capture_completeness_unconfirmed"),
                              (lambda r: r["snapshot_consistency"].update(stable=False), "snapshot_unstable_or_unconfirmed"),
                              (lambda r: r.update(rpc={"complete": False}), "rpc_capture_incomplete")]:
            raw = capture(); change(raw)
            model = build_fault_report(raw)
            self.assertTrue(any(g.get("reason") == reason for g in model["gaps"]))

    def test_unverified_source_not_read_and_script_text_inert(self):
        evil = '</script><script>window.injected=true</script><img src=x onerror=alert(1)>'
        rows = [{"address": a, "resolved": True, "symbol": evil, "function_id": "unsafe", "source": {"file": "/etc/passwd"},
                 "static_edges": [{"callee_id": evil}]} for a in (100, 200, 207)]
        with patch("faultdebug.fault_report.resolve_addresses", return_value=rows):
            model = build_fault_report(capture())
        self.assertEqual(model["sources"], {})
        self.assertFalse(model["crashes"][0]["source_verified"])
        html = render_html(model)
        self.assertNotIn(evil, html)
        self.assertIn("connect-src 'none'", html)
        self.assertIn("\\u003c/script", html)

    def test_uint64_preserved_in_browser_payload(self):
        raw = capture()
        raw["threads"][0]["tid"] = (1 << 63) + 1
        model = build_fault_report(raw)
        html = render_html(model)
        self.assertIn('"tid": "9223372036854775809"', html)
        raw["threads"][0]["tid"] = '<script>alert(1)</script>'
        with self.assertRaises(ValueError):
            build_fault_report(raw)

    def test_cli_documents_and_checksum_rejection(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            artifact = write_artifact(capture(), root / "capture", pid=7)
            output = root / "report"
            run = subprocess.run([sys.executable, "-m", "faultdebug.cli", "fault-report", str(artifact),
                                  "--output", str(output), "--language", "ko"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual({p.name for p in output.iterdir()}, {"report.md", "report.json", "report.html"})
            self.assertIn("장애 실행 흐름", (output / "report.md").read_text())
            self.assertTrue(json.loads((output / "report.json").read_text())["artifact"]["checksum_verified"])
            with self.assertRaises(ValueError):
                write_fault_report(artifact, output)
            data = bytearray(artifact.read_bytes()); data[-1] ^= 1; artifact.write_bytes(data)
            with self.assertRaises(ValueError):
                write_fault_report(artifact, root / "bad")
            self.assertFalse((root / "bad").exists())

    def test_mcp_model_read_only_and_allowlist(self):
        async def check(root):
            server = make_server(root)
            registered = {t.name for t in await server.list_tools()}
            self.assertIn("get_fault_flow", registered)
            result = await server.call_tool("get_fault_flow", {"name": "fault-7.fault", "max_events": 1})
            # FastMCP returns text content for dict-valued tools.
            model = json.loads(result[0].text)
            self.assertEqual(model["kind"], "faultdebug-fault-flow")
            self.assertEqual(len(model["threads"][0]["events"]), 1)
            with self.assertRaises(Exception):
                await server.call_tool("get_fault_flow", {"name": "../outside.fault"})
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_artifact(capture(), root, pid=7)
            before = sorted(root.iterdir())
            asyncio.run(check(root))
            self.assertEqual(before, sorted(root.iterdir()))

    def test_bundle_validation_precedes_report_publication(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "source"; source.mkdir()
            (source / "example.c").write_text("void example(void) {}\n")
            bundle = create_bundle(source, root / "bundle")
            artifact = write_artifact(capture(), root / "capture", pid=7)
            captured = bundle.root / "source/example.c"
            captured.chmod(0o600); captured.write_text("tampered source\n")
            with self.assertRaises(ValueError):
                write_fault_report(artifact, root / "report", bundle=str(bundle.root))
            self.assertFalse((root / "report").exists())


if __name__ == "__main__":
    unittest.main()
