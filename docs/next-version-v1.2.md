# v1.2 개발 실행 계획

작성일: 2026-10-03 (Asia/Seoul). 기준 릴리스: **v1.1.0**, Git revision
`6659a3baa7d84c9025f6d66dfdd421c53334c033`.

다음 버전의 목표는 **수집한 증거를 정확하게 복호화하고, 실제 도입 환경에서
설치·성능·재현성을 검증할 수 있게 만드는 것**이다. 현재 버전을 기준으로
분석과 새 빌드 검증을 수행했고, 첫 구현 작업을 바로 시작할 수 있도록 범위와
수락 기준을 정했다. 이 문서의 작업은 구현 완료를 뜻하지 않는다.

## 1. 출발점과 우선순위

현재 Python/CMake 패키지와 Git 태그는 v1.1.0이다. launcher, native recorder,
immutable source bundle, 읽기 전용 MCP, local agent, SQLite evidence store,
incident 조회, doctor, benchmark 및 선택 계측 기능이 이미 존재한다.
v0.9 gRPC fixture에는 streaming·retry·deadline 시나리오도 있다. 이를 새 기능으로
다시 계획하지 않는다. 실제 현재 검증 결과는 [기준선 보고서](v1.2-baseline.md)를 따른다.

가장 먼저 해결할 문제는 **작은 이벤트 용량에서 발생하는 조용한 기록 누락**이다.
실제 native 실행에서 `FAULTDEBUG_CONFIG=events=8,threads=2`로 설정하면 슬롯 1의
ENTER/EXIT 기록이 메모리에 존재하지만 Python 결과에서는 사라진다.
launcher 결과도 `collector.ok=true`, `partial=false`, `complete=true`였다.
기본 용량 4096에서는 같은 실행의 두 슬롯을 모두 읽었다.

| 근거 | 현재 확인한 내용 | 계획에 미치는 영향 |
| --- | --- | --- |
| `faultdebug/format.py:136-146`, `include/faultdebug/format.h:95-97`, `docs/format.md:29-36` | 디코더는 논리 용량으로 스레드 간격을 계산하지만 native ABI의 물리 링은 고정 크기다. 실행으로 누락 재현. | P1-01 최우선 |
| `test/doctor_benchmark.py:48-54,82-85`, `faultdebug/doctor.py:75-83` | 도구가 없는 상황의 `NOT RUN` 계약과 테스트의 `FAIL` 기대값이 충돌한다. 현재 테스트 실패. | P1-02 |
| `faultdebug/doctor.py:34-54,144-152`, `scripts/faultdebug-cc:7-9` | doctor의 compiler fallback과 wrapper 실행 선택이 다르다. runtime 확인은 파일 존재 중심이다. | P1-02 |
| `faultdebug/collector.py`, `faultdebug/agent.py`, `faultdebug/format.py` | readiness 대기 hang, idle connection의 head-of-line blocking, publication 검사와 event decode 사이 혼합 기록을 재현했다. | **P2-01 DONE** — bounded deadline, idle-connection timeout, event/RPC/crash snapshot 검증 및 native writer stress. 상세: [P2-01 결과](v1.2-p2-01.md) |
| `test/negative_cases.py:20-28`, `test/run_tests.py:127-132` | malformed 사례가 같은 디렉터리에 누적된다. soak는 일반 검사와 다른 종료 상태 해석을 쓴다. | P1-03 |
| `test/external/cpp-call-benchmark-v1.1.md:31,44`, `test/external/libuv-v1.48.0-evaluation.md:33-35` | 기준선 보고서에는 정상 종료 loss와 libuv 독립 비교가 없었다. P2-02/P2-03에서 측정·비교를 완료했다. | [P2-02 결과](v1.2-p2-02.md), [P2-03 결과](v1.2-p2-03.md) |
| `.github/workflows/ci.yml:19-48`, `test/v10_validation.py:425-446` | CI는 전체 설치/MCP/CTest gate를 실행하지 않는다. 통합 gate의 `NOT RUN`은 종료 코드 0일 수 있다. | P3-01 |

소스 행 번호는 위 revision 기준이며 수정 후에는 갱신한다. codebase-memory 스킬을
읽었지만 graph MCP 도구가 현재 세션에 제공되지 않아 graph/index coverage는
`NOT RUN`이다. 위 구조 판단은 지정한 파일의 직접 확인과 실행 증거에 근거한다.

