#!/usr/bin/env python3
"""Resident-agent SCM_RIGHTS and peer incident snapshot integration gate."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import threading
import time
import argparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.agent import AgentServer  # noqa: E402
from faultdebug.artifact import read_artifact  # noqa: E402
from faultdebug.run import run_target  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--peer-binary", type=pathlib.Path,
                        default=ROOT / "build-grpc-check/test/fd_soak")
    parser.add_argument("--trigger-binary", type=pathlib.Path,
                        default=ROOT / "build-grpc-check/test/fd_signals")
    ns = parser.parse_args()
    if not ns.peer_binary.is_file() or not ns.trigger_binary.is_file():
        parser.error("peer and trigger fixture binaries must exist")
    with tempfile.TemporaryDirectory(prefix="faultdebug-agent-") as raw:
        root = pathlib.Path(raw)
        spool = root / "spool"
        socket_path = spool / "agent.sock"
        server = AgentServer(socket_path, spool, max_bytes=8 * 1024 * 1024, max_files=32)
        stop = threading.Event()
        thread = threading.Thread(target=server.serve_forever, args=(stop,), daemon=True)
        thread.start()
        for _ in range(100):
            try:
                socket_mode = socket_path.stat().st_mode & 0o777
            except FileNotFoundError:
                socket_mode = None
            if socket_mode == 0o600:
                break
            time.sleep(0.01)
        assert socket_path.exists()
        assert socket_mode == 0o600
        assert (spool.stat().st_mode & 0o777) == 0o700

        peer_result: dict[str, object] = {}

        def run_peer() -> None:
            peer_result["report"] = run_target(
                [str(ns.peer_binary), "2"],
                artifact_dir=root / "peer",
                identity={"session_id": "agent-session", "role": "peer"},
                agent_socket=socket_path,
            )

        peer_thread = threading.Thread(target=run_peer)
        peer_thread.start()
        for _ in range(200):
            if server.registered_count >= 1:
                break
            time.sleep(0.01)
        assert server.registered_count >= 1
        trigger = run_target(
            [str(ns.trigger_binary), "11"],
            artifact_dir=root / "trigger",
            identity={"session_id": "agent-session", "role": "trigger"},
            agent_socket=socket_path,
        )
        peer_thread.join(5)
        assert trigger["collector"]["agent"]["status"] == "limited"
        assert trigger["collector"]["agent"]["phase"] == "incident_snapshot"
        assert trigger["collector"]["agent"]["peer_count"] >= 1
        incident_id = trigger["collector"]["agent"]["incident_id"]
        files = [pathlib.Path(path) for path in trigger["collector"]["agent"]["artifacts"]]
        assert len(files) >= 2
        assert all(path.name.startswith("fault-process-") and "-g1-" in path.name for path in files)
        reports = [read_artifact(path) for path in files]
        trigger_rows = [row for row in reports if row.get("evidence_class") == "observed"]
        peer_rows = [row for row in reports if row.get("evidence_class") == "incident_snapshot"]
        assert trigger_rows and peer_rows
        assert all(row["collector"]["incident_id"] == incident_id for row in reports)
        assert any(row["target"]["signal"] == 11 for row in trigger_rows)
        assert any(row["target"]["signal"] is None and row["collector"]["phase"] == "incident_snapshot" for row in peer_rows)
        assert all((path.stat().st_mode & 0o777) == 0o600 for path in files)

        server.stop()
        stop.set()
        thread.join(3)
        assert not socket_path.exists()
        stopped = __import__("json").loads((spool / "agent-status.json").read_text())
        assert stopped["state"] == "stopped"

        restarted = AgentServer(socket_path, spool, max_bytes=8 * 1024 * 1024, max_files=32)
        assert restarted._status_generation >= 2
        restarted.stop()
        restarted.close()
    print("agent-test-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
