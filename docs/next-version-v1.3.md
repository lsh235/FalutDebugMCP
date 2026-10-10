# v1.3 후보 실행 계획: 컨테이너 서비스 장애 보고서

작성일: **2026-10-11, Asia/Seoul**.
기준 revision: `70d6771386a97778bdad167c6508827d6c1d56b4`.
상태: **IN PROGRESS — P0-01 완료, P0-02 로컬·hosted gate PASS, 최종 수락 pending**.
v1.3은 제안 버전명이며, 현재 패키지는 `1.2.0rc1`이다.

## 1. 목표와 출발 조건

사용자가 HTTP 주문 실패를 선택하면 **어느 프로세스 세대의 어느 호출이 실패했는지,
receiver는 어디까지 처리했는지, 어떤 원인 증거가 있는지** 문서와 flow에서 확인할 수
있게 한다. 증거가 없으면 미확인으로 표시한다. 실패를 주입한 설정에서 원인을
자동 정답으로 복사하지 않는다.

Docker의 기존 8/16프로세스 검증을 보존하고, 네트워크 장애·재시작·N=32·로컬
Kubernetes 검증을 추가하는 것이 v1.3의 필수 범위다. 표준 trace 연결, 재사용 가능한
보고서, bounded MCP 조회가 이를 지원한다.

먼저 v1.2 정식 수락을 별도로 마무리한다. RC 이후 Make, fault/service report,
Docker lab 변경이 추가되었으므로 이전 RC의 PASS를 현재 소스의 정식 수락으로
사용하지 않는다. 아래 P0 정확성 문제가 재현되면 stable 승격 전에 해결하거나
지원 제한을 수락 문서에 명시한다. 결과를 숨긴 채 다음 minor 버전으로 넘기지 않는다.

## 2. 유지할 증거 계약

| 증거 | 보고서에서 허용하는 주장 | 금지할 확대 해석 |
| --- | --- | --- |
| native function/crash capture | 검증된 binary와 bundle이 맞는 PC/함수/보존된 이벤트 | C++ 경계 함수만 계측해 Python/Java/Go 전체 스택이라고 표현 |
| native numeric RPC | session + trace hi/lo + rpc + endpoint identity가 일치하는 관측 연결 | 공통 trace/PID/시간 유사성만으로 edge 생성 |
| application log/OTel span | 별도 application 관측과 native 관계의 corroboration | 앱 설명/feature flag를 native 원인 또는 인증된 작성자 증거로 승격 |
| orchestrator/proxy 기록 | 신원이 일치하는 종료/재시작/적용 상태 및 관측 증상 | exit 137만으로 OOM 확정, 설정 요청만으로 실제 fault 적용 확정 |
| derived relation/hypothesis | 계산 근거, 입력 evidence ID, 불확실성을 함께 공개 | static reach 또는 LLM 추론을 실제 장애 전파로 표현 |
| incomplete/missing capture | 캡처 존재·보존 범위·누락 사유와 unresolved | RPC가 완전하다는 이유로 native 함수 기록도 완전하다고 표현 |

기존 capability의 `observed/derived/static_candidates/unresolved/hypotheses`는
유지한다. 세부 출처는 additive `evidence_origin` 같은 필드로 구분하는 안을 먼저
검토한다. 기존 reader의 동작을 바꿔야 한다면 별도 schema/version과 변환 규칙을
제안하고 호환 gate를 통과한다. numeric runtime ABI 변경은 기본 방안이 아니다.

## 3. 작업 목록과 수락 기준

아래 담당은 작업 책임 영역이며 실제 인원 배정이 아니다. P0-01의 구현과 로컬 검증은
[P0 결과](v1.3-p0-01.md)에 기록했다. P0-02는 로컬·hosted gate PASS, 최종 수락 pending이며
그 밖의 항목은 PLANNED다.
P0-01의 `test/thread_generation_contract.py`와 native fixture는 구현되었다.
나머지 계획에서 “신규”를 붙인 항목은 아직 존재하지 않는다.

