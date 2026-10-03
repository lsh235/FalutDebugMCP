#!/usr/bin/env python3
"""Run isolated corruption cases through the independent report oracle."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import struct
import subprocess
import sys
import tempfile
from typing import Any, Callable

FDAR_HEADER = struct.Struct("<4sHHQI32s")


def _load_report(path: pathlib.Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if path.suffix == ".fault":
        if len(raw) < FDAR_HEADER.size:
            raise ValueError("FDAR header is truncated")
        magic, version, _flags, length, _pid, digest = FDAR_HEADER.unpack_from(raw)
        payload = raw[FDAR_HEADER.size:]
        if (magic != b"FDAR" or version != 1 or length != len(payload)
                or hashlib.sha256(payload).digest() != digest):
            raise ValueError("FDAR header or checksum is invalid")
    else:
        payload = raw
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("artifact payload is not an object")
    return value


def _oracle(oracle: pathlib.Path, artifact_dir: pathlib.Path) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(oracle), str(artifact_dir)],
                          capture_output=True, text=True, check=False)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = {"status": "FAIL", "error": "oracle emitted non-JSON output"}
    return {"returncode": proc.returncode, "report": report,
            "stderr": proc.stderr[-2000:]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=pathlib.Path)
    ns = parser.parse_args()
    files = sorted(ns.artifact.glob("fault-*.json")) + sorted(ns.artifact.glob("fault-*.fault"))
    if not files:
        print(json.dumps({"status": "NOT RUN", "reason": "no fault artifact available"}))
        return 2

    try:
        base = _load_report(files[0])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "reason": f"could not read base artifact: {exc}"}))
        return 1

    cases: dict[str, Callable[[dict[str, Any]], None] | None] = {
        "bad_signal": lambda value: value["crashes"][0].update(signal=0),
        "bad_pc": lambda value: value["crashes"][0].update(pc=0),
        "bad_generation": lambda value: value["threads"][0]["events"][0].update(generation=999999),
        "truncated": None,
    }
    oracle = pathlib.Path(__file__).with_name("oracle.py")
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="fd-negative-") as temp:
        root = pathlib.Path(temp)
        control_dir = root / "normal-control"
        control_dir.mkdir()
        (control_dir / "fault-control.json").write_text(json.dumps(base), encoding="utf-8")
        control = _oracle(oracle, control_dir)
        control_ok = control["returncode"] == 0 and control["report"].get("status") == "PASS"

        for name, mutate in cases.items():
            case_dir = root / name
            case_dir.mkdir()
            target = case_dir / f"fault-{name}.json"
            if mutate is None:
                encoded = json.dumps(base).encode("utf-8")
                target.write_bytes(encoded[:min(32, len(encoded))])
            else:
                value = json.loads(json.dumps(base))
                try:
                    mutate(value)
                except (IndexError, KeyError, TypeError) as exc:
                    results.append({"name": name, "status": "FAIL",
                                    "reason": f"base artifact lacks mutation target: {exc}"})
                    continue
                target.write_text(json.dumps(value), encoding="utf-8")
            oracle_result = _oracle(oracle, case_dir)
            rejected = (oracle_result["returncode"] != 0
                        and oracle_result["report"].get("status") == "FAIL")
            results.append({"name": name, "status": "PASS" if rejected else "FAIL",
                            "reason": "oracle rejected isolated malformed input" if rejected else
                            "oracle accepted or did not classify malformed input as FAIL",
                            "oracle": oracle_result})

    passed = control_ok and all(case["status"] == "PASS" for case in results)
    report = {"status": "PASS" if passed else "FAIL",
              "normal_control": {"status": "PASS" if control_ok else "FAIL",
                                 "oracle": control},
              "cases": results}
    print(json.dumps(report, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
