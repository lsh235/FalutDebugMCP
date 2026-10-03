#!/usr/bin/env python3
"""Focused v0.7 identity, registration, and durable artifact check."""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.artifact import read_artifact, recover_artifacts, write_artifact  # noqa: E402
from faultdebug.run import run_target  # noqa: E402
from faultdebug.session import (PARENT_PROCESS_ID_ENV, PROCESS_ID_ENV, SESSION_ID_ENV,
                                identity_from_env)  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=pathlib.Path, required=True)
    ns = parser.parse_args()
    inherited = identity_from_env(env={SESSION_ID_ENV: "s-parent", PROCESS_ID_ENV: "p-parent",
                                      PARENT_PROCESS_ID_ENV: "p-supervisor"})
    assert inherited.session_id == "s-parent"
    assert inherited.parent_process_id == "p-supervisor"
    assert inherited.process_id != "p-parent"
    with tempfile.TemporaryDirectory(prefix="faultdebug-session-") as raw:
        root = pathlib.Path(raw)
        artifact_dir = root / "artifacts"
        report = run_target(
            [str(ns.binary), "11"],
            artifact_dir=artifact_dir,
            context={"trace_id": "v07-trace"},
            identity={"session_id": "v07-session", "role": "backend"},
        )
        assert report["target"]["signal"] == 11
        assert report["session"] == {"schema": 1, "session_id": "v07-session"}
        process_identity = report["process"]["identity"]
        assert process_identity["session_id"] == "v07-session"
        assert process_identity["role"] == "backend"
        assert process_identity["pid"] == report["process"]["pid"]
        artifact = pathlib.Path(report["artifact"])
        assert read_artifact(artifact)["process"]["identity"] == process_identity
        assert not list((artifact_dir / ".collector").glob("*.json"))
        stale = artifact_dir / ".faultdebug-artifact-crashed.tmp"
        stale.write_bytes(b"partial")
        os.utime(stale, (0, 0))
        write_artifact({"header": {}, "process": {"pid": 99}}, artifact_dir, 99)
        assert not stale.exists()
        assert recover_artifacts(artifact_dir) == 0
    print("session-collector-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
