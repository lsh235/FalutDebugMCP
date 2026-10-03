#!/usr/bin/env python3
"""Deterministically verify compiler-wrapper behavior without native toolchains."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "faultdebug-cc"


def _fake_compiler(path: Path, log: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['FD_WRAPPER_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps({'driver': os.path.basename(sys.argv[0]), 'argv': sys.argv[1:]}) + '\\n')\n"
    )
    path.chmod(0o755)


def _invoke(args: list[str], env: dict[str, str]) -> list[str]:
    run = subprocess.run([str(WRAPPER), *args], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=10)
    if run.returncode:
        raise AssertionError(f"wrapper failed ({run.returncode}): {run.stderr}")
    return run.stdout.splitlines()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="faultdebug-build-contract-") as raw:
        work = Path(raw)
        log = work / "compiler.jsonl"
        cc, cxx, linker = work / "fake-cc", work / "fake-cxx", work / "fake-linker"
        for compiler in (cc, cxx, linker):
            _fake_compiler(compiler, log)
        src = work / "project" / "src" / "app.c"
        excluded = work / "project" / "generated" / "schema.c"
        cpp = work / "project" / "src" / "main.cpp"
        for source in (src, excluded, cpp):
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("int main(void) { return 0; }\n")
        runtime = work / "runtime"
        runtime.mkdir()
        env = dict(os.environ)
        env.update({
            "FAULTDEBUG_REAL_CC": str(cc),
            "FAULTDEBUG_REAL_CXX": str(cxx),
            "FAULTDEBUG_LINK_DRIVER": str(linker),
            "FAULTDEBUG_RUNTIME_DIR": str(runtime),
            "FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX": r"/src/",
            "FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX": r"/generated/",
            "FD_WRAPPER_LOG": str(log),
        })
        _invoke(["-c", str(src), "-o", str(work / "app.o")], env)
        _invoke(["-c", str(excluded), "-o", str(work / "schema.o")], env)
        _invoke(["-c", str(cpp), "-o", str(work / "main.o")], env)
        _invoke([str(work / "app.o"), "-o", str(work / "app")], env)
        single_step_env = dict(env)
        single_step_env.pop("FAULTDEBUG_LINK_DRIVER", None)
        _invoke([str(src), "-o", str(work / "app-single-step")], single_step_env)
        _invoke([str(cpp), "-o", str(work / "main-single-step")], single_step_env)
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        instrument = "-finstrument-functions"
        disable = "-fno-instrument-functions"
        checks = {
            "C allowlisted source is instrumented": rows[0]["driver"] == "fake-cc" and instrument in rows[0]["argv"] and disable not in rows[0]["argv"],
            "excluded generated source receives no instrumentation flag": rows[1]["driver"] == "fake-cc" and instrument not in rows[1]["argv"] and disable not in rows[1]["argv"],
            "C++ source selects C++ compiler": rows[2]["driver"] == "fake-cxx" and instrument in rows[2]["argv"],
            "object-only link selects explicit driver and runtime": rows[3]["driver"] == "fake-linker" and "-lfaultdebug_runtime" in rows[3]["argv"] and any(a.startswith("-Wl,-rpath,") for a in rows[3]["argv"]),
            "one-step C compile+link keeps instrumentation and runtime": rows[4]["driver"] == "fake-cc" and instrument in rows[4]["argv"] and "-lfaultdebug_runtime" in rows[4]["argv"],
            "one-step C++ compile+link selects C++ and keeps instrumentation": rows[5]["driver"] == "fake-cxx" and instrument in rows[5]["argv"] and "-lfaultdebug_runtime" in rows[5]["argv"],
        }
        print(json.dumps({"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}, indent=2))
        return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