## 2. 범위와 호환성

v1.2의 필수 범위는 디코더 정확성, 검증 도구의 올바른 상태 판정, 수집 대기 경계,
동시 snapshot의 증거 제한 검증, 측정별 loss 정보, 외부 재현성, 전체 CI gate다.
동시 snapshot에서 실제 결함이 재현되면 P2-01 안에서 수정한다.
정상 종료 telemetry는 명시적으로 활성화한 측정에만 제공하고, 기존 정상 종료가
fault artifact를 만들지 않는 계약을 유지한다.

호환성 기준은 다음과 같다.

- Python 3.12, Ubuntu 24.04 x86_64, Clang 18을 지원 기준으로 유지한다.
- ABI v1의 native 크기/오프셋과 기존 `.fault`·bundle 읽기 계약을 유지한다.
- SQLite schema v2와 v0.8/v0.9 조회·migration 계약을 회귀 검증한다.
- observed, derived, static-candidate, unresolved, hypothesis를 분리한다.
- 공유 session/trace ID, 함수 이름 또는 현재 worktree를 인과관계·실행·소스 일치의
  증거로 사용하지 않는다. 실제 손실·부분 수집·미측정 값은 명시한다.
- 새 JSON 필드는 additive하게 제공하고, 새 계약에는 명시적 schema/version을 둔다.

동적 모듈 load/unload 추적, 자동 gRPC interceptor, 원격·다중 호스트 수집,
주기적 수집, 별도 시각화 UI는 후속 계획으로 분리한다. 현재 모듈 표는 startup
시점의 `dl_iterate_phdr` 기록이다(`runtime/faultdebug_runtime.c:274`). 동적 모듈은
세대·주소 재사용 계약이, 자동 RPC는 취소·예외·terminal status 계약이 먼저 필요하다.

## 3. 작업 목록과 소유권

`READY`는 구현 착수 가능, `WAITING`은 선행 작업 필요, `DONE`은 해당 범위의 증거가
남았다는 뜻이다. 실행 결과인 `PASS/FAIL/NOT RUN`과 구분한다.

