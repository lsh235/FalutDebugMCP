# FaultDebug launch kit

Date: 2026-10-11, Asia/Seoul. These are publication drafts, not records of
delivery to external communities or of Trendshift ranking.

- Repository: https://github.com/lsh235/FalutDebugMCP
- Interactive examples: https://lsh235.github.io/FalutDebugMCP/
- Video: https://lsh235.github.io/FalutDebugMCP/assets/demo.webm
- Local fixture: ./scripts/try-demo.sh after cloning
- License: Apache-2.0
- Support: Linux x86_64 / local Docker Engine and Compose
- Product state: development snapshot; stable v1.2/v1.3 acceptance remains pending

## Show HN draft

Title: Show HN: FaultDebug — source-verified C/C++ crash and service-flow reports

I built FaultDebug to make a captured C/C++ failure easier to explain.
It records bounded native function events, verifies source against the captured
binary's Build ID and immutable bundle, and generates offline reports.
There is a local CLI and read-only MCP inspector.

The demo follows a checkout across eight independent Docker services. You can
inspect a successful order, a payment process SIGILL and an inventory timeout,
then open the native crash location and source. The shopping app is Python with
instrumented C++ boundaries; those events are not Python call stacks.

Dropped records, missing receiver ends and incomplete captures stay visible.
The online examples are recorded synthetic runs. The repository includes a
checksummed prebuilt image and a script to reproduce the fixture locally.

Demo: https://lsh235.github.io/FalutDebugMCP/
Code: https://github.com/lsh235/FalutDebugMCP

I would appreciate feedback on whether the report makes the failure and the
remaining uncertainty understandable, and where the setup is difficult.

Before posting, follow https://news.ycombinator.com/showhn.html.
Use the functional demo link, disclose that you are the author, and be available
to answer technical questions. No vote solicitation is part of this launch kit.

## Short English post

FaultDebug turns captured C/C++ crashes into source-verified execution-flow
reports. Try an eight-service checkout failure: follow the recorded calls,
open the native SIGILL location, and inspect the evidence gaps.
Apache-2.0, local CLI + read-only MCP.

Interactive examples: https://lsh235.github.io/FalutDebugMCP/
Repository: https://github.com/lsh235/FalutDebugMCP

## 한국어 소개

C/C++ 프로그램의 crash를 실제 실행 기록과 검증된 소스로 설명하는
FaultDebug를 만들었습니다. 8개 Docker 서비스의 쇼핑몰에서 정상 주문,
결제 프로세스 SIGILL, 재고 timeout을 비교할 수 있습니다.
서비스 사이의 실패 구간과 native crash 위치를 연결해 보고, 수집되지 않은
증거는 미확인으로 남깁니다. 쇼핑몰의 Python 스택 전체를 수집하는 도구는 아닙니다.

설치 없이 체험: https://lsh235.github.io/FalutDebugMCP/?lang=ko
코드: https://github.com/lsh235/FalutDebugMCP

## 中文介绍

FaultDebug 将捕获的 C/C++ crash 转换为经过源码验证的执行流程报告。
在线示例展示 8 个独立 Docker 服务中的正常订单、支付进程 SIGILL 和库存超时。
可以检查实际 RPC、native crash 位置以及缺失证据。购物应用使用 Python
和经过插桩的 C++ 边界模块，不代表采集了 Python 调用栈。

交互示例：https://lsh235.github.io/FalutDebugMCP/
代码：https://github.com/lsh235/FalutDebugMCP

## 日本語紹介

FaultDebug は、取得した C/C++ crash をソース検証付きの実行フロー
レポートに変換します。8 個の独立した Docker サービスで、正常な注文、
決済プロセスの SIGILL、在庫タイムアウトを比較できます。
観測された RPC と native crash を確認でき、欠けた証拠は明示します。
Python アプリと計測した C++ 境界モジュールの例であり、
Python の呼び出しスタック全体を取得するものではありません。

デモ：https://lsh235.github.io/FalutDebugMCP/
コード：https://github.com/lsh235/FalutDebugMCP

## Trendshift submission fields

- Repository URL: https://github.com/lsh235/FalutDebugMCP
- Website: https://lsh235.github.io/FalutDebugMCP/
- Description: Local C/C++ crash tracing with source-verified execution-flow reports, cross-service examples, and a read-only MCP inspector.
- Suggested categories, if available: developer tools, debugging, observability, MCP
- Submission entry: https://trendshift.io/ → Submit repository

Submission and ranking are separate. Registration status is not claimed by
this document. Account login and the site's current form must be checked when
the owner submits. No automated external announcement is sent.

## Measure response

Capture a baseline, then compare owner-visible snapshots weekly:

~~~~sh
python3 scripts/github-growth.py --output output/growth
~~~~

Record launch channel/date, GitHub visits, referrers, new stars and voluntary
installation-success feedback. GitHub traffic windows overlap; do not sum them.
Clones may be automated, and unique visitors are not equivalent to real adopters.
No visitor-to-star conversion rate is asserted from these aggregate metrics.

Initial practical target: 5–10 people independently open a report and report
whether they reproduced the local fixture. Star counts are observations,
not a promised outcome.
