#!/usr/bin/env bash
set -euo pipefail

# Offline-friendly Ubuntu Noble bootstrap. Packages are downloaded through apt's
# normal repository configuration and extracted locally; sudo and dpkg --install
# are intentionally not used.
repo_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
tool_root="$repo_root/.tools"
debs="$tool_root/debs"
prefix="$tool_root/clang"
mkdir -p "$debs" "$prefix" "$tool_root/bin"
(cd "$debs" && apt-get download clang-18 llvm-18 llvm-18-runtime llvm-18-tools libllvm18 libclang1-18 libclang-cpp18)
for archive in "$debs"/*.deb; do dpkg-deb -x "$archive" "$prefix"; done
ln -sfn ../clang/usr/bin/clang-18 "$tool_root/bin/clang"
ln -sfn clang "$tool_root/bin/clang++"
ln -sfn ../clang/usr/lib/llvm-18/bin/llvm-symbolizer "$tool_root/bin/llvm-symbolizer"
cat > "$tool_root/env.sh" <<EOF
export PATH="$tool_root/bin:\$PATH"
export LD_LIBRARY_PATH="$prefix/usr/lib/llvm-18/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
EOF
echo "native toolchain ready: $tool_root/bin/clang and $tool_root/bin/llvm-symbolizer"