| ID / 우선순위 | 담당·수정 대상 | 의존성 | 완료 기준 |
| --- | --- | --- | --- |
| P0-01 / 최우선 | runtime/decoder: `runtime/faultdebug_runtime.c`, `faultdebug/format.py`, `include/faultdebug/format.h`(필요 시), 기존 `test/programs/thread_slot_reuse/main.c`, 신규 `test/thread_generation_contract.py` | 없음 | 새 소스로 slot 재사용 최소 재현. 용량 1/8/4096, 80회/10,000회 순차 thread 생성, wrap·동시 snapshot·crash 시점 비교. 마지막 세대의 실제 raw 기록과 decoder 일치. retired generation의 보존/손실을 명시하고 false complete=0. ABI 변경이 필요하면 M1 전에 결정. |
| P0-02 / 최우선 | release/검증: `test/v12_release_gate.py`, 기존 report/RPC/Make 테스트, `.github/workflows/v12-release-gate.yml`, `.github/workflows/shopping-fault-lab.yml`, 수락 문서 | P0-01 판단 | 최종 후보 revision의 core/gRPC·installed wheel/MCP·소스 archive native build·쇼핑몰 hosted gate를 각각 검증. required row에 FAIL/NOT RUN이면 stable 수락 보류. 최종 검토와 알려진 제한을 문서화. |
| P1-01 / 높음 | context/report: `test/shop/service.py`, `faultdebug/service_report.py`, `faultdebug/rpc.py`, 신규 HTTP context adapter와 contract 테스트 | M0, P0-01 | W3C traceparent validation/propagation. 128비트 trace 전체 보존, legacy hi=0 입력 수락. client/server span과 shared rpc_id 매핑 명시. hi만 다른 ID, 중복/zero/잘못된 헤더, retry/attempt, sampling 누락에서 false pair=0. |
| P1-02 / 높음 | 신원/시간: `faultdebug/session.py`, `faultdebug/aggregate.py`, `faultdebug/rpc.py`, lab manifest, 문서 | M0 | 실행마다 process identity/generation, host boot/clock domain, container/Pod UID 출처 기록. 같은 PID·서비스 이름의 재시작이 합쳐지지 않음. 다른 domain의 절대 monotonic deadline을 비교하지 않음. clock 정보가 없으면 duration/전역 순서는 미확인. |
| P1-03 / 높음 | Docker lab: `test/shop/run.py`, `test/shop/service.py`, 신규 proxy 설정/driver 및 application-event 테스트 | P1-01/02 | upstream/downstream 지연·timeout·TCP reset과 복구 대조군. injection 설정과 관측 입력 분리. receiver 처리 후 응답 유실을 caller 실패와 구분. source log가 없어도 증상을 남기고 원인은 unresolved. |
| P1-04 / 높음 | fixture 상태 oracle: 신규 `test/shop/ledger.py`와 테스트, `test/shop/service.py`, restart driver | P1-02/03 | fixture용 작은 SQLite durable ledger에 order/idempotency 상태 기록. restart 후 동일 주문 재시도에서 실제 durable debit/예약 mutation 횟수 1. 배송/보상 실패의 미완료 상태를 명시. 전역 checkout lock을 좁혀 실제 in-flight checkout 2개 이상을 관측. 실 결제 provider 보장은 범위 밖. |
| P2-01 / 높음 | report model/조회: `faultdebug/service_report.py`, `faultdebug/cli.py`, `faultdebug/mcp_server.py`, `faultdebug/capabilities.py`, 신규 bounded 조회 테스트 | P1 계약 | identity+trace hi/lo+rpc+attempt 색인, 총 입력 상한, paginated read-only service flow 조회. native/application/orchestrator 출처와 로컬 evidence hash 공개. 잘못된 신원·세대·trace·status·bundle 및 누락 입력에서 오탐 원인/edge=0. 기존 MCP 도구 호환. |
| P2-02 / 높음 | viewer/docs: `faultdebug/service_report_view.py`, 기존 `test/service_report_test.py`, 신규 topology fixture/브라우저 검증 | P2-01 | 임의 역할과 fan-out/fan-in/retry/보상 경로, 프로세스 세대 필터. 실제 32 participants를 집계 없이 선택 가능. 한국어/영어, 키보드 탐색, offline HTML/JSON/MD, 인쇄 검증. 보이는 edge의 evidence ID를 조회할 수 있음. |
| P3-01 / 높음 | 로컬 Kubernetes: 신규 `test/shop/k8s/` manifest/driver, collector 실행 profile/export 계약 | P1-02/04, P2-01 | 고정 kind/node-image에서 N=8/16 서비스 및 native collector 확인. container restart와 Pod replacement 구분. SIGILL은 native bundle 증거, SIGKILL/관측된 OOM은 orchestrator 증거로 표시. Pod 삭제 뒤 capture 보존/누락을 확인하고 복구 대조군 통과. |
| P3-02 / 조건부 | 외부 연동: 신규 `test/external/otel_demo/` overlay/driver/평가 문서 | P1, P2, 자원 spike | pinned OTel Demo C++ 서비스 한 곳의 native capture와 인접 spans 비교. 정상/업무 실패/native crash를 비교하고 최소 한 crash의 PC→Build ID→bundle source를 확인. 비계측 언어는 application 증거로 표시. 자원 초과/계측 불가이면 이유와 NOT RUN을 남기고 필수 profile과 분리. |
| P4-01 / 높음 | QA/CI: 신규 v1.3 gate runner, scale/soak 계획, 기존 workflow, release 자료 | 필수 P0–P3-01 | 아래 matrix의 local/hosted 결과, false edge/원인 negative oracle, 비용/latency/loss, wheel/sdist consumer, 마지막 revision의 모든 필수 row 검증. RC 공개 후 별도 최종 수락. |

