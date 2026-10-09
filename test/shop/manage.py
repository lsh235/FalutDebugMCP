#!/usr/bin/env python3
"""Leave a shopping laboratory running, then gracefully collect and stop it."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import time
from run import compose, command, wait_ready, shutdown, roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "stop"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--port", type=int, default=8860)
    parser.add_argument("--image", default="faultdebug-shop:dev")
    args = parser.parse_args()
    folder = args.output.resolve()
    if args.action == "up":
        roles(args.processes)
        if folder.exists():
            parser.error("output already exists; choose a new laboratory directory")
        folder.mkdir(parents=True)
        project = "fdshop-lab-" + secrets.token_hex(6)
        manifest, names = compose(folder, args.processes, args.image, args.port, project)
        base = ["docker", "compose", "-p", project, "-f", str(manifest)]
        container = command(["docker", "create", args.image, "true"]).strip()
        try:
            command(["docker", "cp", f"{container}:/opt/shop-bundle", str(folder / "bundle")])
        finally:
            command(["docker", "rm", container])
        state = {"project": project, "roles": names, "port": args.port, "manifest": str(manifest),
                 "image_id": command(["docker", "image", "inspect", "--format", "{{.Id}}", args.image]).strip()}
        (folder / "laboratory.json").write_text(json.dumps(state, indent=2) + "\n")
        try:
            command(base + ["up", "-d"], timeout=90)
            state["participants"] = wait_ready(base, names, args.port)
            (folder / "laboratory.json").write_text(json.dumps(state, indent=2) + "\n")
        except BaseException:
            command(base + ["down", "--timeout", "5"])
            raise
        print(json.dumps({"url": f"http://127.0.0.1:{args.port}", "processes": len(names),
                          "stop": f"python test/shop/manage.py stop --output {folder}"}, indent=2))
    else:
        state = json.loads((folder / "laboratory.json").read_text())
        if not state["project"].startswith("fdshop-lab-") or Path(state["manifest"]) != folder / "compose.json":
            parser.error("not an owned shopping laboratory")
        if state.get("stopped"):
            parser.error("laboratory already stopped")
        base = ["docker", "compose", "-p", state["project"], "-f", state["manifest"]]
        try:
            shutdown(base, state["roles"], state["port"])
            until = time.monotonic() + 20
            while time.monotonic() < until:
                if all(list((folder / "evidence" / role).glob("*.fault")) for role in state["roles"]):
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("native capture missing after shutdown")
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
            from faultdebug.service_report import write_service_report
            print(json.dumps(write_service_report(folder / "evidence", folder / "report", bundle=folder / "bundle"), indent=2))
        finally:
            logs = command(base + ["logs", "--no-color"])
            (folder / "containers.log").write_text(logs)
            command(base + ["down", "--timeout", "5"])
            state["stopped"] = True
            (folder / "laboratory.json").write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    main()