| ID / 우선순위 | 산출물·담당 역할 | 주 소유 파일 | 의존성 | 수락 기준 | 시작 상태 |
| --- | --- | --- | --- | --- | --- |
| P0 / 기준선 | 분석·통합 담당: 현 상태, 새 빌드, 실행 결과, 계획 | 이 문서, `docs/v1.2-baseline.md`, `ROADMAP.md` | 없음 | 실제 실행과 이전 릴리스 기록을 분리하고 실패와 미실행을 보존 | DONE: 분석·기준선 완료, 릴리스 수락 아님 |
| P1-01 / 최우선 | decoder 담당: 고정 물리 링 간격과 bounds 수정 | `faultdebug/format.py`, `test/abi_decoder_contract.py`, `test/decoder_capacity.py`, `test/CMakeLists.txt` | P0 | 실제 두 스레드의 독립 원시 기록과 결과가 일치. 용량 1·8·4096, wrap·slot reuse·truncated mapping 검증. native sizeof/offsetof 및 기본 용량 회귀 통과 | **DONE** — raw 슬롯 비교 3용량, ABI/truncated CTest, 통합 7/7 + CTest 11/11, acceptance 516/516 + oracle PASS. 상세: [P1-01 구현 및 검증](v1.2-p1-01.md) |
| P1-02 / 높음 | tooling 담당: doctor 상태·compiler/runtime 진단 계약 | `faultdebug/doctor.py`, `test/doctor_benchmark.py`, `test/CMakeLists.txt` | P0 | compiler 미가용은 `NOT RUN`/exit 2, 필수 package 누락은 `FAIL`/exit 1. 명시한 잘못된 compiler를 다른 fallback의 PASS로 숨기지 않음. 실제 wrapper와 compiler 선택 일치. 빈/잘못된 runtime 파일을 사용 가능하다고 판정하지 않음 | **DONE** — configured/default C/C++ wrapper parity, runtime load/hook probe, missing-tool/package exit contract, native launcher smoke; CTest 12/12. 상세: [P1-02 구현 및 검증](v1.2-p1-02.md) |
| P1-03 / 높음 | validation 담당: 독립 negative·soak·MCP 검증의 신뢰성 | `test/negative_cases.py`, `test/run_tests.py`, `test/v10_validation.py`, `test/v09_validation.py`, `test/grpc_v09_scenarios.py`, runner contract tests | P0 | 각 malformed 사례를 독립 검사하고 정상 대조군 수락. JSON target signal로 종료 판정. MCP initialize→tools/list→tools/call 실제 응답 검증. `NOT RUN`을 PASS로 바꾸지 않음. 환경/프로토콜 실패 이유와 raw logs 보존 | **DONE** — malformed 4종 및 정상 대조군, launcher 누락 NOT RUN/exit 2, 500 signal 실행, actual MCP/gRPC, 통합 7/7, CTest 15/15. 1800초 soak는 별도 릴리스 gate로 NOT RUN. 상세: [P1-03 구현 및 검증](v1.2-p1-03.md) |
| P2-01 / 높음 | collector/agent 담당: bounded 대기·snapshot 계약 | `faultdebug/collector.py`, `faultdebug/agent.py`, `faultdebug/format.py`, agent/collector 테스트·문서 | P1-01. `format.py` 변경은 decoder 담당과 순차 통합 | readiness 미전송·요청 없이 연결 유지에도 선언한 deadline 안에 종료/응답. 정상 후속 요청과 서버 종료 성공, FD/process 누수 없음. 동시 wrap·slot reuse·RPC writer stress에서 불안정 기록은 partial/unresolved로 보존하고 잘못된 trusted 결과 없음 | **DONE** — 미전송 readiness와 idle socket hang 재현·수정. synthetic race contract, live native event/RPC writer stress, agent integration, 전체 CTest 18/18. 상세: [P2-01 결과](v1.2-p2-01.md) |
| P2-02 / 보통 | performance 담당: 호출별 정상 종료 telemetry·workload 측정 | `faultdebug/benchmark.py`, `faultdebug/run.py`의 측정 전용 opt-in 수집, `test/external/cpp_call_benchmark_v1_1.py`, benchmark docs/tests | P1-01, P1-02; collector 연계 변경은 P2-01 담당과 순차 통합 | 각 측정의 run/target/pair와 loss·overflow·partial 연결. process 시간과 workload 시간 분리. 독립 operation/checksum 검증. 고의 overflow에 loss 표시. 미가용 값은 `NOT RUN` | **DONE** — schema 2의 run/sample/artifact 식별자, opt-in 정상 종료 artifact, 독립 checksum, clean·overflow matrix 모두 검증. 상세: [P2-02 결과](v1.2-p2-02.md) |
| P2-03 / 보통 | external 담당: portable libuv 재현·성능·실제 stdio 평가 | `test/external/libuv_v1_48_0.py`, `test/external/compare_libuv_runs.py`, external docs | P1-03, P2-02 | pinned libuv `e9f29cb984231524e3931aa0ae2c5dae1a32884e`의 별도 두 실행 비교. source/Build-ID/hash·signal·진단 의미 비교. PID/ASLR/시각/측정 변동은 사전 선언한 규칙 적용. 자료 archive/hash 검증. 외부 artifact로 필수 MCP 도구의 실제 stdio 성공·오류 경로 검사 | **DONE** — clean snapshot의 독립 평가 2회, normalized debug-prefix reproducibility, semantic comparator 12/12, evidence tar/hash, MCP stdio 다섯 성공 도구와 path-error 검증. 상세: [P2-03 결과](v1.2-p2-03.md) |
| P3-01 / 높음 | CI/package 담당: 전체 gate·installed wheel 소비자 | `.github/workflows/ci.yml`, 신규 scheduled/manual gate, release runner, `docs/clang18-ci.md` | P1 작업 안정화; P2 결과 연결 | provenance ON 빌드, named CTest, installed C/C++와 checkout 없이 설치한 wheel CLI/MCP, doctor/tooling/호환성 실행. 필수 row의 FAIL·NOT RUN은 release 실패. 실패 시에도 reports 업로드 | **IN PROGRESS** — 최신 소스의 동일한 195-file provenance snapshot으로 로컬 core 20/20 및 gRPC 21/21 CTest profile PASS; 설치 wheel 소비자도 양쪽 PASS. Hosted GitHub Actions 실행·artifact 업로드는 **NOT RUN**. 상세 및 raw report: [P3-01 결과](v1.2-p3-01.md) |
| P4 / 릴리스 | 통합 담당 + 독립 read-only reviewer: 최종 검증·버전 정합 | 버전 파일, `CHANGELOG.md`, `ROADMAP.md`, release evidence | 모든 필수 작업 | 아래 릴리스 gate 충족, 독립 감사 PASS, source/report/docs 일치 | WAITING |