P1-04 ledger는 테스트 서비스의 durable mutation 증거를 제공하기 위한 최소 구성이다.
분산 transaction이나 production exactly-once 보장을 추가하는 과제가 아니다.
알림의 실제 큐/전달 재시도는 별도 후속 과제로 두며 `deferred`를 delivery 성공으로
계산하지 않는다. 배송 실패 후 결제 완료라는 상태도 원인 보고서에 그대로 남긴다.

### thread generation 설계 결정: P0-01 완료

ABI v1의 layout은 유지한다. additive thread flag로 event_count/sequence는 현재 세대,
dropped_count는 slot lifetime임을 표시한다. 이전 세대의 부재는 별도 retirement flag,
sticky PARTIAL과 보고서 gap으로 공개한다. 따라서 counter를 초기화한 뒤 snapshot이
stable이어도 전체 기록을 complete로 표시하지 않는다. 과거 event 수와 TID는 추정하지
않는다. 18 native cases, 기존 reader 호환, core/gRPC와 Docker 회귀 결과는 P0 보고서에 있다.

### HTTP trace adapter에서 먼저 결정할 것

W3C client span ID는 outbound call의 context, server span ID는 receiver operation의
context다. 현재 numeric RPC의 shared rpc_id와 둘을 무조건 1:1 치환하지 않는다.
adapter가 `trace hi/lo + client span + server span + rpc_id + parent_rpc_id + attempt`
매핑을 별도 관측으로 보존하는 안을 검증한다. 전송 형식과 표준 헤더 충돌 규칙을
contract로 고정하고, native ABI에 HTTP payload/header 문자열을 넣지 않는다.

### Kubernetes 자료 보존과 clock 범위

M3는 동일 물리 호스트의 kind 검증이다. 최초 profile은 기존 launcher, app과 collector를
같은 컨테이너에서 실행해 memfd 전달 계약을 유지한다. 별도 sidecar를 쓴다면 export
역할부터 검증하며 다른 컨테이너의 memfd에 자동 접근할 수 있다고 가정하지 않는다.
실행별 collector와 bounded export로 자료를 로컬 분석에 전달한다.
Pod의 emptyDir와 종료 hook만으로 삭제 시 자료
보존을 보장하지 않는다. export 완료 manifest 또는 구체적 누락 사유가 필요하다.
일반 사용자를 위한 원격 agent/API 서비스는 이번 범위에 포함하지 않는다.

