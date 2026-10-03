"""Read-only local installation and toolchain diagnostics."""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

from . import __version__ as PACKAGE_VERSION


def _check(name: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message, **details}


def _version(command: str) -> dict[str, Any] | None:
    path = shutil.which(command)
    if not path:
        return None
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True,
                              timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"path": path, "error": str(exc)}
    first = (proc.stdout or proc.stderr).splitlines()
    return {"path": path, "version": first[0] if first else "unknown",
            "returncode": proc.returncode}


def _compiler_version(name: str, setting: str, default: str) -> dict[str, Any] | None:
    """Probe the exact executable selected by the compiler wrapper.

    The wrappers use shell parameter-default expansion and pass the selected
    value as one executable name to ``exec``. They do not parse embedded args
    or search project-local compiler directories, so doctor must not either.
    """
    configured = os.environ.get(setting) or None
    command = configured or default
    selected_from = setting if configured else "wrapper default"
    path = shutil.which(command)
    if not path:
        if configured:
            return {"command": command, "error": f"configured compiler was not found: {command}",
                    "selected_from": selected_from}
        return None
    try:
        proc = subprocess.run([path, "--version"], capture_output=True, text=True,
                              timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "path": path, "error": str(exc),
                "selected_from": selected_from}
    first = (proc.stdout or proc.stderr).splitlines()
    return {"command": command, "path": path, "version": first[0] if first else "unknown",
            "returncode": proc.returncode, "selected_from": selected_from}


