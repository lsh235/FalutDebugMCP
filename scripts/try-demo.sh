#!/usr/bin/env bash
# Run the real shopping fixture using a prebuilt image and the local Docker engine.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
tag="demo-2026-10-11"
image="${FAULTDEBUG_DEMO_IMAGE:-faultdebug-shop:$tag}"
output="${FAULTDEBUG_DEMO_OUTPUT:-$root/build/demo-$(date -u +%Y%m%dT%H%M%S)-$$}"
port="${FAULTDEBUG_DEMO_PORT:-18860}"
report_port="${FAULTDEBUG_REPORT_PORT:-18870}"
serve=1
if [[ "${1:-}" == "--no-serve" ]]; then serve=0; shift; fi
if [[ "$#" != 0 ]]; then echo "Usage: scripts/try-demo.sh [--no-serve]" >&2; exit 2; fi
command -v docker >/dev/null || { echo "Install Docker Engine and Docker Compose first." >&2; exit 2; }
docker compose version >/dev/null
endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ||
      "$endpoint" != unix:///var/run/docker.sock || -n "${DOCKER_HOST:-}" ]]; then
  echo "This demo supports Linux x86_64 with a local Docker Engine at /var/run/docker.sock." >&2
  exit 2
fi
compose="$(docker info --format '{{range .ClientInfo.Plugins}}{{if eq .Name "compose"}}{{.Path}}{{end}}{{end}}')"
[[ -f "$compose" ]] || { echo "Docker Compose plugin executable was not found." >&2; exit 2; }
[[ "$output" = /* && ! -e "$output" ]] || { echo "Choose a new absolute FAULTDEBUG_DEMO_OUTPUT directory." >&2; exit 2; }
mkdir -p "$(dirname "$output")"
if ! docker image inspect "$image" >/dev/null 2>&1; then
  command -v curl >/dev/null || { echo "curl is required to download the image." >&2; exit 2; }
  cache="$(mktemp -d)"
  trap 'rm -rf "$cache"' EXIT
  url="https://github.com/lsh235/FalutDebugMCP/releases/download/$tag"
  curl --fail --location --retry 3 "$url/faultdebug-demo-amd64.tar.gz" -o "$cache/faultdebug-demo-amd64.tar.gz"
  curl --fail --location --retry 3 "$url/SHA256SUMS" -o "$cache/SHA256SUMS"
  (cd "$cache" && sha256sum --check SHA256SUMS)
  docker load --input "$cache/faultdebug-demo-amd64.tar.gz"
  rm -rf "$cache"
  trap - EXIT
fi
resolved="$(docker image inspect --format '{{.Id}}' "$image")"
echo "Image: $resolved"
echo "Running 8 independent services: success, payment_crash, inventory_timeout."
# Preserve absolute host paths for the host engine's Compose bind mounts.
docker run --rm --init --network host --user "$(id -u):$(id -g)" \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  --volume "$root:$root:ro" \
  --volume "$(dirname "$output"):$(dirname "$output")" \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  --volume "$(command -v docker):/usr/bin/docker:ro" \
  --volume "$compose:/usr/libexec/docker/cli-plugins/docker-compose:ro" \
  --workdir "$root" --env HOME=/tmp --entrypoint python "$resolved" \
  "$root/test/shop/run.py" --image "$resolved" --processes 8 --requests 1 \
  --concurrency 1 --scenarios success payment_crash inventory_timeout \
  --port "$port" --output "$output"
echo "Reports: $output/index.html"
if [[ "$serve" == 1 ]]; then
  echo "Open http://127.0.0.1:$report_port/index.html ; Ctrl+C stops the report server."
  exec docker run --rm --init --user "$(id -u):$(id -g)" \
    --publish "127.0.0.1:$report_port:8870" --volume "$output:/reports:ro" \
    --entrypoint python "$resolved" -m http.server 8870 --bind 0.0.0.0 --directory /reports
fi
