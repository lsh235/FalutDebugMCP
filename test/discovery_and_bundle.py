#!/usr/bin/env python3
"""Focused checks for spool discovery and verified binary bundle lookup."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faultdebug.discovery import inspect_spool
from faultdebug.bundle import BundleError, create_bundle, load_bundle


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fd-discovery-") as raw:
        root = pathlib.Path(raw)
        nested = root / "nested"
        nested.mkdir()
        valid = nested / "fault-1.json"
        valid.write_text(json.dumps({"process": {"pid": 1}, "collector": {"ok": True}}))
        bad = nested / "fault-2.fault"
        bad.write_bytes(b"not-an-artifact")
        result = inspect_spool(root, include_json=True)
        assert result["count"] == 2 and result["valid"] == 1 and result["invalid"] == 1
        source_root = root / "sources"
        source_root.mkdir()
        source = source_root / "source.c"
        source.write_text("int main(void) { return 0; }\n")
        binary = ROOT / "build" / "libfaultdebug_runtime.so"
        if binary.is_file():
            bundle_dir = root / "bundle"
            bundle = create_bundle(source_root, bundle_dir, files=[source], binaries=[binary])
            loaded = load_bundle(bundle_dir)
            assert loaded.manifest["binaries"][0]["sha256"] == hashlib.sha256((bundle_dir / loaded.manifest["binaries"][0]["path"]).read_bytes()).hexdigest()
            binary_path = bundle_dir / loaded.manifest["binaries"][0]["path"]
            os.chmod(binary_path, 0o600)
            binary_path.write_bytes(binary_path.read_bytes() + b"tampered")
            try:
                load_bundle(bundle_dir)
            except BundleError:
                pass
            else:
                raise AssertionError("tampered bundle binary was accepted")
        evil = root / "evil-bundle"
        evil.mkdir()
        outside = root.parent / (root.name + "-outside.txt")
        outside.write_text("outside")
        manifest = {"schema": 1, "kind": "faultdebug-source-bundle", "files": [{
            "path": "../" + outside.name, "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            "size": outside.stat().st_size, "kind": "source"}]}
        (evil / "bundle.json").write_text(json.dumps(manifest))
        try:
            load_bundle(evil)
        except BundleError:
            pass
        else:
            raise AssertionError("bundle path traversal was accepted")
        outside.unlink()
    print("discovery-bundle-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
