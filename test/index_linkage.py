#!/usr/bin/env python3
"""Independent libclang check for C++ linkage and relative compdb paths."""
import json, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from faultdebug.index import build_index

def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); (root / ".git").mkdir()
        (root / "include").mkdir()
        header = root / "include" / "inline.hpp"; header.write_text("static inline int header_helper() { return 7; }\nvoid declared();\n")
        source = root / "deliberate.cpp"; source.write_text('#include "inline.hpp"\nvoid declared() {}\nstatic void deliberate_ill() {}\nextern "C" void c_entry() { deliberate_ill(); }\n')
        compdb = root / "compile_commands.json"; compdb.write_text(json.dumps([{"directory": str(root), "file": "deliberate.cpp", "arguments": ["clang++", "-Iinclude", "-std=c++17", "-c", "deliberate.cpp", "-o", str(root / "deliberate.o")]}]))
        result = build_index(compdb, root / "index.json")
        cpp = next(row for row in result["functions"] if row["name"] == "deliberate_ill")
        c = next(row for row in result["functions"] if row["name"] == "c_entry")
        assert cpp["linkage_name"].startswith("_ZL") and cpp["linkage_name"] != cpp["name"]
        assert c["linkage_name"] == "c_entry"
        header_row = next(row for row in result["functions"] if row["name"] == "header_helper")
        assert header_row["file"].endswith("inline.hpp")
        definition = next(row for row in result["functions"] if row["name"] == "declared")
        assert definition["is_definition"] and definition["file"].endswith("deliberate.cpp")
    print("index-linkage-ok")
    return 0

if __name__ == "__main__": raise SystemExit(main())
