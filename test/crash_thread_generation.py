#!/usr/bin/env python3
"""Native fault records must identify the registered thread generation."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from faultdebug.artifact import read_artifact


def main():
    binary = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="faultdebug-crash-generation-") as name:
        result = subprocess.run([sys.executable, "-m", "faultdebug.cli", "run", "--artifact-dir", name,
                                 "--", str(binary), "16", "fault"], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 132, (result.returncode, result.stderr)
        capture = read_artifact(Path(json.loads(result.stdout)["artifact"]))
        crash = capture["crashes"][0]
        assert crash["thread_generation"] > 0, crash
        matching = [t for t in capture["threads"]
                    if (t["tid"], t["generation"]) == (crash["tid"], crash["thread_generation"])]
        assert len(matching) == 1 and matching[0]["events"], matching
        assert matching[0]["tid"] != (1 << 64) - 1
        print("native-crash-thread-generation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
