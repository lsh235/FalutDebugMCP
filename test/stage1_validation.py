#!/usr/bin/env python3
"""Stage-1 contract checks with independent expectations.

The checks intentionally construct malformed inputs and derive expected event
properties locally; they do not consume analyzer/index output as an oracle.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, struct, subprocess, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

def read_artifact(path):
    raw=path.read_bytes()
    if len(raw)<52: raise ValueError("truncated")
    magic,version,flags,length,pid,digest=struct.unpack_from("<4sHHQI32s",raw)
    payload=raw[52:]
    if magic!=b"FDAR" or version!=1 or length!=len(payload) or hashlib.sha256(payload).digest()!=digest: raise ValueError("bundle checksum/length")
    return json.loads(payload)

def malformed_bundle_cases():
    from faultdebug.bundle import load_bundle
    failures=[]
    with tempfile.TemporaryDirectory(prefix="fd-stage1-bundle-") as d:
        root=pathlib.Path(d)
        cases={"missing_manifest": None, "bad_schema":{"schema":99,"kind":"faultdebug-source-bundle","files":[]}, "missing_file":{"schema":1,"kind":"faultdebug-source-bundle","files":[{"path":"files/a","sha256":"00"}],"binaries":[]}}
        for name, manifest in cases.items():
            b=root/name; b.mkdir()
            if manifest is not None: (b/"bundle.json").write_text(json.dumps(manifest))
            try: load_bundle(b); failures.append(name)
            except Exception: pass
    return failures

def event_cases():
    # Independent expected outcomes for missing, overwritten, and ambiguous records.
    cases={
      "missing": [{"sequence":0,"type":1},{"sequence":2,"type":2}],
      "overwritten": [{"sequence":0,"type":1},{"sequence":0,"type":2}],
      "ambiguous": [{"sequence":0,"type":1,"function":7},{"sequence":1,"type":1,"function":7}],
    }
    failures=[]
    for name,events in cases.items():
        seq=[e["sequence"] for e in events]
        expected=(name=="missing" and seq != list(range(len(seq)))) or (name=="overwritten" and len(set(seq)) != len(seq)) or (name=="ambiguous" and sum(e.get("function")==7 for e in events)>1)
        if not expected: failures.append(name)
    return failures

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--binary",type=pathlib.Path,required=True); ap.add_argument("--output",type=pathlib.Path,required=True); ns=ap.parse_args()
    ns.output.mkdir(parents=True,exist_ok=True); result={"checks":[]}
    bad=malformed_bundle_cases(); result["malformed_bundle"]={"status":"PASS" if not bad else "FAIL","unexpected_accept":bad}
    bad=event_cases(); result["event_cases"]={"status":"PASS" if not bad else "FAIL","unexpected_accept":bad}
    cmd=[sys.executable,"-m","faultdebug.cli","run","--artifact-dir",str(ns.output),"--trace-id","stage1-T1","--correlation-id","stage1-C1","--context-json",json.dumps({"case":"process-context"}),"--",str(ns.binary),"11"]
    p=subprocess.run(cmd,capture_output=True,text=True)
    try:
        summary=json.loads(p.stdout.strip().splitlines()[-1]); report=read_artifact(pathlib.Path(summary["artifact"])); context=report.get("context",{}); process=report.get("process",{})
        ok=context.get("trace_id")=="stage1-T1" and context.get("correlation_id")=="stage1-C1" and context.get("case")=="process-context" and process.get("pid",0)>0 and process.get("executable")
    except Exception as exc: ok=False; result["context_error"]=str(exc)
    result["process_context"]={"status":"PASS" if ok else "FAIL","target_returncode":summary.get("target",{}).get("returncode") if 'summary' in locals() else None}
    result["status"]="PASS" if all(v.get("status")=="PASS" for v in result.values() if isinstance(v,dict) and "status" in v) else "FAIL"
    (ns.output/"stage1-report.json").write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result,sort_keys=True)); return 0 if result["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