SIGKILL은 handler가 실행되지 않으므로 crash PC의 부재가 예상 결과다. OOM 원인에는
container terminated reason/cgroup 이벤트 같은 추가 자료가 필요하다. 마지막 capture,
in-flight RPC, 수집 시점/누락, 새 프로세스 신원을 각각 보여 준다.

다른 clock domain의 전역 정렬은 만들지 않는다. caller timeout과 receiver budget을
각자 로컬 시계로 측정한다. 응답 유실/늦은 처리의 업무 안전성은 durable idempotency,
명시적 취소·보상 상태로 검증한다. 외부 Demo/실제 다중 호스트는 관측 범위가 별도다.

## 4. 실행 순서와 산출물

| 단계 | 선행 조건 | 리뷰 가능한 결과 | 다음 단계 진입 조건 |
| --- | --- | --- | --- |
| M0: baseline와 v1.2 수락 | 현재 source/remote 확인 | P0-01 최소 재현, 수정 또는 지원 경계, 최종 후보 gate 보고서와 수락 기록 | P0 결과를 숨기지 않은 안정된 기준선. 정식 승격은 별도 release 작업. |
| M1: ID/시간/신원 계약 | M0 | trace adapter contract, schema/ABI 호환 비교, 충돌·restart negative tests | native/legacy reader 호환, false pair=0, clock domain 제한 명시 |
| M2: Docker chaos와 범용 보고서 | M1 | proxy·ledger driver, 일반 topology report, bounded MCP, N=8/16/32 결과 | 원인 입력 분리, durable 상태 oracle, 복구 대조군, UI/문서 검증 |
| M3: kind lifecycle/export | M2 | pinned manifests와 export 자료, restart/Pod 교체/SIGKILL/제한된 OOM 보고서 | 자료 보존 또는 명시적 누락, 새 generation 분리, 정상 복구 확인 |
| M3b: 외부 Demo 선택 평가 | M1/M2 및 spike | pinned overlay, 계측한 서비스/미계측 영역, CPU/RAM/원인 비교 | 별도 experimental 수락; 필수 profile 결과와 섞지 않음 |
| M4: RC와 최종 수락 | M0–M3 필수 완료 | current-revision build/CI/scale/soak/consumer, 알려진 제한, EN/KO 사용 가이드 | required FAIL=0, NOT RUN=0; 선택 profile의 NOT RUN은 명시 |

개발 주수는 M0 재현/ABI 판단과 M1/M3 spike 이후 산정한다. 외부 도구의 존재만으로
일정을 확정하지 않는다. P2 viewer와 model 변경, P1 ledger와 driver 변경은 같은
계약에 맞춰 순차 통합하고 마지막 변경 이후 관련 gate를 재검증한다.

## 5. 검증 matrix와 예상 결과

이 표는 **앞으로 실행할 기준과 현재 진행 상태**다. 새 P0 실행 결과는 P0 보고서,
이전 기준선은 리서치 문서의 표를 따른다.