P1-02, P1-03은 소유 파일을 나누어 병렬 진행할 수 있다. 이후 decoder와
collector 변경을 통합한 뒤 성능·외부 평가를 진행한다. CI 뼈대는 미리 만들 수 있지만
수락은 실제 통합 결과로 판단한다. 구현자는 다른 작업자의 변경을 되돌리지 않는다.
독립 reviewer는 구현 파일을 편집하지 않는다.

## 4. 단계별 진행과 릴리스 완료 기준

1. **M1: 정확성 회복. DONE.** P1-01의 작은 용량 누락을 고쳤고 P1-02 doctor/runtime,
   P1-03 negative/MCP/runner 계약 검증도 통과했다. 새 성능 수치는 아직 채택하지 않았다.
2. **M2: 수집과 측정 신뢰성. DONE.** P2-01 bounded collection/live snapshot
   consistency와 P2-02 정상 종료 telemetry, 호출별 결과·loss 연결을 검증했다.
3. **M3: 다른 환경에서 재현. IN PROGRESS.** P2-03의 clean source snapshot + pinned
   libuv 독립 비교와 stdio 경로, P3-01 core/grpc release profiles와 installed-wheel
   gate는 로컬에서 완료했다. 두 profile의 195-file provenance manifest가
   동일한지 raw source snapshot으로 대조한다. GitHub-hosted workflow 실행과
   Actions artifact 확인은 **NOT RUN**이다.
4. **M4: v1.2 수락.** 최종 revision에서 gate를 실행하고 독립 감사를 받는다.

P3 release runner는 실행 전에 필수/선택 **하위 gate 목록**을 고정한다.
core profile은 gRPC 빌드를 끄고 설치·MCP·ABI·collector·store·tooling 등 모든 core
하위 gate를 필수로 둔다. gRPC profile은 선택 의존성을 설치하고 streaming·retry·
workers·deadline 및 기존 unary 회귀까지 필수로 둔다. gRPC가 없는 core profile에서
선택 시나리오의 `NOT RUN`은 별도로 남긴다.
기존 v0.9/v1.0 runner는 선택 항목의 `NOT RUN`을 상위 상태로 전파하므로, 원본
상위 상태·하위 row를 보존하고 사전 지정한 필수 하위 row로 `required_gate_status`를
계산한다. 상위 회귀 전체를 선택 항목으로 취급하거나 raw `NOT RUN`을 `PASS`로
바꾸지 않는다. 필수 row 누락·FAIL·NOT RUN, 또는 실행한 선택 row의 FAIL은
수락을 보류한다. gRPC 지원을 포함한 v1.2 릴리스에는 gRPC profile도 통과해야 한다.

외부 stdio 평가는 `open_fault`, `get_thread_trace`, `resolve_addresses`,
`get_function_source`, `get_call_relations`를 최소 검사 대상으로 한다.

성능 측정은 다음 프로토콜을 출발점으로 사용한다. CPU 호출 workload는
1·8·32 workers, worker당 500 iterations를 별도 사례로 기록하고,
1 worker × 5000 iterations는 고의 overflow 사례로 분리한다.
각 사례의 operation 수와 checksum 기대값은 fixture 정의에서 독립적으로 계산한다.
baseline/instrumented는 같은 최적화·workload·launcher 조건으로 실행하며,
2 warmups와 7 alternating measurement pairs의 원자료를 보존한다.
process 시간과 workload 시간을 각각 보고하고 작은 표본의 tail percentile을
일반적인 성능 보장으로 사용하지 않는다. libuv는 기존 fatal-signal driver와
성능용 정상 종료 workload를 나누고, 후자의 작업량·계측 범위를 실행 전에 명시한다.

필수 릴리스 gate:

- native ABI probe와 capacity 회귀, 필수 named CTest 전체, installed C/C++ consumer,
  실제 MCP stdio, source citation/hash, store migration/quarantine, doctor·benchmark 계약.
