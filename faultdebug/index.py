"""Compilation-database index with explicit unresolved-edge reporting."""
from __future__ import annotations
import json, os, shlex
from pathlib import Path

class IndexErrorRuntime(RuntimeError): pass

def _project_root(entries: list[dict]) -> Path:
    files = []
    for entry in entries:
        path = Path(entry["file"])
        if not path.is_absolute(): path = Path(entry.get("directory", ".")) / path
        files.append(path.resolve())
    if not files: raise IndexErrorRuntime("compile database has no source files")
    common = Path(os.path.commonpath([str(path.parent) for path in files]))
    markers = {"CMakeLists.txt", "meson.build", "configure.ac", ".git"}
    for candidate in (common, *common.parents):
        if any((candidate / marker).exists() for marker in markers): return candidate
    return common

def build_index(compdb: Path, output: Path) -> dict:
    entries = json.loads(compdb.read_text())
    if not isinstance(entries, list):
        raise IndexErrorRuntime("compile_commands.json must be an array")
    try:
        from clang import cindex
    except ImportError as exc:
        raise IndexErrorRuntime("libclang Python bindings are required") from exc
    idx = cindex.Index.create()
    functions = []
    coverage_failures = []
    project_root = _project_root(entries)
    for entry in entries:
        directory = Path(entry.get("directory", ".")).resolve()
        path = Path(entry["file"])
        if not path.is_absolute(): path = directory / path
        path = path.resolve()
        args = entry.get("arguments") or shlex.split(entry.get("command", ""))
        if args: args = args[1:]
        cleaned = []
        skip = False
        for arg in args:
            if skip: skip = False; continue
            if arg in ("-c", "-M", "-MM"): continue
            if arg in ("-o", "-MF", "-MT"): skip = True; continue
            if arg == str(path) or arg == path.name: continue
            cleaned.append(arg)
        tu = idx.parse(str(path), args=cleaned, options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        diagnostics = [{"severity": d.severity, "message": d.spelling, "file": str(d.location.file) if d.location.file else None, "line": d.location.line} for d in tu.diagnostics]
        for cur in tu.cursor.walk_preorder():
            if cur.kind in (cindex.CursorKind.FUNCTION_DECL, cindex.CursorKind.CXX_METHOD, cindex.CursorKind.FUNCTION_TEMPLATE):
                usr = cur.get_usr() or f"{cur.spelling}@{cur.location.file}:{cur.location.line}"
                if cur.location.file:
                    location = Path(str(cur.location.file)).resolve()
                    # Include project headers and inline/template definitions,
                    # while excluding system and unrelated external headers.
                    if project_root not in location.parents and location != project_root: continue
                linkage_name = getattr(cur, "mangled_name", "") or cur.spelling
                functions.append({"id": usr, "name": cur.spelling, "linkage_name": linkage_name, "kind": str(cur.kind), "file": str(cur.location.file) if cur.location.file else None, "line": cur.location.line, "is_definition": bool(cur.is_definition()), "edges": [], "unresolved_edges": [], "source_range": {"start": cur.extent.start.line, "end": cur.extent.end.line}})
                for node in cur.walk_preorder():
                    if node.kind == cindex.CursorKind.CALL_EXPR:
                        callee = node.referenced
                        if callee is not None and callee.get_usr(): functions[-1]["edges"].append({"callee_id": callee.get_usr(), "kind": "direct"})
                        else: functions[-1]["unresolved_edges"].append({"spelling": node.spelling, "kind": "indirect_or_virtual"})
        if diagnostics:
            for d in diagnostics: d["translation_unit"] = str(path)
            coverage_failures.extend(diagnostics)
    # A declaration and definition share a USR. Prefer the definition so source
    # lookup returns implementation evidence (for example format-inl.h), while
    # retaining edges discovered on either cursor.
    unique: dict[str, dict] = {}
    for row in functions:
        key = row["id"]; current = unique.get(key)
        if current is None or (row.get("is_definition") and not current.get("is_definition")):
            chosen, other = row, current
        else:
            chosen, other = current, row
        if other is not None:
            chosen["edges"] = list({json.dumps(edge, sort_keys=True): edge for edge in chosen.get("edges", []) + other.get("edges", [])}.values())
            chosen["unresolved_edges"] = list({json.dumps(edge, sort_keys=True): edge for edge in chosen.get("unresolved_edges", []) + other.get("unresolved_edges", [])}.values())
        unique[key] = chosen
    result = {"version": 1, "functions": list(unique.values()), "coverage_failures": coverage_failures}
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result
