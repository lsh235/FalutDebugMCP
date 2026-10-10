# FaultDebug 中文指南

[English](README.md) · [한국어](README.ko.md) · **简体中文** · [日本語](README.ja.md)

## 无需安装，先体验报告

[交互示例](https://lsh235.github.io/FaultDebugMCP/) · [42 秒演示](https://lsh235.github.io/FaultDebugMCP/assets/demo.webm)

查看实际合成测试的正常订单、支付 SIGILL、库存超时，以及 native C SIGSEGV。
在 Linux x86_64 的本地 Docker Engine 和 Compose 环境中，clone 后运行：

~~~~sh
./scripts/try-demo.sh
~~~~

脚本下载校验过的预构建镜像，运行 8 个独立服务并生成报告。
不需要在主机安装 Python、Clang 或 CMake。打开 http://127.0.0.1:18870/index.html；Ctrl+C 停止报告服务器。
脚本使用本地 Docker socket 管理自己的测试容器。购物示例记录的是 C++ 边界事件，不是 Python 调用栈。
这是开发 snapshot，不是稳定版。[环境要求](docs/showcase/README.md) · [案例](docs/case-studies/payment-crash.md)

FaultDebug 用于本地记录和检查 C/C++ 程序的运行时故障证据。轻量级 C11
运行时在有界内存中记录函数进入/退出事件；目标进程退出后，Python 启动器
收集并验证共享内存 trace，并在受支持的致命信号或部分终止情况下生成
`.fault` 文件。项目还提供 Clang/CMake 集成、CLI 和只读 MCP 检查器。

![FaultDebug 采集与检查流程](docs/assets/faultdebug-overview.svg)

> FaultDebug 不会猜测丢失的事件。overflow、不完整 trace 和 source
> provenance 不匹配都会明确显示。

## 项目状态

当前候选版本为 [`v1.2.0-rc.1`](https://github.com/lsh235/FaultDebugMCP/releases/tag/v1.2.0-rc.1)。
core 与 gRPC 的本地及 GitHub Actions gate 均已通过，但独立最终审查尚未完成。
30 分钟 soak trace 丢失了 344,793 个事件，并包含 9,276 条不稳定 snapshot
记录，因此 trace 不完整。该版本不是正式的 `v1.2.0` 稳定版。

## 快速开始

支持环境：Ubuntu 24.04 x86_64、Python 3.12、Clang 18、CMake 3.20 以上和
Ninja。

```sh
git clone https://github.com/lsh235/FaultDebugMCP.git
cd FaultDebugMCP
sudo apt-get update
sudo apt-get install clang-18 llvm-18-tools cmake ninja-build python3.12 python3.12-venv
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
cmake -S . -B build -G Ninja \
  -DCMAKE_C_COMPILER=clang-18 \
  -DCMAKE_CXX_COMPILER=clang++-18 \
  -DFAULTDEBUG_PYTHON_EXECUTABLE="$PWD/.venv/bin/python" \
  -DFAULTDEBUG_BUILD_TESTS=ON
cmake --build build --parallel 2
```

如果使用 [`uv`](https://docs.astral.sh/uv/)，可以用下面两条命令替换上述
Python 虚拟环境和安装步骤。apt 安装的 Clang、CMake 等 native 工具仍然需要。

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e .
```

检查环境并运行正常示例：

```sh
.venv/bin/fault-debug doctor
.venv/bin/fault-debug run --artifact-dir artifacts -- build/test/fd_c_chain 16
```

正常退出默认不会创建 `.fault` 文件。要测试 SIGSEGV 采集：

```sh
.venv/bin/fault-debug run --artifact-dir artifacts -- build/test/fd_signals 11
```

只读 Docker MCP 配置见[容器指南](docs/mcp-container.md)；编译和采集仍需在
具备 native 工具链的环境中执行。

使用 `.venv/bin/fault-debug inspect artifacts/fault-<pid>.fault` 查看 artifact。
基于 source 的检查需要构建时生成的已验证 source bundle。

## 如何理解结果

- **Observed（已观测）：** artifact 中实际保存的 committed runtime records。
- **Static candidates（静态候选）：** 从 source 或 compile database 得到的可能路径，
  不代表程序实际执行过。
- **Unresolved（未解决）：** 因缺失、歧义、丢失或校验失败而无法确认的证据。

仅凭父 PID、函数名、trace ID 或时间戳不能证明跨进程因果关系。`.fault`
文件和 source bundle 可能包含敏感代码与路径，公开 issue 前请先脱敏。

## 更多文档

- [English 完整文档和命令示例](README.md)
- [v1.2 开发计划与验收标准](docs/next-version-v1.2.md)
- [构建和测试](test/README.md)
- [贡献指南](CONTRIBUTING.md) · [安全政策](SECURITY.md)
