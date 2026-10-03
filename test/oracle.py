#!/usr/bin/env python3
"""Independent structural oracle for captured JSON fault reports.

It intentionally does not call faultdebug.format or inspect helpers. The
report is treated as an untrusted decoded product output and checked using
independent invariants: committed event shape, per-generation sequence order,
enter/exit nesting, module containment, and crash metadata.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, struct, sys

ENTER, EXIT = 1, 2

def check(path: pathlib.Path) -> list[str]:
    errors=[]
    try:
        if path.suffix == ".fault":
            data=path.read_bytes()
            if len(data) < 52: raise ValueError("truncated artifact")
            magic, version, flags, length, pid, digest=struct.unpack_from("<4sHHQI32s", data)
            payload=data[52:]
            if magic != b"FDAR" or version != 1 or length != len(payload) or hashlib.sha256(payload).digest() != digest:
                raise ValueError("artifact checksum/header mismatch")
            report=json.loads(payload)
        else: report=json.loads(path.read_text())
    except Exception as exc: return [f"{path}: invalid artifact: {exc}"]
    header=report.get("header", {})
    if not (header.get("status",0) & (2 | 512)):
        errors.append("report is not a crash or partial publication")
    modules=report.get("modules", [])
    ranges=[(m.get("text_start",0),m.get("text_end",0)) for m in modules]
    for thread in report.get("threads", []):
        generation=thread.get("generation")
        events=thread.get("events", [])
        seq=[e.get("sequence") for e in events]
        if any(not isinstance(x,int) for x in seq): errors.append("non-integer event sequence")
        if any(b <= a for a,b in zip(seq,seq[1:])):
            errors.append(f"thread {thread.get('tid')} sequence is not strictly increasing")
        stack=[]
        for e in events:
            if e.get("generation") != generation: errors.append("event generation mismatch")
            if e.get("type") == ENTER: stack.append(e.get("function"))
            elif e.get("type") == EXIT:
                if not stack: errors.append("exit without matching enter")
                elif stack.pop() != e.get("function"): errors.append("non-nested enter/exit order")
            elif e.get("type") not in (3,4,5): errors.append("unknown event type")
            if e.get("type") in (ENTER,EXIT) and not any(lo <= e.get("function",0) < hi for lo,hi in ranges):
                errors.append("event function outside captured module ranges")
    crashes=report.get("crashes", [])
    if not crashes: errors.append("crash/partial report has no crash record")
    for c in crashes:
        if c.get("signal",0) <= 0: errors.append("invalid crash signal")
        if c.get("pc",0) == 0: errors.append("missing crash PC")
    return errors

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("root", type=pathlib.Path); ns=ap.parse_args()
    files=sorted(ns.root.glob("fault-*.fault")) + sorted(ns.root.glob("fault-*.json")); errors=[]
    if not files: errors.append("no fault artifacts found")
    for p in files: errors.extend(check(p))
    if errors:
        print(json.dumps({"status":"FAIL","files":len(files),"errors":errors}, indent=2)); return 1
    print(json.dumps({"status":"PASS","files":len(files),"checks":["event_order","generation","nesting","module_containment","crash_metadata"]})); return 0
if __name__ == "__main__": raise SystemExit(main())
