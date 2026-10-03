"""Bounded discovery and validation of fault artifact spools."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .format import collect_file


class DiscoveryError(ValueError):
    pass


def discover_paths(root: Path, *, pattern: str = "fault-*.fault", include_json: bool = False,
                   recursive: bool = True, limit: int = 10000) -> list[Path]:
    """Return deterministic artifact paths below an explicit spool root."""
    root = root.expanduser().resolve()
    if limit < 1 or limit > 100000:
        raise DiscoveryError("limit must be between 1 and 100000")
    if root.is_file():
        if root.suffix not in {".fault", ".json"}:
            raise DiscoveryError("artifact root file must be .fault or .json")
        return [root]
    if not root.is_dir():
        raise DiscoveryError(f"artifact spool does not exist: {root}")
    patterns = [pattern]
    if include_json and pattern == "fault-*.fault":
        patterns.append("fault-*.json")
    paths: set[Path] = set()
    for selected in patterns:
        iterator = root.rglob(selected) if recursive else root.glob(selected)
        for path in iterator:
            resolved = path.resolve()
            if path.is_file() and (resolved.parent == root or root in resolved.parents):
                paths.add(resolved)
                if len(paths) > limit:
                    raise DiscoveryError(f"artifact spool exceeds limit {limit}")
    return sorted(paths, key=lambda path: (str(path.relative_to(root)), str(path)))


def inspect_spool(root: Path, *, pattern: str = "fault-*.fault", include_json: bool = False,
                  recursive: bool = True, limit: int = 10000) -> dict[str, Any]:
    root = root.expanduser().resolve()
    paths = discover_paths(root, pattern=pattern, include_json=include_json,
                           recursive=recursive, limit=limit)
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            report = collect_file(path)
            relative = path.name if root.is_file() else path.relative_to(root).as_posix()
            raw = path.read_bytes()
            rows.append({"path": relative, "status": "PASS", "sha256": hashlib.sha256(raw).hexdigest(),
                         "pid": (report.get("process") or {}).get("pid"),
                         "collector": report.get("collector", {}),
                         "context": report.get("context", {})})
        except Exception as exc:  # retain malformed spool entries as evidence
            relative = path.name if root.is_file() else path.relative_to(root).as_posix()
            rows.append({"path": relative, "status": "FAIL", "error": str(exc)})
    return {"schema": 1, "root": str(root), "count": len(rows),
            "valid": sum(row["status"] == "PASS" for row in rows),
            "invalid": sum(row["status"] == "FAIL" for row in rows),
            "artifacts": rows}
