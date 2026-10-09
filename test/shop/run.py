#!/usr/bin/env python3
"""Build, exercise and collect isolated N-process Docker shopping sessions."""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
CORE = ["gateway", "catalog", "cart", "checkout", "inventory", "payment", "shipping", "notification"]
SCENARIOS = ["success", "inventory_shortage", "payment_decline", "inventory_timeout", "notification_failure", "payment_crash"]
EXPECTED = dict(zip(SCENARIOS, [200, 409, 402, 504, 200, 502]))


def command(argv: list[str], *, timeout=600) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(argv)}\n{result.stdout[-6000:]}")
    return result.stdout


def roles(count: int) -> list[str]:
    if not 8 <= count <= 32:
        raise ValueError("processes must be between 8 and 32")
    return CORE + [f"risk-{index + 1}" for index in range(count - 8)]


def compose(directory: Path, count: int, image: str, port: int, project: str) -> tuple[Path, list[str]]:
    names = roles(count)
    peers = json.dumps({name: f"{name}:8080" for name in names})
    services = {}
    for ordinal, name in enumerate(names, 1):
        evidence = directory / "evidence" / name
        evidence.mkdir(parents=True, exist_ok=True)
        identity = f"{project}-{name}"
        services[name] = {
            "image": image, "init": True, "restart": "no", "cpus": 0.5,
            "user": f"{os.getuid()}:{os.getgid()}",
            "mem_limit": "256m", "pids_limit": 128,
            "environment": {"SHOP_ROLE": name, "SHOP_ORDINAL": str(ordinal), "SHOP_PEERS": peers,
                            "FAULTDEBUG_SESSION_ID": project, "FAULTDEBUG_PROCESS_ID": identity},
            "command": ["fault-debug", "run", "--collect-success", "--artifact-dir", "/evidence",
                        "--session-id", project, "--process-id", identity, "--process-role", name,
                        "python", "-u", "/app/test/shop/service.py"],
            "volumes": [f"{evidence.resolve()}:/evidence"],
        }
        # Only the gateway is published; other ports remain in the project network.
        if name == "gateway":
            services[name]["ports"] = [f"127.0.0.1:{port}:8080"]
    manifest = directory / "compose.json"
    manifest.write_text(json.dumps({"name": project, "services": services}, indent=2) + "\n")
    return manifest, names


def http_request(port: int, path: str, body=None) -> tuple[int, dict]:
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        client.request("GET" if body is None else "POST", path,
                       None if body is None else json.dumps(body), {"Content-Type": "application/json"})
        response = client.getresponse()
        return response.status, json.loads(response.read())
    finally:
        client.close()


def inside(base: list[str], service: str, path: str, post=False) -> dict:
    code = ("import json,urllib.request; "
            f"r=urllib.request.urlopen(urllib.request.Request('http://{service}:8080{path}', "
            f"data={'b\"{}\"' if post else 'None'}, headers={{'Content-Type':'application/json'}}),timeout=5); "
            "print(r.read().decode())")
    # Gateway is still running during health, state checks, and peer shutdown.
    return json.loads(command(base + ["exec", "-T", "gateway", "python", "-c", code], timeout=20))


def wait_ready(base: list[str], names: list[str], port: int) -> list[dict]:
    until = time.monotonic() + 45
    last = ""
    while time.monotonic() < until:
        try:
            status, gateway = http_request(port, "/health")
            if status == 200:
                return [gateway] + [inside(base, name, "/health") for name in names if name != "gateway"]
        except (OSError, RuntimeError, ValueError) as exc:
            last = str(exc)
        time.sleep(0.3)
    raise RuntimeError(f"Shopping processes did not become ready: {last}")


def exercise(base: list[str], names: list[str], port: int, scenario: str, requests: int, concurrency: int) -> dict:
    responses = []
    def one(index: int):
        body = {"order_id": f"{scenario}-{index}", "quantity": 1, "scenario": scenario}
        return {"order_id": body["order_id"], "status": (result := http_request(port, "/checkout", body))[0], "body": result[1]}
    # Crash has one request; subsequent requests would observe an already-dead service.
    count = 1 if scenario == "payment_crash" else requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        responses = list(pool.map(one, range(count)))
    for response in responses:
        if response["status"] != EXPECTED[scenario]:
            raise AssertionError(f"{scenario}: unexpected response {response}")
        if scenario in {"success", "notification_failure"}:
            assert response["body"]["state"] == "completed", response
            assert response["body"]["notification"] == ("sent" if scenario == "success" else "deferred")
        else:
            assert response["body"].get("state") != "completed", response
    if scenario == "inventory_timeout":
        time.sleep(1)  # Let the delayed receiver record its deadline guard before state assertions.
    states = {name: inside(base, name, "/state") for name in ("inventory", "checkout")}
    if scenario != "payment_crash":
        states["payment"] = inside(base, "payment", "/state")
    if scenario in {"success", "notification_failure"}:
        assert len(states["checkout"]["orders"]) == count
        assert len(states["payment"]["charges"]) == count
        before = states["inventory"]["stock"]
        replay = http_request(port, "/checkout", {"order_id": f"{scenario}-0", "scenario": scenario})
        assert replay[0] == 200 and replay[1]["replayed"] is True, replay
        assert inside(base, "inventory", "/state")["stock"] == before
        assert len(inside(base, "payment", "/state")["charges"]) == count
    else:
        assert not states["checkout"]["orders"]
        assert not states["inventory"]["reservations"] and states["inventory"]["stock"] == 10000
        if scenario != "payment_crash":
            assert not states["payment"]["charges"]
    if scenario in {"payment_decline", "payment_crash"}:
        assert all(response["body"]["reservation_released"] for response in responses)
    return {"scenario": scenario, "assertions": "PASS", "requests": count,
            "concurrency": concurrency, "responses": responses, "states": states}


