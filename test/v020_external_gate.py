#!/usr/bin/env python3
"""v0.2.0 independent second-run gate for an external fmt clone.

Commands are supplied by the caller and run in a clean temporary copy. The
gate compares immutable source/build evidence and validates supplied MCP and
evaluator reports; it never learns expected values from analyzer output.
"""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, re, shlex, shutil, subprocess, tempfile

def tree_sha(root):
    h=hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file() and ".git" not in x.parts and "build" not in x.parts):
        h.update(p.relative_to(root).as_posix().encode()+b"\0"); h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()

def bid(binary):
    try:
        text=subprocess.check_output(["readelf","-n",str(binary)],text=True,stderr=subprocess.DEVNULL); m=re.search(r"Build ID:\s*([0-9a-fA-F]+)",text); return m.group(1).lower() if m else None
    except Exception:return None

def command(template, values):
    # Replace only the four documented tokens. Literal C/C++ braces and shell
    # syntax must survive unchanged.
    result=template
    for key,value in values.items(): result=result.replace("{"+key+"}",str(value))
    return result

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--source",type=pathlib.Path); ap.add_argument("--build-command"); ap.add_argument("--run-command"); ap.add_argument("--binary",type=pathlib.Path); ap.add_argument("--artifact",type=pathlib.Path); ap.add_argument("--mcp-result",type=pathlib.Path); ap.add_argument("--evaluator-command"); ap.add_argument("--output",type=pathlib.Path,required=True); ns=ap.parse_args(); ns.output.parent.mkdir(parents=True,exist_ok=True)
    required=[ns.source,ns.build_command,ns.run_command,ns.binary,ns.artifact,ns.evaluator_command]
    if any(x is None for x in required) or not ns.source.exists():
        out={"status":"NOT RUN","reason":"external fmt clone/build/run/evaluator inputs unavailable","checks":{}}; ns.output.write_text(json.dumps(out,indent=2)+"\n"); print(json.dumps(out,sort_keys=True)); return 0
    checks={}
    with tempfile.TemporaryDirectory(prefix="fd-v020-fmt-") as td:
        root=pathlib.Path(td)/"fmt"; shutil.copytree(ns.source,root); source_hash=tree_sha(root); checks["source_sha"]={"status":"PASS" if source_hash else "FAIL","sha256":source_hash}
        build=root/"build"; build.mkdir()
        def remap(value):
            p=pathlib.Path(value)
            if not p.is_absolute(): return root/p
            try: return root/p.relative_to(ns.source.resolve())
            except ValueError: raise ValueError(f"absolute path is outside clean clone: {p}")
        try:
            binary=remap(ns.binary); artifact=remap(ns.artifact); mcp_result=remap(ns.mcp_result) if ns.mcp_result else None
        except ValueError as exc:
            out={"status":"FAIL","checks":{"path_contract":{"status":"FAIL","reason":str(exc)}}}; ns.output.write_text(json.dumps(out,indent=2)+"\n"); print(json.dumps(out,sort_keys=True)); return 1
        env={**os.environ,"FD_V020_BUILD":str(build),"FD_V020_SOURCE":str(root),"FD_V020_BINARY":str(binary),"FD_V020_ARTIFACT":str(artifact)}
        values={"root":root,"build":build,"binary":binary,"artifact":artifact}
        b=subprocess.run(command(ns.build_command,values),cwd=root,env=env,shell=True,capture_output=True,text=True); checks["instrumented_build"]={"status":"PASS" if b.returncode==0 else "FAIL","returncode":b.returncode,"stderr":b.stderr[-2000:]}
        checks["build_id"]={"status":"PASS" if bid(binary) else "FAIL","build_id":bid(binary)}
        r=subprocess.run(command(ns.run_command,values),cwd=root,env=env,shell=True,capture_output=True,text=True); checks["run"]={"status":"PASS" if r.returncode==0 else "FAIL","returncode":r.returncode,"stderr":r.stderr[-2000:]}
        if artifact.is_file(): checks["artifact_checksum"]={"status":"PASS","sha256":hashlib.sha256(artifact.read_bytes()).hexdigest(),"bytes":artifact.stat().st_size}
        else: checks["artifact_checksum"]={"status":"FAIL","reason":"artifact missing"}
        if mcp_result and mcp_result.exists():
            try:
                m=json.loads(mcp_result.read_text()); checks["mcp_source_resolution"]={"status":"PASS" if m.get("resolved") is True and m.get("source") else "FAIL"}
            except (OSError,json.JSONDecodeError) as exc:
                checks["mcp_source_resolution"]={"status":"FAIL","reason":f"invalid MCP JSON: {exc}"}
        else: checks["mcp_source_resolution"]={"status":"NOT RUN","reason":"MCP result unavailable in clean copy"}
        e=subprocess.run(command(ns.evaluator_command,values),cwd=root,env=env,shell=True,capture_output=True,text=True); checks["evaluator"]={"status":"PASS" if e.returncode==0 else "FAIL","returncode":e.returncode,"stdout":e.stdout[-2000:],"stderr":e.stderr[-2000:]}
    statuses=[v["status"] for v in checks.values()]; overall="FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS"); out={"status":overall,"checks":checks}; ns.output.write_text(json.dumps(out,indent=2)+"\n"); print(json.dumps(out,sort_keys=True)); return 0 if overall in ("PASS","NOT RUN") else 1
if __name__=="__main__":raise SystemExit(main())
