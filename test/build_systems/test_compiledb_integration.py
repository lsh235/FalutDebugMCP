#!/usr/bin/env python3
"""Optional black-box check for compiledb output and FaultDebug C++ wrapping.

Run with the project's Python environment and compiledb on PATH. The fixture
uses an isolated GNU Make project and does not modify this repository.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CPP_WRAPPER = ROOT / "scripts" / "faultdebug-cxx"


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _not_run(reason: str) -> int:
    print(json.dumps({"status": "NOT RUN", "reason": reason}, sort_keys=True))
    return 2


def main() -> int:
    compiledb = os.environ.get("COMPILEDB_BIN") or shutil.which("compiledb")
    cc = shutil.which(os.environ.get("FD_TEST_CC", "clang"))
    cxx = shutil.which(os.environ.get("FD_TEST_CXX", "clang++"))
    nm = shutil.which("nm")
    if not compiledb:
        return _not_run("compiledb is not installed or COMPILEDB_BIN is unset")
    if not cc or not cxx or not nm or not shutil.which("make"):
        return _not_run("make, clang, clang++, and nm are required")

    sys.path.insert(0, str(ROOT))
    try:
        from clang import cindex  # noqa: F401
    except ImportError:
        return _not_run("the active Python environment lacks FaultDebug/libclang")

    with tempfile.TemporaryDirectory(prefix="faultdebug-compiledb-") as raw:
        project = Path(raw) / "make-project"
        include = project / "include"
        source = project / "src"
        build = project / "build"
        for directory in (include, source, build, project / ".git"):
            directory.mkdir(parents=True, exist_ok=True)

        (include / "answer.h").write_text(
            "#ifndef ANSWER_H\n#define ANSWER_H\n"
            "int c_entry(void);\nint cpp_entry();\n#endif\n",
            encoding="utf-8",
        )
        (source / "c_main.c").write_text(
            '#include "answer.h"\nint c_entry(void) { return INDEX_ANSWER; }\n',
            encoding="utf-8",
        )
        (source / "cpp_main.cpp").write_text(
            '#include "answer.h"\nint cpp_entry() { return INDEX_ANSWER; }\n',
            encoding="utf-8",
        )
        (project / "Makefile").write_text(
            "CC ?= cc\nCXX ?= c++\n"
            "CPPFLAGS := -Iinclude -DINDEX_ANSWER=42\n"
            "CFLAGS := -O0 -g -std=c11\n"
            "CXXFLAGS := -O0 -g -std=c++17\n"
            "\n.PHONY: all\nall: build/c_main.o build/cpp_main.o\n"
            "build/c_main.o: src/c_main.c include/answer.h\n"
            "\t$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@\n"
            "build/cpp_main.o: src/cpp_main.cpp include/answer.h\n"
            "\t$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@\n",
            encoding="utf-8",
        )

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            path for path in (str(ROOT), env.get("PYTHONPATH", "")) if path
        )
        db_path = project / "compile_commands.json"
        _run([compiledb, "-f", "-n", "make", f"CC={cc}", f"CXX={cxx}"],
             cwd=project, env=env)
        if not db_path.is_file():
            raise RuntimeError("compiledb did not create compile_commands.json")

        entries = json.loads(db_path.read_text(encoding="utf-8"))
        files = {Path(row["file"]).name for row in entries}
        if files != {"c_main.c", "cpp_main.cpp"}:
            raise RuntimeError(f"unexpected compilation database source files: {sorted(files)}")

        index_path = build / "index.json"
        _run([sys.executable, "-m", "faultdebug.cli", "index",
              str(db_path), "-o", str(index_path)], cwd=project, env=env)
        indexed = json.loads(index_path.read_text(encoding="utf-8"))
        function_names = {row["name"] for row in indexed["functions"]}
        if not {"c_entry", "cpp_entry"}.issubset(function_names):
            raise RuntimeError(f"index missed fixture functions: {sorted(function_names)}")
        if indexed["coverage_failures"]:
            raise RuntimeError(f"libclang reported incomplete fixture parsing: {indexed['coverage_failures']}")

        wrapped_env = dict(env)
        wrapped_env.update({
            "FAULTDEBUG_REAL_CC": cc,
            "FAULTDEBUG_REAL_CXX": cxx,
            "FAULTDEBUG_INSTRUMENT_PROFILE": "full",
        })
        _run(["make", "build/cpp_main.o", f"CXX={CPP_WRAPPER}"],
             cwd=project, env=wrapped_env)
        symbols = _run([nm, "-u", str(build / "cpp_main.o")],
                       cwd=project, env=wrapped_env).stdout
        hooks = ("__cyg_profile_func_enter" in symbols
                 and "__cyg_profile_func_exit" in symbols)
        if not hooks:
            raise RuntimeError("FaultDebug C++ wrapper did not instrument the C++ object")

        print(json.dumps({
            "status": "PASS",
            "checks": {
                "compiledb emitted C and C++ commands": True,
                "FaultDebug index parsed both translation units": True,
                "FaultDebug C++ wrapper emitted instrumentation hooks": hooks,
            },
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