| Profile | 고정 조건 | 반드시 확인할 결과 | 상태 |
| --- | --- | --- | --- |
| runtime-generation | threads=1/2/64, events=1/8/4096, 순차 재사용·wrap·동시 읽기 | raw oracle와 retained generation 일치, retired 손실 공개, false complete=0 | PASS: 선택한 18 native cases와 기존 live stress. 전체 Cartesian 조합은 아님 |
| Docker short | N=8/16/32, 기본 concurrency=4, N=32 clean은 우선 8주문 | 기존 6시나리오(정상 포함), participant 수와 실제 호출, 짧은 clean capture loss=0. crash는 missing end/incomplete 허용·표시 | PARTIAL: N=8 6종/N=16 2종 PASS, N=32 NOT RUN |
| Docker transport | 선택 링크의 directional delay/timeout/reset, applied/removed 상태 | caller/receiver 결과 분리, missing peer는 unresolved, 복구 후 정상 성공 | NOT RUN |
| restart + retry | receiver durable mutation 후 응답 유실, payment/checkout 각각 restart | 동일 order의 durable mutation 1회, 실제 retry/attempt·새 generation, 잔여 보상 실패 표시 | NOT RUN |
| missing/tampered evidence | 앱 설명 삭제, capture 삭제, hi만 변경, 세대 변경, checksum/bundle 오류, orphan span | 없는 원인/edge를 생성하지 않음. 손상 입력 reject 또는 문서화된 unresolved | NOT RUN |
| kind lifecycle | N=8/16, 단일 control plane부터, container restart/Pod 교체/SIGILL/SIGKILL | UID/container/generation 별 신원, 수집 보존/누락, crash PC와 종료 증거 종류 구분 | NOT RUN |
| kind OOM | 작은 전용 workload에서 낮은 memory limit, 실제 OOM 관측 필요 | terminated reason/cgroup 근거. 관측되지 않으면 NOT RUN; exit 137 단독은 OOM 확정 아님 | NOT RUN |
| shopping soak | N=16 1800초 반복 batch, 사전 고정 seed와 5분 fault window | 주문 oracle, 복구, thread/FD/RSS 추이, event drop/overflow/partial. 장시간 ring 손실은 공개하고 false complete/edge=0 | NOT RUN |
| scale/report | 동일 runner/image에서 N=8/16/32, 5회 clean 반복, 100,000 event 한계 입력 | 기간·p50/p95·RSS·보고서 시간/크기, input cap 초과 거부, dropout 원인 분리 | NOT RUN |
| UI/document | 8/16/32 역할 + fan-in/retry/restart, EN/KO, light/dark, print | 정상/실패/미확인 색과 출처, offline 요청 0, label 겹침·선택·keyboard·소스 표시 실제 브라우저 확인 | NOT RUN |
| package/compatibility | 소스 archive native build와 checkout 밖 wheel/CLI/MCP consumer | 기존 required tools, ABI/FDAR v1 읽기, 새 조회와 오류 응답, provenance/bundle 확인 | P0 local PASS; 새 service-flow MCP 조회는 NOT RUN |
| external OTel | 고정 Demo revision, C++ 한 서비스와 인접 spans | native/application 범위를 분리한 정상/오류/crash 보고서 | NOT RUN, 선택 |

N은 **application process 수**다. collector, init, proxy, DB 및 kind node 수를 따로
보고한다. 프로세스를 띄운 수와 실제 request에 참여한 수를 각각 집계한다.
고의 조기 실패로 도달하지 못한 서비스를 호출된 것으로 표시하지 않는다.

### 측정 예산과 수락 정책

- 기존 read limit 16MiB/file, 64 native captures, 100,000 application events를
  기준으로 총 입력 예산을 추가한다. **초기 설계 목표**는 64MiB 합계다. 이를 넘는
  run은 query/report shard와 전체 목록을 제공하거나 명확히 거부한다. 누락을 숨기지 않는다.
- **초기 성능 목표**는 고정 4-vCPU/8GiB runner에서 해당 예산 report 생성 10초 이내,
  analyzer peak RSS 512MiB 이내다. 미측정 목표이므로 M2 시작 전에 baseline과 gate
  측정법을 고정한다. 변경 시 결과를 본 뒤 맞추지 말고 이유와 새 기준을 기록한다.
- N=32 앱 memory limit의 합만 8GiB(32×256MiB)다. 실제 RSS는 별도 측정하며 host/CI
  여유가 부족하면 전용 scale profile을 사용한다. 환경 부족은 NOT RUN이고 PASS가 아니다.
- 1800초는 native 기존 soak와 동일 길이를 선택한 **새 shopping 검증 목표**다.
  기존 driver는 최대 100 requests/run이므로 새 반복 driver와 batch별 snapshot/export가
  필요하다. 현재 `run.py`에 존재하지 않는 soak 옵션을 사용 가능한 명령처럼 제시하지 않는다.
