#!/usr/bin/env bash
set -euo pipefail

# Reproduce the bounded fmt 11.1.4 external evaluation.  Missing toolchain,
# package, or network prerequisites are reported as NOT RUN.  A completed
# build or evaluator failure is reported as FAIL and never relabelled PASS.

repo_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
output=${FAULTDEBUG_FMT_REPORT:-${repo_root}/fmt-evaluation.json}
work=${FAULTDEBUG_FMT_WORK:-${TMPDIR:-/tmp}/faultdebug-fmt-evaluation}
fmt_source=${FAULTDEBUG_FMT_SOURCE_DIR:-}
mkdir -p "$(dirname "$output")" "$work"

not_run() {
  local reason=$1
  python3 - "$output" "$reason" <<'PY'
import json, pathlib, sys
path, reason = sys.argv[1:]
pathlib.Path(path).write_text(json.dumps({"status": "NOT RUN", "reason": reason, "checks": {}}, indent=2) + "\n")
print(json.dumps({"status": "NOT RUN", "reason": reason}, sort_keys=True))
PY
  exit 0
}

fail_run() {
  local reason=$1
  python3 - "$output" "$reason" <<'PY'
import json, pathlib, sys
path, reason = sys.argv[1:]
pathlib.Path(path).write_text(json.dumps({"status": "FAIL", "reason": reason, "checks": {}}, indent=2) + "\n")
print(json.dumps({"status": "FAIL", "reason": reason}, sort_keys=True))
PY
  exit 1
}

for tool in python3 git cmake ninja clang-18 clang++-18 readelf; do
  command -v "$tool" >/dev/null 2>&1 || not_run "required tool unavailable: $tool"
done
python3 -c 'import faultdebug, clang.cindex, elftools' >/dev/null 2>&1 || not_run "Python dependencies unavailable (faultdebug/libclang/pyelftools)"

if [[ -z "$fmt_source" ]]; then
  [[ "${FAULTDEBUG_FMT_OFFLINE:-0}" != 1 ]] || not_run "external source is not supplied and offline mode is enabled"
  fmt_source="$work/fmt"
  if [[ ! -d "$fmt_source/.git" ]]; then
    timeout 20 git ls-remote --exit-code https://github.com/fmtlib/fmt.git refs/tags/11.1.4 >/dev/null 2>&1 \
      || not_run "external network unavailable for fmt 11.1.4"
    rm -rf "$fmt_source"
    git clone --depth 1 --branch 11.1.4 https://github.com/fmtlib/fmt.git "$fmt_source" \
      || fail_run "fmt 11.1.4 clone failed after network probe"
  fi
fi
[[ -f "$fmt_source/CMakeLists.txt" ]] || not_run "fmt source directory is unavailable"

native_build="$work/faultdebug-build"
fmt_build="$work/fmt-build"
prefix="$work/fmt-prefix"
driver_dir="$work/driver"
artifact_dir="$work/artifacts"
mkdir -p "$driver_dir" "$artifact_dir"

cmake -S "$repo_root" -B "$native_build" -G Ninja \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
  -DFAULTDEBUG_BUILD_TESTS=OFF -DFAULTDEBUG_ENABLE_PROVENANCE=OFF \
  || fail_run "faultdebug Clang 18 configure failed"
cmake --build "$native_build" --parallel 2 \
  || fail_run "faultdebug native build failed"

cmake -S "$fmt_source" -B "$fmt_build" -G Ninja \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
  -DFMT_TEST=OFF -DFMT_DOC=OFF -DFMT_INSTALL=ON \
  || fail_run "fmt 11.1.4 configure failed"
cmake --build "$fmt_build" --parallel 2 \
  || fail_run "fmt 11.1.4 build failed"
cmake --install "$fmt_build" --prefix "$prefix" \
  || fail_run "fmt 11.1.4 install failed"

fmt_lib_dir=$(find "$prefix" -type f -name 'libfmt.a' -printf '%h\n' | head -1)
[[ -n "$fmt_lib_dir" ]] || fail_run "installed fmt library was not found"

