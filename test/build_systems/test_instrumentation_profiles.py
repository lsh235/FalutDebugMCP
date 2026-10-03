#!/usr/bin/env python3
"""Exercise wrapper and CMake instrumentation profile decisions deterministically."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "faultdebug-cc"
HOOK_ON = "-finstrument-functions"
HOOK_OFF = "-fno-instrument-functions"


def make_fake_compiler(path: Path, log: Path) -> None:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['FD_PROFILE_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    path.chmod(0o755)


def wrapper_decision(work: Path, profile: str, source: str,
                     include: str = "", exclude: str = "") -> tuple[bool, str]:
    log = work / "wrapper.jsonl"
    log.unlink(missing_ok=True)
    cc = work / "fake-cc"
    make_fake_compiler(cc, log)
    source_path = work / source
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("int fixture(void) { return 0; }\n")
    env = dict(os.environ)
    env.update({
        "FAULTDEBUG_REAL_CC": str(cc),
        "FAULTDEBUG_INSTRUMENT_PROFILE": profile,
        "FAULTDEBUG_INSTRUMENT_INCLUDE_REGEX": include,
        "FAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX": exclude,
        "FD_PROFILE_LOG": str(log),
    })
    run = subprocess.run([str(WRAPPER), "-c", str(source_path), "-o", str(work / "out.o")],
                         cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
    if run.returncode:
        return False, run.stderr
    args = json.loads(log.read_text().splitlines()[-1])
    return HOOK_ON in args and HOOK_OFF not in args, run.stderr


def wrapper_checks(work: Path) -> dict[str, bool]:
    cases = {
        "legacy default keeps all-source behavior": ("legacy", "src/app.c", "", "", True),
        "minimal with no allowlist instruments nothing": ("minimal", "src/app.c", "", "", False),
        "minimal instruments an allowlisted source": ("minimal", "src/app.c", "src/", "", True),
        "explicit exclude wins in minimal": ("minimal", "src/app.c", "src/", "app\\.c$", False),
        "recommended instruments ordinary project source": ("recommended", "src/app.c", "", "", True),
        "recommended excludes generated source": ("recommended", "generated/schema.c", "", "", False),
        "recommended excludes vendor source": ("recommended", "vendor/lib.c", "", "", False),
        "recommended applies user include filter": ("recommended", "other/extra.c", "src/", "", False),
        "full ignores include and built-in path exclusions": ("full", "generated/schema.c", "src/", "", True),
        "full still honors explicit exclude": ("full", "vendor/lib.c", "src/", "vendor/", False),
    }
    results: dict[str, bool] = {}
    for name, (profile, source, include, exclude, expected) in cases.items():
        actual, diagnostic = wrapper_decision(work, profile, source, include, exclude)
        results[name] = actual == expected and f"profile={profile}" in diagnostic

    env = dict(os.environ)
    env.update({"FAULTDEBUG_REAL_CC": str(work / "fake-cc"),
                "FAULTDEBUG_INSTRUMENT_PROFILE": "mystery",
                "FD_PROFILE_LOG": str(work / "wrapper.jsonl")})
    invalid = subprocess.run([str(WRAPPER), "-c", str(work / "src/app.c")],
                             cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
    results["invalid profile is rejected before compiler invocation"] = (
        invalid.returncode == 2 and "invalid FAULTDEBUG_INSTRUMENT_PROFILE" in invalid.stderr)
    return results


def cmake_checks(work: Path) -> tuple[str, dict[str, bool]]:
    cmake = shutil.which("cmake")
    if not cmake:
        return "NOT RUN: CMake is unavailable", {}
    project = work / "cmake-profile-fixture"
    project.mkdir()
    sources = ["src/app.c", "generated/schema.c", "vendor/lib.c", "other/extra.c"]
    for source in sources:
        path = project / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("int fixture(void) { return 0; }\n")
    module = (ROOT / "cmake" / "FaultDebugSelective.cmake").as_posix()
    source_list = "\n  ".join(f'"{source}"' for source in sources)
    (project / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n"
        "project(profile_fixture C)\n"
        "set(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n"
        f'include("{module}")\n'
        f"add_executable(profile_fixture\n  {source_list})\n"
        "faultdebug_apply_source_filters(profile_fixture)\n"
    )

    def configure(name: str, profile: str, include: str = "", exclude: str = "") -> tuple[subprocess.CompletedProcess[str] | None, dict[str, bool]]:
        build = work / f"cmake-{name}"
        run = subprocess.run(
            [cmake, "-S", str(project), "-B", str(build),
             f"-DFAULTDEBUG_INSTRUMENT_PROFILE={profile}",
             f"-DFAULTDEBUG_INSTRUMENT_INCLUDE_REGEX={include}",
             f"-DFAULTDEBUG_INSTRUMENT_EXCLUDE_REGEX={exclude}"],
            text=True, capture_output=True, timeout=30)
        if run.returncode:
            return run, {}
        commands = json.loads((build / "compile_commands.json").read_text())
        flags: dict[str, bool] = {}
        for command in commands:
            source = str(Path(command["file"]).resolve())
            joined = command.get("command", " ".join(command.get("arguments", [])))
            flags[source] = HOOK_ON in joined and HOOK_OFF not in joined
        return run, flags

    def selected(flags: dict[str, bool], source: str, enabled: bool) -> bool:
        return flags.get(str((project / source).resolve())) is enabled

    results: dict[str, bool] = {}
    legacy, flags = configure("legacy", "legacy")
    results["legacy default keeps all-source behavior"] = bool(legacy and legacy.returncode == 0 and
        all(selected(flags, source, True) for source in sources) and
        "FaultDebug instrumentation profile: legacy" in legacy.stdout)
    minimal_empty, flags = configure("minimal-empty", "minimal")
    results["minimal with no allowlist instruments nothing"] = bool(minimal_empty and minimal_empty.returncode == 0 and
        all(selected(flags, source, False) for source in sources))
    minimal, flags = configure("minimal-allow", "minimal", "src/")
    results["minimal instruments only allowlisted source"] = bool(minimal and minimal.returncode == 0 and
        selected(flags, "src/app.c", True) and selected(flags, "generated/schema.c", False))
    minimal_exclude, flags = configure("minimal-exclude", "minimal", "src/", "app\\.c$")
    results["explicit exclude takes precedence over minimal allowlist"] = bool(minimal_exclude and
        minimal_exclude.returncode == 0 and selected(flags, "src/app.c", False))
    recommended, flags = configure("recommended", "recommended", "src/|other/", "other/")
    results["recommended generated/vendor defaults and user filters"] = bool(recommended and recommended.returncode == 0 and
        selected(flags, "src/app.c", True) and selected(flags, "generated/schema.c", False) and
        selected(flags, "vendor/lib.c", False) and selected(flags, "other/extra.c", False))
    full, flags = configure("full", "full", "src/", "vendor/")
    results["full ignores include and built-in excludes but honors explicit exclude"] = bool(full and full.returncode == 0 and
        selected(flags, "src/app.c", True) and selected(flags, "generated/schema.c", True) and
        selected(flags, "vendor/lib.c", False) and selected(flags, "other/extra.c", True))
    invalid, _ = configure("invalid", "mystery")
    results["invalid profile fails CMake configure"] = bool(invalid and invalid.returncode != 0 and
        "Invalid FAULTDEBUG_INSTRUMENT_PROFILE" in invalid.stderr)

    genex_project = work / "cmake-genex-fixture"
    (genex_project / "src").mkdir(parents=True)
    (genex_project / "other").mkdir()
    (genex_project / "src" / "app.c").write_text("int app(void) { return 0; }\n")
    (genex_project / "other" / "extra.c").write_text("int extra(void) { return 1; }\n")
    (genex_project / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\n"
        "project(genex_fixture C)\n"
        "set(CMAKE_EXPORT_COMPILE_COMMANDS ON)\n"
        f'include("{module}")\n'
        'add_executable(genex_fixture src/app.c "$<$<BOOL:1>:other/extra.c>")\n'
        "faultdebug_apply_source_filters(genex_fixture)\n"
    )

    def configure_genex(name: str, profile: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [cmake, "-S", str(genex_project), "-B", str(work / f"cmake-genex-{name}"),
             f"-DFAULTDEBUG_INSTRUMENT_PROFILE={profile}"],
            text=True, capture_output=True, timeout=30)

    genex_legacy = configure_genex("legacy", "legacy")
    genex_commands_path = work / "cmake-genex-legacy" / "compile_commands.json"
    genex_commands = json.loads(genex_commands_path.read_text()) if genex_commands_path.is_file() else []
    results["legacy preserves instrumentation for generator-expression sources"] = bool(
        genex_legacy.returncode == 0 and len(genex_commands) == 2 and
        all(HOOK_ON in command.get("command", " ".join(command.get("arguments", [])))
            for command in genex_commands) and
        "decision=instrumented (target-wide)" in genex_legacy.stdout)
    genex_filtered = configure_genex("filtered", "recommended")
    results["filtered profile clearly rejects generator-expression sources"] = bool(
        genex_filtered.returncode != 0 and
        "cannot select generator-expression source" in genex_filtered.stderr)
    return "PASS" if all(results.values()) else "FAIL", results


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="faultdebug-instrumentation-profiles-") as raw:
        work = Path(raw)
        results = {"wrapper": wrapper_checks(work)}
        cmake_status, cmake = cmake_checks(work)
        results["cmake_status"] = cmake_status
        results["cmake"] = cmake
        wrapper_ok = all(results["wrapper"].values())
        cmake_ok = cmake_status.startswith("NOT RUN") or all(cmake.values())
        status = "PASS" if wrapper_ok and cmake_ok else "FAIL"
        print(json.dumps({"status": status, **results}, indent=2))
        return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
