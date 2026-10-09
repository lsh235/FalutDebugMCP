#!/usr/bin/env python3
"""Namespace-safe RPC joins and evidence-bound multi-service reports."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from faultdebug.artifact import write_artifact
from faultdebug.rpc import process_relations, rpc_trace
from faultdebug.service_report import build_service_report, write_service_report
from faultdebug.service_report_view import render_html


def capture(role, direction, *, session="session", trace=20, generation=1, status=200):
    return {"header": {"status": 0, "abi_version": 1}, "target": {"returncode": 0},
            "process": {"pid": 8, "identity": {"session_id": session, "process_id": role,
                                               "process_generation": generation, "role": role}},
            "rpc_events": [{"rpc_id": 10, "trace_id_hi": 0, "trace_id_lo": trace, "direction": direction,
                            "method_id": 4, "phase": phase, "status": value, "monotonic_ns": n}
                           for n, phase, value in [(1, "begin", 0), (2, "end", status)]]}


def joins(*reports):
    return [row for row in process_relations(list(reports))["observed"] if row["kind"] == "rpc"]


class ServiceEvidenceTests(unittest.TestCase):
    def test_native_concurrent_time_order_is_not_sequence_loss(self):
        report = capture("checkout", 2)
        rows = report.pop("rpc_events")
        rows[0].update(sequence=0, monotonic_ns=200)
        rows[1].update(sequence=1, monotonic_ns=100)
        report["rpc"] = {"header": {"flags": 0}, "events": rows}
        self.assertEqual(rpc_trace(report)["status"], "complete")

    def test_native_end_timestamp_not_zero(self):
        report = capture("checkout", 2)
        for index, row in enumerate(report["rpc_events"]):
            row.pop("monotonic_ns")
            row.update(sequence=index, start_monotonic_ns=100 if index == 0 else 0,
                       end_monotonic_ns=200 if index == 1 else 0)
        decoded = rpc_trace(report)
        self.assertEqual(decoded["status"], "complete")
        self.assertEqual([row["monotonic_ns"] for row in decoded["observed"]], [100, 200])

    def test_equal_pids_and_inbound_begin(self):
        edge, = joins(capture("checkout", 2), capture("inventory", 1))
        self.assertEqual(edge["from_pid"], edge["to_pid"])
        self.assertEqual((edge["from_process_id"], edge["to_process_id"]), ("checkout", "inventory"))

    def test_trace_reuse_is_separate(self):
        self.assertEqual(len(joins(capture("checkout", 2), capture("inventory", 1),
                                  capture("checkout", 2, trace=21), capture("inventory", 1, trace=21))), 2)

    def test_trace_and_session_mismatch(self):
        self.assertEqual(joins(capture("checkout", 2), capture("inventory", 1, trace=21)), [])
        self.assertEqual(joins(capture("checkout", 2), capture("inventory", 1, session="other")), [])

    def test_generations_remain_ambiguous(self):
        self.assertEqual(joins(capture("checkout", 2), capture("inventory", 1),
                               capture("inventory", 1, generation=2)), [])
        receiver = capture("inventory", 1)
        for event in receiver["rpc_events"]:
            event["process_generation"] = 2
        self.assertEqual(joins(capture("checkout", 2), receiver), [])

    def test_method_mismatch_and_mixed_identity(self):
        receiver = capture("inventory", 1)
        for event in receiver["rpc_events"]:
            event["method_id"] = 5
        self.assertEqual(joins(capture("checkout", 2), receiver), [])
        receiver = capture("inventory", 1)
        receiver["process"].pop("identity")
        self.assertEqual(joins(capture("checkout", 2), receiver), [])

    def fixture(self, root, *, cause=True, wrong=False, status=409):
        for role, direction in [("checkout", 2), ("inventory", 1)]:
            folder = root / role
            folder.mkdir()
            write_artifact(capture(role, direction, status=status), folder, 8)
            common = {"schema": 1, "session_id": "session", "process_id": role, "process_generation": 1,
                      "service": role, "pid": 8, "trace_id": 20, "rpc_id": 10, "parent_rpc_id": 3, "request_id": "order"}
            rows = ([{**common, "kind": "client_begin", "monotonic_ns": 1, "peer": "inventory", "path": "/reserve"},
                     {**common, "kind": "client_end", "monotonic_ns": 2, "status": 409}] if role == "checkout" else [])
            if cause and role == "inventory":
                rows.append({**common, "process_id": "wrong" if wrong else role,
                             "kind": "failure", "code": "shortage", "reason": "No stock", "status": 409, "monotonic_ns": 1})
            (folder / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    def test_matched_reason_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            model = build_service_report(root)
            self.assertEqual(model["causes"][0]["assessment"], "corroborated_rpc_status")
            self.assertEqual(model["calls"][0]["status"], 409)

    def test_no_reason_inferred_or_identity_mismatch(self):
        for cause, wrong in [(False, False), (True, True)]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); self.fixture(root, cause=cause, wrong=wrong)
                self.assertEqual(build_service_report(root)["causes"], [])

    def test_status_disagreement_remains_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root, status=200)
            model = build_service_report(root)
            self.assertEqual(model["causes"][0]["assessment"], "unresolved_native_status_absent")
            self.assertNotIn("status", model["calls"][0])

    def test_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            artifact = next(root.rglob("*.fault")); data = artifact.read_bytes()
            artifact.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
            with self.assertRaises(ValueError): build_service_report(root)

    def test_incomplete_native_capture_remains_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            folder = root / "checkout"
            next(folder.glob("*.fault")).unlink()
            report = capture("checkout", 2, status=409)
            report["complete"] = False
            report["snapshot_consistency"] = {"stable": False, "unstable_records": [{"reason": "unpublished"}]}
            write_artifact(report, folder, 8)
            self.assertTrue(any(gap["reason"] == "native_capture_incomplete" for gap in build_service_report(root)["unresolved"]))

    def test_safe_html_and_non_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "evidence"; root.mkdir(); self.fixture(root)
            self.assertEqual(write_service_report(root, Path(tmp) / "report")["observed_calls"], 1)
            with self.assertRaises(ValueError): write_service_report(root, Path(tmp) / "report")
            model = build_service_report(root); model["session_id"] = '</script><script>alert(1)</script>'
            self.assertNotIn(model["session_id"], render_html(model))


if __name__ == "__main__":
    unittest.main()