- signal 5종 및 slot reuse·wrap·stack exhaustion 등의 기존 acceptance.
- 수정된 runner로 **한 프로세스 1800초 soak**: 실제 target 종료 신호, trace oracle,
  recorder 예산과 장시간 RSS/FD 기록. 현재 source에서 **PASS 24/24**. fidelity oracle
  10개 artifact PASS, RSS/FD 30개 연속 표본, mapping 12,768,064/33,554,432 bytes.
  단, soak artifact는 344,793 dropped events와 9,276 unstable snapshot records로
  `trace.complete=false`; loss/partial을 보존한 상태에서 구조적 oracle가 통과했다.
  상세: [P3-01 soak evidence](v1.2-p3-01.md).
- 선언한 workload matrix의 baseline/instrumented 측정과 호출별 loss 증거,
  libuv 독립 두 실행의 의미 비교. 속도·overhead 기준은 측정 전에 정한다.
  기준을 정하지 않은 timing은 관측 결과이지 성능 합격 판정이 아니다.
- 필수 row는 모두 `PASS`. 도구·네트워크·소켓 제약에 따른 `NOT RUN`이 있으면 필수
  수락은 보류한다. 선택 gRPC/다른 플랫폼의 미실행은 별도 표기하며, gRPC 포함 빌드에서는
  streaming·retry·workers·deadline 시나리오를 실행한다.
- package wheel/sdist 및 checkout 없는 소비자 검증, 문서·보고서·배포 버전 일치,
  구현자와 분리한 감사 `PASS`.

작업 중 `1.1.0` 릴리스 번호는 유지한다. 기능/검증 완료 뒤 `pyproject.toml`,
`CMakeLists.txt`, `faultdebug/__init__.py`, gate의 고정 버전(`test/v10_validation.py`),
capabilities 및 관련 문서/테스트의 실제 버전 사용을 함께 점검한다.
새 릴리스 표기는 수락 단계에서 정합성을 검증한다.

## 5. 다음 구현 작업

P1-01/02/03과 P2-01/02/03은 완료했고 M1과 M2는 닫았다. wrapped-ring event ordering
수정 이후 CTest, 517회 acceptance, 1800초 soak가 통과했다. P3-01의 전체 gate와
installed-wheel 소비자는 동일 provenance snapshot의 로컬 core/grpc profiles에서 통과했다. M3는 hosted Actions
실행 및 report artifact 확인이 남아 있고, P4 독립 read-only audit도 남았다.
P2-03 pinned libuv 독립 비교와 MCP stdio evidence는
[구현 결과](v1.2-p2-03.md)에 기록했다. P2-01
재현·수정·stress 증거는 [구현 결과](v1.2-p2-01.md)에, P2-02 측정과 호출별
loss 증거는 [구현 결과](v1.2-p2-02.md)에, P1-03 상세 판정과 raw report 경로는
[구현 결과](v1.2-p1-03.md)에 기록했다. 1800초 soak는 이번 작업에 포함하지 않았고
최종 release gate에서 새 revision으로 실행한다.

P1-02의 초기 handoff는 완료 기록으로 보존한다:

> v1.2 계획의 P1-02를 구현한다. doctor의 configured/fallback compiler 선택과 실제
> wrapper 사용 결과를 일치시키고 runtime file existence를 runtime usability로 오인하지
> 않도록 검증 계약을 추가한다. missing tool은 NOT RUN/exit 2, missing package는
> FAIL/exit 1로 구분한다. 잘못된 configured compiler가 사용하지 않는 정상 fallback을
> 보고하여 PASS 되지 않도록 한다. 고의로 누락되거나 잘못된 runtime fixture와 실제
> launcher readiness를 검증한다. P1-03과 파일 소유권을 조율하고, 다른 작업·output/을
> 보존하며 변경 파일·명령·PASS/FAIL/NOT RUN·남은 한계를 보고한다.

P2-01 이후 작업의 기준선 재실행 명령과 환경 전제는
[기준선 보고서](v1.2-baseline.md)에 있다. 새 gate는 기존 보고서가 `NOT RUN`으로
종료 코드 0을 반환할 수 있다는 점을 고려해 JSON row까지 판정해야 한다. P1-01 및
P1-02의 명령·raw report 경로는 [P1-01 결과](v1.2-p1-01.md),
[P1-02 결과](v1.2-p1-02.md), [P1-03 결과](v1.2-p1-03.md)에 기록했다. 이후 상태 갱신에도 실제 revision·raw report
경로·검증 범위를 함께 남긴다.
