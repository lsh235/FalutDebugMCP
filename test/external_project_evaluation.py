#!/usr/bin/env python3
"""Independent evaluation harness for an external fmt-style project run.

The harness never derives expectations from the analyzer's own summaries. It
checks supplied build/artifact evidence against fixed structural requirements.
Absent external inputs are reported as NOT RUN rather than inferred PASS.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, re, struct, subprocess, sys

def build_id(binary: pathlib.Path) -> str | None:
    try:
        out=subprocess.check_output(["readelf","-n",str(binary)],text=True,stderr=subprocess.DEVNULL)
        m=re.search(r"Build ID:\s*([0-9a-fA-F]+)",out)
        return m.group(1).lower() if m else None
    except (OSError,subprocess.CalledProcessError): return None

def artifact(path: pathlib.Path):
    raw=path.read_bytes()
    if len(raw)<52:return None,"truncated artifact"
    magic,version,flags,length,pid,digest=struct.unpack_from("<4sHHQI32s",raw)
    payload=raw[52:]
    if magic!=b"FDAR" or version!=1:return None,"unsupported artifact header"
    if length!=len(payload) or hashlib.sha256(payload).digest()!=digest:return None,"artifact checksum/length mismatch"
    try:return json.loads(payload),None
    except json.JSONDecodeError:return None,"artifact payload is not JSON"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--original-build",type=pathlib.Path); ap.add_argument("--instrumented-build",type=pathlib.Path); ap.add_argument("--binary",type=pathlib.Path); ap.add_argument("--artifact",type=pathlib.Path); ap.add_argument("--source",type=pathlib.Path); ap.add_argument("--mcp-result",type=pathlib.Path); ap.add_argument("--output",type=pathlib.Path,required=True); ns=ap.parse_args()
    ns.output.parent.mkdir(parents=True, exist_ok=True); checks={}
    required=[ns.original_build,ns.instrumented_build,ns.binary,ns.artifact]
    if any(x is None for x in required) or any(not x.exists() for x in required if x):
        result={"status":"NOT RUN","reason":"external project build/artifact inputs are unavailable","checks":checks}; ns.output.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result,sort_keys=True)); return 0
    oid=build_id(ns.original_build); iid=build_id(ns.instrumented_build); bid=build_id(ns.binary)
    checks["build_ids"]={"status":"PASS" if oid and iid and bid else "FAIL","original":oid,"instrumented":iid,"binary":bid,"distinct_builds":oid!=iid}
    report,error=artifact(ns.artifact)
    checks["artifact"]={"status":"PASS" if report is not None else "FAIL","error":error}
    events=sum(len(t.get("events",[])) for t in (report or {}).get("threads",[])); checks["event_count"]={"status":"PASS" if events>0 else "FAIL","count":events}
    source_ok=bool(ns.source and ns.source.is_file())
    checks["resolved_source"]={"status":"PASS" if source_ok else "NOT RUN","path":str(ns.source) if ns.source else None}
    if ns.mcp_result and ns.mcp_result.is_file():
        try:
            m=json.loads(ns.mcp_result.read_text()); tools={"open_fault","get_thread_trace","resolve_addresses","get_function_source","get_call_relations"}; present=set(m) if isinstance(m,dict) else set(); checks["mcp_schema"]={"status":"PASS" if tools.issubset(present) else "FAIL","missing":sorted(tools-present)}
        except Exception as exc: checks["mcp_schema"]={"status":"FAIL","error":str(exc)}
    else: checks["mcp_schema"]={"status":"NOT RUN","reason":"MCP result file unavailable"}
    statuses=[v["status"] for v in checks.values()]; overall="FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    result={"status":overall,"checks":checks}; ns.output.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result,sort_keys=True)); return 0 if overall in ("PASS","NOT RUN") else 1
if __name__=="__main__": raise SystemExit(main())
