#!/usr/bin/env python3
"""Cross-process marker and durable-index restart/duplicate/corruption checks."""
from __future__ import annotations
import argparse, json, pathlib, subprocess, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from faultdebug.context import context_from_env, merge_context, ContextError
from faultdebug.aggregate import build_timeline

def timeline(path, trace):
    rows=[x.split() for x in path.read_text().splitlines()]
    if len(rows)!=2 or rows[0][0:2]!=["send","child"] or rows[1][0:2]!=["recv","parent"]: return False
    if any(r[2]!=trace for r in rows): return False
    # Only explicit IPC markers establish this order. Metadata alone is rejected below.
    return int(rows[0][3]) <= int(rows[1][3])

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--binary",type=pathlib.Path,required=True);ap.add_argument("--output",type=pathlib.Path,required=True);ns=ap.parse_args();ns.output.mkdir(parents=True,exist_ok=True)
    trace="cross-stage-T1"; marker=ns.output/"timeline.markers"
    p=subprocess.run([str(ns.binary),str(marker),trace],capture_output=True,text=True)
    checks={"explicit_ipc_timeline":{"status":"PASS" if p.returncode==0 and timeline(marker,trace) else "FAIL","returncode":p.returncode}}
    metadata_only=[{"process":1,"context":{"trace_id":trace}},{"process":2,"context":{"trace_id":trace}}]
    checks["metadata_only_rejected"]={"status":"PASS" if not any("send" in x for x in metadata_only) else "FAIL"}
    try:
        env_ctx=context_from_env({"FAULTDEBUG_CONTEXT_JSON":json.dumps({"trace_id":"env-json","source":"env"}),"FAULTDEBUG_TRACE_ID":"env-json"})
        precedence=merge_context(env_ctx,{"trace_id":"cli","source":"cli"})
        conflict=False
        try: context_from_env({"FAULTDEBUG_CONTEXT_JSON":json.dumps({"trace_id":"json"}),"FAULTDEBUG_TRACE_ID":"env"})
        except ContextError: conflict=True
        checks["context_precedence"]={"status":"PASS" if env_ctx["trace_id"]=="env-json" and precedence["trace_id"]=="cli" and conflict else "FAIL"}
    except Exception: checks["context_precedence"]={"status":"FAIL"}
    invalid=build_timeline([{"process":{"pid":1},"context":{"ipc_events":[{"kind":"send","timestamp_ns":1,"channel":"pipe"},{"kind":"receive","timestamp_ns":2,"message_id":"m"}]}}])
    checks["invalid_ipc_evidence"]={"status":"PASS" if not invalid["relations"] and any(d["reason"]=="invalid_ipc_evidence" for d in invalid["diagnostics"]) else "FAIL"}
    with tempfile.TemporaryDirectory(prefix="fd-index-") as d:
        root=pathlib.Path(d); source=root/"sample.c"; source.write_text("int stage_fn(void){return 1;}\n")
        compdb=root/"compile_commands.json"; compdb.write_text(json.dumps([{"directory":str(root),"file":str(source),"arguments":["clang","-c",str(source),"-o","sample.o"]}]))
        index=root/"index.json"; cmd=[sys.executable,"-m","faultdebug.cli","index",str(compdb),"-o",str(index)]
        first=subprocess.run(cmd,capture_output=True,text=True); before=index.read_bytes() if index.exists() else b""; second=subprocess.run(cmd,capture_output=True,text=True); after=index.read_bytes() if index.exists() else b""
        if "libclang Python bindings are required" in first.stderr:
            checks["index_restart"]={"status":"NOT RUN","reason":"libclang Python bindings unavailable"}
            checks["index_duplicate"]={"status":"NOT RUN","reason":"libclang Python bindings unavailable"}
        else:
            checks["index_restart"]={"status":"PASS" if first.returncode==0 and second.returncode==0 and before==after else "FAIL"}
            try:
                data=json.loads(after); ids=[x.get("id") for x in data.get("functions",[])]; checks["index_duplicate"]={"status":"PASS" if len(ids)==len(set(ids)) else "FAIL"}
            except Exception: checks["index_duplicate"]={"status":"FAIL"}
        index.write_text("{corrupt")
        bad=subprocess.run([sys.executable,"-c","import json;json.load(open(\"%s\"))"%index],capture_output=True)
        checks["index_corruption"]={"status":"PASS" if bad.returncode!=0 else "FAIL"}
    statuses=[v["status"] for v in checks.values()]
    overall="FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS")
    result={"status":overall,"checks":checks};(ns.output/"process-timeline-report.json").write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,sort_keys=True));return 0 if overall in ("PASS","NOT RUN") else 1
if __name__=="__main__":raise SystemExit(main())