cat > "$driver_dir/main.cpp" <<'CPP'
#include <csignal>
#include <fmt/format.h>
#include <iostream>
#include <string>
int main(int argc, char **argv) {
  std::cout << fmt::format("fmt-external:{}\n", 42);
  if (argc > 1 && std::string(argv[1]) == "sigill") std::raise(SIGILL);
  return 0;
}
CPP

clang++-18 -std=c++17 -O0 -g "$driver_dir/main.cpp" \
  -I"$prefix/include" -L"$fmt_lib_dir" -Wl,-rpath,"$fmt_lib_dir" -lfmt \
  -Wl,--build-id=sha1 -o "$driver_dir/fmt-driver-original" \
  || fail_run "original fmt driver build failed"
FAULTDEBUG_REAL_CXX=clang++-18 FAULTDEBUG_RUNTIME_DIR="$native_build" \
  "$repo_root/scripts/faultdebug-cxx" -std=c++17 -I"$prefix/include" \
  -L"$fmt_lib_dir" -Wl,-rpath,"$fmt_lib_dir" "$driver_dir/main.cpp" \
  -lfmt -o "$driver_dir/fmt-driver-instrumented" \
  || fail_run "instrumented fmt driver build failed"

PYTHONPATH="$repo_root" python3 -m faultdebug.cli run \
  --artifact-dir "$artifact_dir" -- "$driver_dir/fmt-driver-instrumented" sigill \
  || true
artifact=$(find "$artifact_dir" -maxdepth 1 -type f -name '*.fault' -print -quit)
[[ -n "$artifact" ]] || fail_run "instrumented fmt driver produced no fault artifact"

index="$work/fmt-index.json"
bundle="$work/fmt-bundle"
mcp_result="$work/mcp-result.json"
[[ -f "$fmt_build/compile_commands.json" ]] || fail_run "fmt compile database was not generated"
PYTHONPATH="$repo_root" python3 -m faultdebug.cli index "$fmt_build/compile_commands.json" -o "$index" \
  || fail_run "fmt compilation database indexing failed"
PYTHONPATH="$repo_root" python3 - "$fmt_source" "$bundle" "$index" "$artifact" "$driver_dir/fmt-driver-instrumented" "$mcp_result" <<'PY' \
  || fail_run "verified bundle or MCP evaluation failed"
import json, sys
from pathlib import Path
from faultdebug.bundle import create_bundle
from faultdebug.mcp_server import make_server

source_root, bundle_path, index_path, artifact_path, binary_path, result_path = map(Path, sys.argv[1:])
bundle = create_bundle(source_root, bundle_path, index=index_path,
                       binaries=[binary_path])
rows = bundle.index_rows()
row = next((item for item in rows if item.get("name") == "vformat_to" and
            item.get("file", "").endswith("format-inl.h") and item.get("is_definition")), None)
if row is None:
    raise RuntimeError("fmt format-inl.h definition was not indexed")
root = artifact_path.parents[1]
artifact_name = artifact_path.relative_to(root).as_posix()
bundle_name = bundle_path.relative_to(root).as_posix()
tools = make_server(root)._tool_manager._tools
result = {
    "open_fault": tools["open_fault"].fn(artifact_name, bundle_name),
    "get_thread_trace": tools["get_thread_trace"].fn(artifact_name, None, 0),
    "resolve_addresses": tools["resolve_addresses"].fn(artifact_name, [1], bundle_name),
    "get_function_source": tools["get_function_source"].fn(artifact_name, row["id"], bundle_name),
    "get_call_relations": tools["get_call_relations"].fn(artifact_name, row["id"], "outbound", bundle_name),
}
result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
PY

PYTHONPATH="$repo_root" python3 test/external_project_evaluation.py \
  --original-build "$driver_dir/fmt-driver-original" \
  --instrumented-build "$driver_dir/fmt-driver-instrumented" \
  --binary "$driver_dir/fmt-driver-instrumented" \
  --artifact "$artifact" --source "$fmt_source/include/fmt/format-inl.h" \
  --mcp-result "$mcp_result" \
  --output "$output"
