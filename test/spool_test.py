#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from faultdebug.artifact import read_artifact, write_artifact  # noqa: E402
import faultdebug.spool as spool_module  # noqa: E402
from faultdebug.spool import ArtifactSpool, SpoolError  # noqa: E402


def report(trace: str, correlation: str) -> dict:
    return {"header": {"status": 0}, "context": {"trace_id": trace, "correlation_id": correlation},
            "payload": {"trace_id": trace}, "threads": [], "modules": [], "crashes": []}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="faultdebug-spool-") as raw:
        root = pathlib.Path(raw)
        source = root / "source"
        spool_root = root / "spool"
        source.mkdir()
        paths = [write_artifact(report(f"trace-{i}", f"corr-{i}"), source, 100 + i) for i in range(3)]
        stale = spool_root / ".faultdebug-crashed.tmp"
        spool_root.mkdir()
        stale.write_bytes(b"partial")
        store = ArtifactSpool(spool_root, max_bytes=10_000, max_files=2,
                              redact_context_ids=("trace-1",))
        assert not stale.exists()
        store.ingest(paths[0]); store.ingest(paths[1]); store.ingest(paths[2])
        assert store.stats()["files"] == 2
        retained = store.list_files()
        assert all(path.suffix == ".fault" for path in retained)
        redacted = [read_artifact(path) for path in retained if path.name.startswith(paths[1].name.split(".")[0])]
        assert redacted and redacted[0]["context"]["trace_id"] == "[REDACTED]"
        assert redacted[0]["context"]["correlation_id"] == "corr-1"
        assert redacted[0]["payload"]["trace_id"] == "trace-1"
        oversized = write_artifact({"header": {}, "context": {"trace_id": "x"}, "large": "x" * 1000}, source, 999)
        try:
            ArtifactSpool(root / "tiny", max_bytes=100, max_files=2).ingest(oversized)
        except SpoolError:
            pass
        else:
            raise AssertionError("oversized artifact was admitted")
        original_replace = spool_module.os.replace
        spool_module.os.replace = lambda _source, _destination: (_ for _ in ()).throw(OSError("simulated crash"))
        try:
            try:
                store.ingest(paths[0])
            except OSError:
                pass
            else:
                raise AssertionError("simulated atomic-write failure was ignored")
            assert not list(spool_root.glob(".faultdebug-*.tmp"))
        finally:
            spool_module.os.replace = original_replace
    print("spool-test-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
