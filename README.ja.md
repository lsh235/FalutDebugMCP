# FaultDebug 日本語ガイド

[English](README.md) · [한국어](README.ko.md) · [简体中文](README.zh-CN.md) · **日本語**

## インストール前にレポートを体験

[対話型デモ](https://lsh235.github.io/FalutDebugMCP/) · [42 秒のデモ動画](https://lsh235.github.io/FalutDebugMCP/assets/demo.webm)

実際の合成テストで正常な注文、決済 SIGILL、在庫タイムアウト、native C SIGSEGV を確認できます。
Linux x86_64 のローカル Docker Engine と Compose があれば、clone 後に実行します：

~~~~sh
./scripts/try-demo.sh
~~~~

検証済みのビルド済みイメージで 8 個の独立サービスを実行し、レポートを生成します。
ホスト側の Python・Clang・CMake は不要です。http://127.0.0.1:18870/index.html を開き、Ctrl+C でレポートサーバーを停止できます。
スクリプトはローカル Docker socket で自身のテストコンテナを管理します。例の記録は C++ 境界イベントであり、Python スタック全体ではありません。
開発 snapshot であり、安定版ではありません。[必要環境](docs/showcase/README.md) · [ケーススタディ](docs/case-studies/payment-crash.md)

FaultDebug は C/C++ プログラムの実行時障害証拠をローカルで記録・検査する
ツールです。軽量な C11 ランタイムが有界メモリに関数の entry/exit イベントを
記録し、対象プロセス終了後に Python ランチャーが共有メモリ trace を回収・検証
します。対応する致命的シグナルや部分終了では `.fault` ファイルを生成します。
Clang/CMake 連携、CLI、読み取り専用 MCP 検査機能も含みます。

![FaultDebug の収集と検査フロー](docs/assets/faultdebug-overview.svg)

> 記録されなかったイベントは推測しません。overflow、不完全な trace、source
> provenance の不一致を明示します。

## プロジェクトの状態

現在の候補版は [`v1.2.0-rc.1`](https://github.com/lsh235/FalutDebugMCP/releases/tag/v1.2.0-rc.1)です。
core と gRPC のローカルおよび GitHub Actions のゲートは通過していますが、
独立した最終レビューは未実施です。30 分間の soak trace は 344,793 件のイベント
欠落と 9,276 件の不安定な snapshot を記録しており、不完全です。正式な
`v1.2.0` 安定版ではありません。

## クイックスタート

サポート対象環境は Ubuntu 24.04 x86_64、Python 3.12、Clang 18、CMake 3.20
以上、Ninja です。

```sh
git clone https://github.com/lsh235/FalutDebugMCP.git
cd FalutDebugMCP
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

環境を診断して正常系の fixture を実行します。

```sh
.venv/bin/fault-debug doctor
.venv/bin/fault-debug run --artifact-dir artifacts -- build/test/fd_c_chain 16
```

正常終了では既定で `.fault` ファイルを作りません。SIGSEGV の収集を試すには
次を実行します。

```sh
.venv/bin/fault-debug run --artifact-dir artifacts -- build/test/fd_signals 11
```

`.venv/bin/fault-debug inspect artifacts/fault-<pid>.fault` で artifact を確認
できます。source に基づく検査には、ビルド時に生成した検証済み source bundle
が必要です。

## 証拠の読み方

- **観測済み:** artifact に実際に保存された committed runtime record。
- **静的候補:** source や compile database から得た可能性であり、実行の証明では
  ありません。
- **未解決:** 欠落、曖昧さ、データ損失、検証不一致などで確定できない証拠。

親 PID、関数名、trace ID、時刻だけではプロセス間の因果関係を証明できません。
`.fault` と source bundle には機密コードやパスが含まれることがあるため、公開
issue に添付する前に内容を確認・匿名化してください。

## 関連ドキュメント

- [English の全機能・コマンド説明](README.md)
- [v1.2 計画と受け入れ基準](docs/next-version-v1.2.md)
- [ビルドとテスト](test/README.md)
- [コントリビューション](CONTRIBUTING.md) · [セキュリティ方針](SECURITY.md)