def shutdown(base: list[str], names: list[str], port: int):
    for name in names:
        if name != "gateway":
            try:
                inside(base, name, "/shutdown", post=True)
            except RuntimeError:
                pass  # The injected crash already stopped payment; collection is checked below.
    http_request(port, "/shutdown", {})


def execute(args):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError as exc:
            raise ValueError(f"Gateway port {args.port} is unavailable; choose another --port") from exc
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    output.mkdir(parents=True)
    if args.build:
        command(["docker", "build", "-f", "test/shop/Dockerfile", "-t", args.image, "."], timeout=900)
    image_id = command(["docker", "image", "inspect", "--format", "{{.Id}}", args.image]).strip()
    # Copy immutable build evidence once from an owned temporary container.
    container = command(["docker", "create", args.image, "true"]).strip()
    try:
        command(["docker", "cp", f"{container}:/opt/shop-bundle", str(output / "bundle")])
    finally:
        command(["docker", "rm", container])
    summary = {"schema": 1, "application_processes": args.processes, "image_id": image_id,
               "backend": "docker-compose", "scenarios": [], "kubernetes": "NOT RUN"}
    for scenario in args.scenarios:
        folder = output / scenario
        folder.mkdir()
        project = f"fdshop-{secrets.token_hex(5)}-{scenario.replace('_', '-')}"
        manifest, names = compose(folder, args.processes, args.image, args.port, project)
        base = ["docker", "compose", "-p", project, "-f", str(manifest)]
        try:
            command(base + ["up", "-d"], timeout=90)
            participants = wait_ready(base, names, args.port)
            result = exercise(base, names, args.port, scenario, args.requests, args.concurrency)
            result.update(session_id=project, participants=participants, image_id=image_id)
            shutdown(base, names, args.port)
            until = time.monotonic() + 20
            while time.monotonic() < until:
                if all(list((folder / "evidence" / name).glob("*.fault")) for name in names):
                    break
                time.sleep(0.2)
            else:
                raise AssertionError("A service did not produce its native capture")
            (folder / "run.json").write_text(json.dumps(result, indent=2) + "\n")
            from faultdebug.service_report import write_service_report
            report = write_service_report(folder / "evidence", folder / "report", bundle=output / "bundle")
            model = json.loads((folder / "report" / "report.json").read_text())
            assert report["processes"] == args.processes
            assert all(service["native_complete"] is True or service["crashes"] for service in model["services"]), model["services"]
            if scenario == "success":
                touched = {call["from_service"] for call in model["calls"]} | {call["to_service"] for call in model["calls"]}
                assert touched == set(names), ("a process was not used", touched, names)
            elif scenario == "payment_crash":
                assert any(cause["assessment"] == "corroborated_rpc_and_native_crash" for cause in model["causes"])
                crash_view = next((folder / "report").glob("fault-*/report.json"))
                crash_model = json.loads(crash_view.read_text())
                assert any(crash.get("source_verified") for crash in crash_model["crashes"])
                assert sum(len(thread["events"]) for thread in crash_model["threads"]) > 0
            else:
                assert any(cause["assessment"].startswith("corroborated") for cause in model["causes"])
            assert not any(row.get("reason") in {"application_identity_unmatched", "application_status_not_corroborated",
                                                  "rpc_decode_error", "rpc_sequence_gap", "rpc_sequence_not_monotonic"}
                           for row in model["unresolved"])
            result["report"] = report
            summary["scenarios"].append(result)
        finally:
            logs = subprocess.run(base + ["logs", "--no-color"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            (folder / "containers.log").write_text(logs.stdout)
            command(base + ["down", "--timeout", "5"], timeout=60)
            (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    links = "".join(f'<li><a href="{s}/report/report.html">{s}</a></li>' for s in args.scenarios)
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Shopping fault reports</title>'
                                     '<style>body{font:18px system-ui;background:#101a2a;color:#dce7f5;padding:50px}a{color:#8cbbff}li{margin:18px}</style>'
                                     f'<h1>N={args.processes} · 쇼핑몰 장애 보고서</h1><p>실제 Docker HTTP 요청과 native RPC 기록에서 생성했습니다.</p><ul>{links}</ul>')
    print(json.dumps({"output": str(output), "status": "PASS", "scenarios": len(summary["scenarios"]),
                      "processes_per_scenario": args.processes}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--requests", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=SCENARIOS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="faultdebug-shop:dev")
    parser.add_argument("--port", type=int, default=8860)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    roles(args.processes)
    if not 1 <= args.requests <= 100 or not 1 <= args.concurrency <= 8 or not 1024 <= args.port <= 65535:
        parser.error("requests 1..100, concurrency 1..8, port 1024..65535 required")
    if len(args.scenarios) != len(set(args.scenarios)):
        parser.error("scenarios must be unique")
    execute(args)


if __name__ == "__main__":
    main()