def _runtime_probe(path: Path) -> dict[str, Any]:
    """Load and inspect the runtime in a child with recorder startup disabled."""
    probe = (
        "import ctypes, json, sys\n"
        "lib = ctypes.CDLL(sys.argv[1])\n"
        "required = ['__cyg_profile_func_enter', '__cyg_profile_func_exit']\n"
        "missing = [name for name in required if not hasattr(lib, name)]\n"
        "print(json.dumps({'symbols': required, 'missing_symbols': missing}))\n"
        "sys.exit(1 if missing else 0)\n"
    )
    env = os.environ.copy()
    env.pop("FAULTDEBUG_SHM_FD", None)
    env.pop("FAULTDEBUG_READY_FD", None)
    env["FAULTDEBUG_DISABLE"] = "1"
    try:
        proc = subprocess.run([sys.executable, "-c", probe, str(path)],
                              capture_output=True, text=True, timeout=5,
                              check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    try:
        details = json.loads(proc.stdout)
    except json.JSONDecodeError:
        details = {}
    if proc.returncode != 0:
        return {**details, "returncode": proc.returncode,
                "error": (details.get("error") or proc.stderr.strip() or
                          "runtime load or required-symbol check failed")[:512]}
    return {**details, "returncode": 0}


def _runtime_candidates() -> list[Path]:
    configured = os.environ.get("FAULTDEBUG_RUNTIME_DIR")
    if configured:
        # The runtime override is authoritative, matching the compiler/link
        # wrapper. Do not silently substitute a library from another build.
        return [Path(configured).expanduser() / "libfaultdebug_runtime.so"]
    values: list[Path] = []
    package_root = Path(__file__).resolve().parents[1]
    for directory in ("build", "build-ci-local", "build-clang", "build-v070",
                      "build-package-check", "lib", "lib64"):
        values.append(package_root / directory / "libfaultdebug_runtime.so")
    found = shutil.which("faultdebug-collector")
    if found:
        prefix = Path(found).resolve().parent.parent
        values.extend((prefix / "lib" / "libfaultdebug_runtime.so",
                       prefix / "lib64" / "libfaultdebug_runtime.so"))
    return values


def _wrapper_paths(package_root: Path) -> tuple[Path, Path]:
    """Find compiler wrappers beside the active CLI or in source/install layouts."""
    script_dirs = (Path(sys.argv[0]).resolve().parent,
                   package_root / "scripts",
                   Path(sysconfig.get_path("scripts")))
    result: list[Path] = []
    for name in ("faultdebug-cc", "faultdebug-cxx"):
        candidates = [directory / name for directory in script_dirs]
        result.append(next((path.resolve() for path in candidates
                            if path.is_file() and os.access(path, os.X_OK)), candidates[0]))
    return result[0], result[1]


def overall_status(checks: list[dict[str, Any]]) -> str:
    essential = {"python", "package:libclang", "package:pyelftools", "package:mcp",
                 "tool:clang", "tool:clang++", "runtime-library"}
    by_name = {item["name"]: item for item in checks}
    if any(item["status"] == "FAIL" for item in checks):
        return "FAIL"
    if any(by_name.get(name, {}).get("status") == "NOT RUN" for name in essential):
        return "NOT RUN"
    return "PASS"


def collect_doctor_report() -> dict[str, Any]:
    """Inspect the current Python, CLI, compiler, wrapper, and runtime setup."""
    checks: list[dict[str, Any]] = []
    py_ok = (sys.version_info.major, sys.version_info.minor) == (3, 12)
    checks.append(_check("python", "PASS" if py_ok else "FAIL",
                         f"Python {platform.python_version()}; project requires Python 3.12",
                         version=platform.python_version(), executable=sys.executable,
                         required="3.12.x"))

    for package in ("faultdebug", "libclang", "pyelftools", "mcp"):
        try:
            distribution_version = importlib.metadata.version(package)
            if package == "faultdebug":
                from . import __version__ as source_version
                checks.append(_check(
                    f"package:{package}", "PASS",
                    f"faultdebug source {source_version} is loaded",
                    version=source_version, distribution_version=distribution_version))
            else:
                checks.append(_check(f"package:{package}", "PASS", f"{package} {distribution_version} is installed",
                                     version=distribution_version))
        except importlib.metadata.PackageNotFoundError:
            checks.append(_check(f"package:{package}", "FAIL", f"{package} is not installed"))

    package_root = Path(__file__).resolve().parents[1]
    compiler_settings = {"clang": ("FAULTDEBUG_REAL_CC", "cc"),
                         "clang++": ("FAULTDEBUG_REAL_CXX", "c++")}
    for name in ("clang", "clang++", "cmake", "ninja"):
        result = (_compiler_version(name, *compiler_settings[name]) if name in compiler_settings
                  else _version(name))
        if result is None:
            if name in compiler_settings:
                setting, default = compiler_settings[name]
                command = os.environ.get(setting) or default
                message = (f"required Clang 18 compiler unavailable; wrapper command "
                           f"{command!r} was not found")
                checks.append(_check(f"tool:{name}", "NOT RUN", message,
                                     command=command, selected_from="wrapper default",
                                     setting=setting))
            else:
                checks.append(_check(f"tool:{name}", "NOT RUN", f"{name} was not found on PATH"))
            continue
        first = result.get("version", "")
        is_clang = name in ("clang", "clang++")
        supported = not is_clang or "clang version 18" in first.lower()
        status = ("PASS" if not result.get("error") and
                  result.get("returncode") == 0 and supported else "FAIL")
        if result.get("error"):
            message = f"{name} compiler probe failed: {result['error']}"
        elif not supported:
            message = f"{name} is present but Clang 18 is required: {first}"
        else:
            message = f"{name}: {first}"
        checks.append(_check(f"tool:{name}", status, message, **result))

    wrapper_paths = _wrapper_paths(package_root)
    for wrapper in wrapper_paths:
        ok = wrapper.is_file() and os.access(wrapper, os.X_OK)
        checks.append(_check(f"wrapper:{wrapper.name}", "PASS" if ok else "FAIL",
                             f"{wrapper} is {'executable' if ok else 'missing or not executable'}",
                             path=str(wrapper)))

    candidates = _runtime_candidates()
    attempted: list[dict[str, Any]] = []
    runtime: Path | None = None
    runtime_details: dict[str, Any] = {}
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        details = _runtime_probe(resolved)
        if not details.get("error") and details.get("returncode") == 0:
            runtime, runtime_details = resolved, details
            break
        attempted.append({"path": str(resolved), **details})
    if runtime:
        checks.append(_check(
            "runtime-library", "PASS",
            f"Runtime library loaded and exports recorder hooks at {runtime}",
            path=str(runtime), **runtime_details,
            rejected_candidates=attempted,
            searched=[str(path) for path in candidates]))
    elif attempted:
        checks.append(_check(
            "runtime-library", "FAIL",
            "Runtime library candidate(s) could not be loaded with the required recorder hooks",
            path=attempted[0]["path"], candidates=attempted,
            searched=[str(path) for path in candidates]))
    else:
        checks.append(_check(
            "runtime-library", "NOT RUN",
            "libfaultdebug_runtime.so was not found; instrumented linking is unavailable",
            path=None, searched=[str(path) for path in candidates]))

    overall = overall_status(checks)
    return {
        "schema": 1,
        "schema_name": "faultdebug.doctor",
        "version": PACKAGE_VERSION,
        "status": overall,
        "environment": {"platform": platform.platform(), "system": platform.system(),
                         "machine": platform.machine(), "python": sys.version},
        "checks": checks,
        "summary": {status: sum(item["status"] == status for item in checks)
                    for status in ("PASS", "FAIL", "NOT RUN")},
    }


def format_doctor_report(report: dict[str, Any]) -> str:
    lines = [f"fault-debug doctor: {report['status']}"]
    lines.extend(f"{item['status']:8} {item['name']}: {item['message']}"
                 for item in report["checks"])
    return "\n".join(lines)


def doctor_json(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2)
