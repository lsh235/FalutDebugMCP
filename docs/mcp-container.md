# Run the read-only MCP inspector in Docker

This image packages the Python MCP inspector. It does not compile or trace
programs. Build and capture artifacts with the native workflow, then mount only
the artifact directory into this container as read-only.

## Build

From the repository root:

```sh
docker build -f Dockerfile.mcp -t faultdebug-mcp:local .
```

The image uses Python 3.12 and installs the pinned application dependencies from
`pyproject.toml`. It does not include the C runtime, Clang, or CMake toolchain.

## Configure an MCP client

Replace `/absolute/path/to/artifacts` with the host directory containing the
`.fault` files, source bundles, or existing evidence store. The bind mount is
read-only, and the MCP process runs as an unprivileged container user.

```json
{
  "mcpServers": {
    "faultdebug": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--mount", "type=bind,src=/absolute/path/to/artifacts,dst=/artifacts,readonly",
        "faultdebug-mcp:local"
      ]
    }
  }
}
```

The MCP server uses stdio. It reads only files under `/artifacts`; it does not
mount the Docker socket, upload evidence, or contact a remote service. A bundle
or evidence database must be inside the mounted directory to be available.
Host file permissions still apply: the container user (UID 65532) must be able
to read the mounted files. If your artifact directory is private to your user,
run the container with `--user "$(id -u):$(id -g)"` before `--mount`, and ensure
the image's `/artifacts` path is not needed for writes.

## Security and scope

The MCP tools are read-only and validate relative paths against the configured
root. The native capture launcher and report-generating CLI are separate
workflows and can write output. Treat fault captures and source bundles as
sensitive; do not expose them to untrusted MCP clients.

## 한국어 안내

이 이미지는 Python MCP 조회기만 포함하며 C/C++ 프로그램을 빌드하거나
추적하지 않습니다. native 도구로 생성한 artifact 디렉터리만 `/artifacts`에
읽기 전용으로 마운트하세요. MCP 프로세스는 stdio로 통신하고 Docker socket을
마운트하지 않습니다. 호스트 파일 권한에 따라 UID 65532가 파일을 읽지 못할
수 있습니다. 이 경우 설정의 `docker run` 인수에 `--user "$(id -u):$(id -g)"`를
추가하고 접근 가능한 artifact 디렉터리를 지정하세요.
