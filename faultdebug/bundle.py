"""Immutable source and binary evidence bundles for offline inspection."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from .provenance import binary_build_id


class BundleError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class BundleFile:
    path: str
    sha256: str
    size: int
    kind: str = "source"


@dataclass(frozen=True)
class SourceBundle:
    root: Path
    manifest: dict

    @property
    def files(self) -> tuple[BundleFile, ...]:
        try:
            return tuple(BundleFile(**row) for row in self.manifest.get("files", []))
        except (TypeError, ValueError) as exc:
            raise BundleError("bundle file manifest entry is malformed") from exc

    def _verified_path(self, relative: str, label: str) -> Path:
        if not isinstance(relative, str) or not relative:
            raise BundleError(f"{label} path is malformed")
        root = self.root.resolve()
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise BundleError(f"{label} path escapes bundle root: {relative}")
        return path

    def verify(self) -> None:
        if self.manifest.get("schema") != 1 or self.manifest.get("kind") != "faultdebug-source-bundle":
            raise BundleError("unsupported source bundle schema")
        for entry in self.files:
            path = self._verified_path(entry.path, "bundle file")
            if not path.is_file():
                raise BundleError(f"bundle file is missing: {entry.path}")
            if path.stat().st_size != entry.size or sha256_file(path) != entry.sha256:
                raise BundleError(f"bundle file hash mismatch: {entry.path}")
        for entry in self.manifest.get("binaries", []):
            if not isinstance(entry, dict):
                raise BundleError("binary manifest entry is malformed")
            relative = entry.get("path")
            expected = entry.get("sha256")
            if not isinstance(relative, str) or not isinstance(expected, str):
                raise BundleError("binary manifest entry is malformed")
            path = self._verified_path(relative, "bundle binary")
            if not path.is_file() or sha256_file(path) != expected:
                raise BundleError(f"bundle binary hash mismatch: {relative}")

    def source_path(self, original: str | os.PathLike[str]) -> Path | None:
        raw = Path(original)
        def matches(entry: BundleFile) -> bool:
            rel = entry.path.removeprefix("source/")
            rel_parts = Path(rel).parts
            return entry.kind == "source" and (entry.path == raw.as_posix() or tuple(raw.parts[-len(rel_parts):]) == rel_parts)
        exact = [entry for entry in self.files if matches(entry)]
        if not exact:
            exact = [entry for entry in self.files if entry.kind == "source" and Path(entry.path).name == raw.name]
        if len(exact) != 1:
            return None
        entry = exact[0]
        path = self._verified_path(entry.path, "source")
        if path.is_file() and sha256_file(path) == entry.sha256:
            return path
        return None

    def index_rows(self) -> list[dict]:
        index_path = self.manifest.get("index")
        if not index_path:
            return []
        path = self._verified_path(index_path, "index")
        expected = self.manifest.get("index_sha256")
        if not path.is_file() or (expected and sha256_file(path) != expected):
            raise BundleError("captured function index is missing or changed")
        return list(json.loads(path.read_text()).get("functions", []))


def load_bundle(path: str | os.PathLike[str]) -> SourceBundle:
    root = Path(path)
    if root.is_file():
        if root.name != "bundle.json":
            raise BundleError("bundle path must be a directory or bundle.json")
        root = root.parent
    manifest_path = root / "bundle.json"
    if not manifest_path.is_file():
        raise BundleError(f"bundle manifest not found: {manifest_path}")
    bundle = SourceBundle(root, json.loads(manifest_path.read_text()))
    bundle.verify()
    return bundle


def create_bundle(
    source_root: Path,
    output: Path,
    *,
    files: Iterable[Path] | None = None,
    index: Path | None = None,
    binaries: Iterable[Path] | None = None,
    build_ids: dict[str, str] | None = None,
) -> SourceBundle:
    source_root = source_root.resolve(); output = output.resolve()
    if output == source_root or source_root in output.parents:
        raise BundleError("bundle output must not be inside the source root")
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    selected = list(files) if files is not None else [p for p in source_root.rglob("*") if p.is_file() and not p.is_symlink()]
    for source in sorted({Path(p).resolve() for p in selected}, key=str):
        try: rel = source.relative_to(source_root)
        except ValueError as exc: raise BundleError(f"path escapes bundle root: {source}") from exc
        dest = output / "source" / rel; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, dest)
        os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        rows.append({"path": f"source/{rel.as_posix()}", "sha256": sha256_file(dest), "size": dest.stat().st_size, "kind": "source"})
    manifest: dict = {"schema": 1, "kind": "faultdebug-source-bundle", "files": rows}
    if index is not None:
        index = index.resolve()
        if not index.is_file(): raise BundleError(f"index file not found: {index}")
        dest = output / "index.json"; shutil.copyfile(index, dest); os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        manifest["index"] = "index.json"; manifest["index_sha256"] = sha256_file(dest)
    binary_rows = []
    for binary in binaries or ():
        binary = Path(binary).resolve()
        if not binary.is_file(): raise BundleError(f"binary not found: {binary}")
        rel = f"binaries/{binary.name}"; dest = output / rel; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(binary, dest)
        os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        supplied = (build_ids or {}).get(str(binary))
        captured = supplied or binary_build_id(binary)
        binary_rows.append({"path": rel, "source": str(binary), "sha256": sha256_file(dest), "size": dest.stat().st_size, "build_id": captured.hex() if isinstance(captured, bytes) else str(captured)})
    if binary_rows: manifest["binaries"] = binary_rows
    manifest_path = output / "bundle.json"; manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n"); os.chmod(manifest_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    bundle = SourceBundle(output, manifest); bundle.verify(); return bundle
