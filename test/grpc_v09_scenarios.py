#!/usr/bin/env python3
"""Independent v0.9 gRPC capability scenarios.

The fixture remains application-owned: this gate drives the public command
line and validates process outcomes and numeric machine-readable summaries. It
does not inspect request payloads, metadata, or credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="backslashreplace")
    return value or ""


def _run(command: list[str], timeout: float = 30.0) -> dict[str, Any]:
    try:
        result = subprocess.run(command, text=True, encoding="utf-8",
                                errors="backslashreplace", capture_output=True,
                                timeout=timeout, check=False, cwd=ROOT)
        return {"command": command, "returncode": result.returncode,
                "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}
    except subprocess.TimeoutExpired as exc:
        return {"command": command, "returncode": None,
                "stdout": _text(exc.stdout)[-4000:],
                "stderr": (_text(exc.stderr)[-4000:] or "timeout")}


def _start(command: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(command, text=True, encoding="utf-8",
                            errors="backslashreplace", stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True,
                            cwd=ROOT)


def _stop(process: subprocess.Popen[str]) -> dict[str, Any]:
    try:
        # A bounded fixture shutdown may already be in progress after the
        # terminal CompletionQueue tag.  Give that path time to complete
        # before treating the process as an abnormal leftover.
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except OSError:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=2)
            return {"returncode": process.returncode, "stdout": stdout[-4000:],
                    "stderr": stderr[-4000:]}
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            process.kill()
        stdout, stderr = process.communicate()
    return {"returncode": process.returncode, "stdout": stdout[-4000:],
            "stderr": stderr[-4000:]}


def _wait_port(port: int, process: subprocess.Popen[str], timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _json_result(run: dict[str, Any]) -> dict[str, Any]:
    for line in reversed(str(run.get("stdout", "")).splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return {}


def _stream(binary: pathlib.Path, port: int) -> dict[str, Any]:
    upstream = _start([str(binary), "--mode=upstream", f"--listen=127.0.0.1:{port}",
                       "--max-calls=1", "--workers=2", "--stream-count=3"])
    try:
        ready = _wait_port(port, upstream)
        client = _run([str(binary), "--mode=client", f"--listen=127.0.0.1:{port}",
                       "--stream", "--stream-count=3", "--json-output",
                       "--rpc-id=901"], timeout=20)
        upstream_result = _stop(upstream)
        summary = _json_result(client)
        passed = (ready and client["returncode"] == 0 and
                  upstream_result["returncode"] == 0 and
                  summary.get("scenario") == "stream" and
                  summary.get("messages") == 3)
        return {"status": "PASS" if passed else "FAIL", "ready": ready,
                "client": client, "upstream": upstream_result,
                "summary": summary}
    finally:
        if upstream.poll() is None:
            _stop(upstream)


def _deadline(binary: pathlib.Path, upstream_port: int, proxy_port: int) -> dict[str, Any]:
    upstream = _start([str(binary), "--mode=upstream",
                       f"--listen=127.0.0.1:{upstream_port}", "--max-calls=1",
                       "--workers=2", "--response-delay-ms=150"])
    proxy = _start([str(binary), "--mode=proxy", f"--listen=127.0.0.1:{proxy_port}",
                    f"--upstream=127.0.0.1:{upstream_port}", "--max-calls=1",
                    "--workers=2", "--deadline-ms=10"])
    try:
        upstream_ready = _wait_port(upstream_port, upstream)
        proxy_ready = _wait_port(proxy_port, proxy)
        client = _run([str(binary), "--mode=client", f"--listen=127.0.0.1:{proxy_port}",
                       "--json-output", "--rpc-id=902"], timeout=20)
        proxy_result = _stop(proxy)
        upstream_result = _stop(upstream)
        summary = _json_result(client)
        passed = (upstream_ready and proxy_ready and client["returncode"] == 2 and
                  proxy_result["returncode"] == 0 and
                  upstream_result["returncode"] == 0 and
                  summary.get("status") == 4)
        return {"status": "PASS" if passed else "FAIL",
                "upstream_ready": upstream_ready, "proxy_ready": proxy_ready,
                "client": client, "proxy": proxy_result,
                "upstream": upstream_result, "summary": summary}
    finally:
        for process in (proxy, upstream):
            if process.poll() is None:
                _stop(process)


def _retry(binary: pathlib.Path, proxy_port: int, unavailable_port: int,
           output: pathlib.Path) -> dict[str, Any]:
    artifact_dir = output / "retry-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for stale in artifact_dir.glob("fault-*.fault"):
        try:
            stale.unlink()
        except OSError:
            pass
    proxy = _start([sys.executable, "-m", "faultdebug.cli", "run",
                    "--artifact-dir", str(artifact_dir),
                    "--session-id", "v09-retry", "--process-id", "proxy-retry",
                    "--", str(binary), "--mode=proxy",
                    f"--listen=127.0.0.1:{proxy_port}",
                    f"--upstream=127.0.0.1:{unavailable_port}", "--max-calls=1",
                    "--workers=2", "--retry=2", "--fault-after-response"])
    try:
        ready = _wait_port(proxy_port, proxy)
        client = _run([str(binary), "--mode=client", f"--listen=127.0.0.1:{proxy_port}",
                       "--json-output", "--rpc-id=903"], timeout=20)
        proxy_result = _stop(proxy)
        summary = _json_result(client)
        artifacts = sorted(artifact_dir.glob("fault-*.fault"))
        rpc_events: list[dict[str, Any]] = []
        if artifacts:
            try:
                from faultdebug.format import collect_file
                rpc_events = list((collect_file(artifacts[0]).get("rpc") or {}).get("events", []))
            except Exception:
                rpc_events = []
        outbound = [row for row in rpc_events if row.get("direction") == 2]
        inbound = [row for row in rpc_events if row.get("direction") == 1]
        attempts = sorted({int(row.get("attempt", 0)) for row in outbound})
        passed = (ready and client["returncode"] == 2 and
                  proxy_result["returncode"] == 139 and summary.get("status") == 14 and
                  len(artifacts) == 1 and attempts == [1, 2, 3] and
                  len([row for row in inbound if row.get("flags", 0) & 1]) == 1 and
                  len([row for row in inbound if row.get("flags", 0) & 2]) == 1)
        return {"status": "PASS" if passed else "FAIL", "ready": ready,
                "client": client, "proxy": proxy_result, "summary": summary,
                "artifacts": [str(path) for path in artifacts],
                "outbound_attempts": attempts,
                "inbound_event_count": len(inbound), "expected_attempts": 3}
    finally:
        if proxy.poll() is None:
            _stop(proxy)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    ns.output.mkdir(parents=True, exist_ok=True)
    if not ns.binary.is_file():
        report = {"schema": 1, "status": "NOT RUN",
                  "reason": "gRPC fixture binary is unavailable", "checks": []}
    else:
        base = 46000 + (os.getpid() % 500) * 4
        help_result = _run([str(ns.binary), "--help"], timeout=10)
        help_text = str(help_result.get("stdout", "")) + str(help_result.get("stderr", ""))
        checks = {
            "streaming_rpc": (_stream(ns.binary, base)
                               if all(token in help_text for token in ("--stream", "--stream-count", "--json-output"))
                               else {"status": "NOT RUN", "reason": "fixture does not advertise streaming/json scenario options"}),
            "deadline_cancellation": (_deadline(ns.binary, base + 1, base + 2)
                                       if all(token in help_text for token in ("--deadline-ms", "--json-output"))
                                       else {"status": "NOT RUN", "reason": "fixture does not advertise deadline/json scenario options"}),
            "retry_unavailable": (_retry(ns.binary, base + 3, base + 20, ns.output)
                                  if all(token in help_text for token in ("--retry", "--json-output"))
                                  else {"status": "NOT RUN", "reason": "fixture does not advertise retry/json scenario options"}),
        }
        statuses = [row["status"] for row in checks.values()]
        report = {"schema": 1,
                  "status": "FAIL" if "FAIL" in statuses else ("NOT RUN" if "NOT RUN" in statuses else "PASS"),
                  "checks": checks,
                  "contract": {"fields": ["rpc_id", "trace_id", "attempt",
                                             "direction", "phase", "status",
                                             "incomplete"],
                               "payload_recorded": False,
                               "metadata_recorded": False,
                               "credentials_recorded": False}}
    ns.output.joinpath("report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"],
                      "report": str(ns.output / "report.json")}, sort_keys=True))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