- false pair/원인은 독립 oracle의 참·거짓 fixture로 계산한다. clean short에서 drop=0,
  soak/고의 overflow에서 손실 정확히 표기. 모든 event 보존을 장시간의 필수 조건으로
  잘못 설정하지 않는다. unavailable 수치는 null/NOT RUN으로 남긴다.

## 6. 검증 입력과 CI 운영

각 run manifest에 revision, tool/image digest, OS/CPU/RAM, N/role/process generation,
clock domain, seed, 요청 수, concurrency, 설정한 fault window, 실제 적용/복구 관측,
artifact/source hash, oracle 결과와 실행 명령을 남긴다. report builder에는
fault 정의 파일을 전달하지 않고 관측 evidence만 전달한다. 실패 위치의 정답 파일은
검증 oracle에서만 사용한다.

PR 필수 gate는 빠른 decoder/ID/negative/report/consumer와 N=8 smoke로 제안한다.
N=16/32·1800초 soak·kind lifecycle은 manual/scheduled profile로 두되 RC 수락에는
필수 실행한다. OTel/Chaos Mesh는 선택 profile이다. 실행 중단/실패에서도 raw logs와
partial 자료를 업로드하며 workflow 이름, run URL, 실제 profile 결과를 분리한다.

새 profile은 지원 OS/toolchain을 확대하지 않는다. Python/Pydantic/MCP SDK 등
dependency 변경이 필요하면 고정 버전별 installed stdio consumer로 먼저 검증한다.
기존 numeric runtime ABI, FDAR, store, required MCP tools의 호환 회귀가 release gate다.

## 7. 구현을 시작할 때 수행할 순서

1. 현재 revision/dirty files와 최종 RC 이후 변경 목록을 고정하고 M0 acceptance manifest를 만든다.
2. P0-01 최소 재현을 기존 `fd_slot_reuse`로 작성하고 raw count/generation/publication oracle를
   확인한다. 정상 종료도 opt-in capture해야 한다. 재현한 뒤 ABI/보존 정책을 결정한다.
3. 수정된 기준 소스로 core/gRPC release gate와 쇼핑몰 hosted gate를 실행한다. 필수
   JSON row와 실제 캡처·oracle를 확인하고 v1.2 정식 수락 여부를 기록한다.
4. trace/신원/clock adapter contract를 먼저 고정하고 negative test를 만든 뒤 M2를 구현한다.
5. Toxiproxy와 ledger 상태 oracle를 갖춘 Docker 증거로 report/MCP를 검증하고 kind로 확장한다.

현재 존재하는 재검증 명령의 예시는 다음과 같다. **이 문서 작성 중 실행하지 않았다.**
새 checkout/venv, Clang 18과 필요한 gRPC 도구 준비가 선행 조건이다. 출력 경로는
기존 evidence와 겹치지 않게 실행마다 새로 선택한다.

```sh
.venv/bin/python test/v12_release_gate.py --profile core \
  --build-dir build-v13-baseline-core --install-prefix build-v13-baseline-core/install \
  --work-dir build-v13-baseline-core/release-work --output output/v13-baseline-core/report.json
.venv/bin/python test/v12_release_gate.py --profile grpc \
  --build-dir build-v13-baseline-grpc --install-prefix build-v13-baseline-grpc/install \
  --work-dir build-v13-baseline-grpc/release-work --output output/v13-baseline-grpc/report.json
.venv/bin/python test/service_report_test.py
.venv/bin/python test/fault_report_test.py
.venv/bin/python test/build_systems/test_compiledb_integration.py
```

신규 driver/adapter/MCP 도구는 아직 구현되지 않았으므로 사용 명령을 가정해서 배포하지
않는다. M0–M4 보고서에는 각 gate의 PASS/FAIL/NOT RUN, 로컬/hosted 구분, 근거 파일과
다음 남은 작업을 남긴다. 제품 구현·버전 변경·release 발행은 이 계획의 후속 작업이다.
