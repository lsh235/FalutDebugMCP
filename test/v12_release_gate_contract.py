#!/usr/bin/env python3
"""Fast contracts for required release rows and stable provenance snapshots."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "test"))
import v12_release_gate as gate  # noqa: E402

sys.path.insert(0, str(ROOT))
from faultdebug.provenance import snapshot_source  # noqa: E402


def main() -> int:
    passing = {"checks": [{"name": name, "status": "PASS"} for name in gate.REQUIRED_V10]}
    assert gate.validate_v10_status(passing, "core") == (True, [], [])
    missing_row = {"checks": passing["checks"][:-1]}
    ok, missing, failed = gate.validate_v10_status(missing_row, "core")
    assert not ok and "package_metadata" in missing and not failed
    failed_row = {"checks": [*passing["checks"][:-1],
                              {"name": "package_metadata", "status": "NOT RUN"}]}
    ok, missing, failed = gate.validate_v10_status(failed_row, "grpc")
    assert not ok and not missing and failed == ["package_metadata"]

    with tempfile.TemporaryDirectory(prefix="faultdebug-provenance-snapshot-") as raw:
        root = Path(raw) / "source"
        for directory in ("faultdebug", "faultdebug.egg-info", "build", "build-v12",
                          "output", "test-results", ".venv"):
            (root / directory).mkdir(parents=True, exist_ok=True)
            (root / directory / "sentinel.txt").write_text(directory)
        (root / "test" / "build-helper").mkdir(parents=True, exist_ok=True)
        (root / "test" / "build-helper" / "source.py").write_text("source = True\n")
        (root / "faultdebug" / "real.py").write_text("value = 1\n")
        manifest_path = snapshot_source(root, root / "build-v12" / "snapshot")
        import json
        manifest = json.loads(manifest_path.read_text())
        included = {row["path"] for row in manifest["files"]}
        assert "faultdebug/real.py" in included
        assert "test/build-helper/source.py" in included
        assert not any(path.startswith(("faultdebug.egg-info/", "build/", "build-v12/",
                                        "output/", "test-results/", ".venv/"))
                       for path in included)
    print("PASS: required release rows and provenance source exclusions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
