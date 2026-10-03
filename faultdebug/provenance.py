"""Build-time provenance helper.

It records immutable inputs supplied by the build, rather than hashing the
current worktree after a binary has been produced.
"""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess
import re
from pathlib import Path

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def make_manifest(output: Path, *, build_id: str, artifacts: list[Path], source_manifest: Path, compile_commands: Path | None = None, toolchain: dict | None = None) -> dict:
    if not build_id or not source_manifest.is_file():
        raise ValueError("build_id and immutable source manifest are required")
    result = {
        "schema": 1, "build_id": build_id,
        "artifacts": [{"path": str(p), "sha256": sha256(p)} for p in artifacts if p.is_file()],
        "source_manifest": {"path": str(source_manifest), "sha256": sha256(source_manifest)},
        "compile_commands": {"path": str(compile_commands), "sha256": sha256(compile_commands)} if compile_commands and compile_commands.is_file() else None,
        "toolchain": toolchain or {},
    }
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result

def snapshot_source(root: Path, output: Path) -> Path:
    """Capture source and build settings before compilation starts."""
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    excluded = {".git", ".venv", ".tools", "build", "dist", "__pycache__",
                "output", "test-results"}
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if (not path.is_file() or any(part in excluded or part.endswith(".egg-info")
                                      for part in parts)
                or (parts and parts[0].startswith("build-"))):
            continue
        rel = path.relative_to(root)
        dest = output / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, dest)
        rows.append({"path": rel.as_posix(), "sha256": sha256(path), "snapshot": (Path("files") / rel).as_posix()})
    manifest = output / "source-manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "root": str(root), "files": rows}, indent=2, sort_keys=True) + "\n")
    return manifest

def binary_build_id(binary: Path) -> str:
    """Read the linker Build ID without consulting the current source tree."""
    try:
        from elftools.elf.elffile import ELFFile
        with binary.open("rb") as stream:
            elf = ELFFile(stream)
            for section in elf.iter_sections():
                if section.name == ".note.gnu.build-id":
                    for note in section.iter_notes():
                        if note["n_type"] == "NT_GNU_BUILD_ID":
                            value = note["n_desc"]
                            return value.hex() if isinstance(value, bytes) else str(value).lower()
    except Exception:
        pass
    try:
        text = subprocess.check_output(["readelf", "-n", str(binary)], text=True, stderr=subprocess.DEVNULL)
        match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", text)
        if match: return match.group(1).lower()
    except Exception:
        pass
    raise ValueError(f"missing GNU Build ID: {binary}")

def main() -> int:
    import argparse
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("--root", type=Path, required=True); s.add_argument("--output", type=Path, required=True)
    m = sub.add_parser("manifest"); m.add_argument("--output", type=Path, required=True); m.add_argument("--binary", type=Path, required=True); m.add_argument("--source-manifest", type=Path, required=True); m.add_argument("--compile-commands", type=Path)
    ns = p.parse_args()
    if ns.action == "snapshot": snapshot_source(ns.root, ns.output); return 0
    make_manifest(ns.output, build_id=binary_build_id(ns.binary), artifacts=[ns.binary], source_manifest=ns.source_manifest, compile_commands=ns.compile_commands)
    return 0

if __name__ == "__main__": raise SystemExit(main())
