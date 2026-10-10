# 다음 버전 리서치: 분산 서비스 장애의 증거와 재현

조사일: **2026-10-11, Asia/Seoul**. 기준 소스:
`70d6771386a97778bdad167c6508827d6c1d56b4`.
로컬 HEAD와 GitHub `main`이 같은 것을 확인했다. 이 문서는 조사 결과이며,
후속 구현·외부 도구 설치·새 부하 시험의 완료 보고서가 아니다.

후속 구현 상태: G1의 native 재현과 수정, 로컬 core/gRPC·Docker 회귀 결과는
[P0-01 결과](v1.3-p0-01.md)에 있다. 아래 소스 표와 기준선은 조사 당시 revision에
고정된 기록으로 유지한다.

## 1. 제안

**v1.2 정식 수락을 마무리하고, v1.3 후보는 “컨테이너 장애를 증거로 설명하는
보고서”에 집중한다.** Docker 쇼핑몰을 정확성 회귀 테스트로 유지하고,
Toxiproxy의 네트워크 장애 → kind의 Kubernetes 생명주기 장애 → 외부
OpenTelemetry Demo 순서로 검증 범위를 넓히는 것이 적절하다.

이 순서는 아래 소스와 공식 자료를 바탕으로 한 프로젝트 적용 판단이다.
다른 프로젝트가 제공하는 기능을 FaultDebug가 이미 지원한다는 의미는 아니다.
실행 순서와 수락 기준은 [v1.3 실행 계획](next-version-v1.3.md)에 있다.

## 2. 현재 확인한 기준선

| 항목 | 현재 근거 | 상태와 해석 |
| --- | --- | --- |
| 공개 릴리스 | [v1.2.0-rc.1](https://github.com/lsh235/FalutDebugMCP/releases/tag/v1.2.0-rc.1), `gh release list` | 공개 prerelease. 정식 v1.2.0 수락은 [P3 보고서](v1.2-p3-01.md)에 pending으로 남아 있다. |
| 패키지 | [`pyproject.toml`](../pyproject.toml) | `1.2.0rc1`, Python 3.12, Clang 18 중심 지원 경로. |
| 현재 main CI | [실제 실행](https://github.com/lsh235/FalutDebugMCP/actions/runs/37891964276) | HEAD `70d6771`에서 success. 별도 쇼핑몰/Kubernetes 검증의 통과를 의미하지 않는다. |
| Docker 쇼핑몰 | [2026-10-09 검증 보고서](shopping-fault-lab.validation.md) | N=8 전체 6시나리오, N=16 정상/결제 거부. 기존 실행에서 69회 독립 주문, 823개 paired RPC, 80개 캡처. 이번 조사에서 전체 재실행하지 않았다. |
| 기록의 한계 | 같은 검증 보고서 | 79개 complete, 고의 결제 crash 1개 incomplete. Python 스택이 아니라 C++ 경계 함수의 기록. |
| 쇼핑몰 hosted workflow | [워크플로](../.github/workflows/shopping-fault-lab.yml), `gh run list --workflow shopping-fault-lab.yml` | 수동 실행 전용. 조사 시점 조회 결과 실행 기록 0건. 로컬 PASS와 구분한다. |
| 다음 검증 | 쇼핑몰 검증 문서와 현재 소스 | Kubernetes, N=32, 장시간 쇼핑몰 soak, 무작위 chaos는 **NOT RUN**. 기존 native 1800초 soak와 다른 검증이다. |
| 구조 조회 | `codebase-memory` 스킬의 소스 fallback | MCP 그래프 도구가 노출되지 않아 graph/index coverage는 **NOT RUN**. 아래 판단은 명시한 파일의 직접 확인에 한정한다. |

### 소스에서 확인한 개선 지점

링크는 모두 위 기준 커밋에 고정한다. 현재 소스에서 관찰한 사실과 새 시험이
필요한 추론을 구분했다.

| ID | 소스 근거 | 확인 내용 | 다음 단계 |
| --- | --- | --- | --- |
| G1 | [runtime 113–163](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/runtime/faultdebug_runtime.c#L113-L163), [decoder 185–215](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/faultdebug/format.py#L185-L215) | 스레드 슬롯 재등록 시 sequence는 0부터, generation은 증가하지만 event_count는 계속 누적된다. decoder는 누적 count로 미발행 슬롯을 기대한다. 기존 탐색 캡처에서도 이 패턴을 다시 확인했다. | 최소 native 재현과 세대별 count/retention 계약을 먼저 정한다. 고정 스레드 풀의 PASS를 slot reuse 해결로 해석하지 않는다. |
| G2 | [service report 55–58,100–112](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/faultdebug/service_report.py#L55-L112), [native RPC API](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/include/faultdebug/rpc.h#L20-L39) | native API는 trace hi/lo 두 워드를 지원하지만 쇼핑몰 application log와 매칭은 64비트 trace 중심이다. 지금 fixture는 hi=0이므로 성립한다. | W3C의 128비트 trace를 도입하기 전에 양쪽 워드를 보존하고 충돌 회귀를 추가한다. |
| G3 | [HTTP headers/deadline](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/test/shop/service.py#L69-L90), [receiver deadline](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/test/shop/service.py#L262-L279) | `X-Shop-*` 전용 헤더와 절대 monotonic deadline을 공유한다. 같은 clock domain의 로컬 컨테이너 시험용이다. | 다른 호스트/시간 namespace에는 그대로 확장하지 않는다. 로컬 duration과 인과 연결을 분리한다. |
| G4 | [checkout/state](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/test/shop/service.py#L133-L199), [compose restart](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/test/shop/run.py#L38-L62) | 주문·결제 상태는 메모리, checkout은 전역 lock으로 직렬화, restart는 `no`. 알림 `deferred`에는 실제 전달 큐가 없다. 배송 실패 뒤 결제/예약 보상도 현재 경로에 없다. | 재시작 시험에는 작은 영속 ledger와 명시적 미완료/보상 모델이 필요하다. 병렬 요청 수가 실제 checkout 처리 병렬성이라는 주장은 금한다. |
| G5 | [report joins](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/faultdebug/service_report.py#L126-L164) | relation마다 application events를 반복 검색한다. 파일·event 수 상한은 있지만 전체 byte budget 및 큰 입력의 시간/RSS 근거는 별도 확인이 필요하다. | identity/trace/RPC/attempt 색인, 총 입력 상한, 응답 pagination과 성능 gate를 설계한다. 실제 성능 저하 수치는 아직 측정하지 않았다. |
| G6 | [viewer draw](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/faultdebug/service_report_view.py#L17-L28), [capabilities](https://github.com/lsh235/FalutDebugMCP/blob/70d6771386a97778bdad167c6508827d6c1d56b4/faultdebug/capabilities.py#L11-L58) | viewer는 쇼핑몰 기본 서비스 배치와 추가 서비스 집계를 사용한다. CLI service-report가 있고 MCP에는 get_fault_flow가 있으나 service-report 전용 조회는 없다. | 임의 topology/프로세스 세대 탐색과 bounded read-only MCP 보고서 조회를 후보로 추가한다. |

G1의 이번 확인은 **기존 캡처 재해석**이다. 새 native 실행은 NOT RUN이다.
로컬 경로 `build/shop-evidence-n8-v2/success/evidence/payment/fault-8.fault`의
SHA256은 `1c32e3d6251b636c6b25b79aae1480e4c7322470a099c91862127cd109c4975b`.
현재 decoder 결과는 generation=4, event_count=8, retained=2,
event_slot 2–7 unpublished, complete=false, snapshot stable=false다.
이 로컬 탐색 자료는 배포 입력이나 원격 재현 자료로 가정하지 않는다. 후속 단계에서
현재 소스로 최소 재현을 만들어 커밋 가능한 작은 회귀 증거를 남긴다.

## 3. 공식 자료와 적용 판단

모든 링크는 조사일에 확인했다. 아래의 채택/보류는 **제안**이다.
공식 문서의 rolling 내용과 특정 release tag의 구현은 다를 수 있으므로,
실제 구현 단계에서는 선택한 tag의 소스와 image digest를 다시 고정한다.

### R1. W3C Trace Context — 추적 ID의 표준 연결

[공식 규격](https://www.w3.org/TR/trace-context/)은 `traceparent`에 version,
128비트 trace ID, 64비트 parent ID와 flags를 정의한다. 전달 시 현재 operation의
ID로 parent를 갱신하며, sampled flag가 기록의 존재를 보장하지 않는다.

**적용 판단:** native numeric API를 유지하면서 HTTP adapter에서 표준 헤더를
읽고 쓴다. W3C client/server span ID와 FaultDebug의 양쪽 endpoint 공통 rpc_id는
동일한 의미가 아니므로 변환 규칙과 별도 매핑 증거가 필요하다. 잘못된 ID,
zero ID, hi만 다른 trace, retry, 헤더 충돌, sampling으로 사라진 endpoint를 검증한다.
표준 ID만 같다는 이유로 native 관측 edge를 만들지 않는다.

### R2. Toxiproxy — Docker 네트워크 장애를 먼저 재현

[공식 저장소](https://github.com/Shopify/toxiproxy)는 HTTP API로 제어하는 TCP
proxy다. latency는 방향별이며, timeout, bandwidth 제한, reset_peer 등을 제공한다.
HTTP 업무 오류나 실제 커널 packet loss와 같은 것으로 취급하지 않는다.

**적용 판단:** checkout↔inventory/payment의 선택한 경로에 proxy를 배치해
지연, 응답 유실, TCP reset을 재현한다. 설정 의도, proxy 적용 기록, caller 증상,
receiver 처리/미처리 증거를 각각 보존한다. 장애 제거 후 정상 대조군도 실행한다.
앱의 `scenario` 분기만으로 네트워크 장애를 재현했다고 보고하지 않는다.

### R3. kind + Kubernetes 생명주기 — 재시작의 신원을 보존

[kind 설정](https://kind.sigs.k8s.io/docs/user/configuration/)은 여러 control-plane/
worker node 구성을 제공하지만 같은 호스트의 node containers가 실제 컴퓨팅 자원이나
격리 수준을 늘리지는 않는다. [Kubernetes Pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
에서 Pod UID와 컨테이너 재시작, Pod 교체를 구분한다. 같은 이름의 교체 Pod도 UID가
다르며 Pod 수명에 묶인 임시 자료는 삭제 시 보존을 기대할 수 없다.

**적용 판단:** 먼저 단일 호스트 kind에서 app+collector, 제한된 artifact volume,
프로세스 실행별 신원과 Pod/container 메타데이터를 검증한다. capture를 Pod 삭제 전에
내보내고 누락 시 unresolved를 남기는 export 경로가 필요하다. kind 다중 node PASS는
실제 다중 물리 호스트 PASS가 아니다. 원격 agent transport는 별도 버전으로 미룬다.

### R4. Chaos Mesh — 선택적 Kubernetes 장애 확장

[PodChaos 문서](https://chaos-mesh.org/docs/simulate-pod-chaos-on-kubernetes/)는 Pod
failure/kill과 container kill을 구분하고, Pod 교체에는 ReplicaSet 같은 복구 controller가
필요하다고 설명한다. 조사 당시 문서 버전은 2.8.4다.
[구조 문서](https://chaos-mesh.org/docs/)의 Chaos Daemon은 기본 privileged 권한을
사용하므로 기존 앱 컨테이너의 권한 계약과 동일하게 취급할 수 없다.

**적용 판단:** 처음에는 kind의 명시적 삭제·재시작과 Toxiproxy로 충분하다.
추가 실험이 필요할 때 관리되는 전용 kind cluster의 선택 profile로 도입한다.
NetworkChaos/PodChaos의 실제 적용·복구 상태와 결과를 기록한다. CRD를 생성했다는
사실만으로 fault가 적용되었다고 판정하지 않는다.

### R5. OpenTelemetry Demo — 외부 다언어 검증 대상

[공식 architecture](https://opentelemetry.io/docs/demo/architecture/)는 여러 언어의
microservices와 HTTP/gRPC 통신을 보여 준다.
[feature flags](https://opentelemetry.io/docs/demo/feature-flags/)에는 결제 실패와
결제 접근 불가 등 재현 가능한 조건이 있다.
[Docker](https://opentelemetry.io/docs/demo/docker-deployment/)와
[Kubernetes](https://opentelemetry.io/docs/demo/kubernetes-deployment/) 실행 경로를 제공한다.
rolling Docker 문서의 자원 안내는 앱 RAM 6GB/최소 구성 약 3GB, disk 14GB이며,
실제 pinned 구성의 소비량은 별도로 측정해야 한다.

**적용 판단:** 자체 Python 쇼핑몰을 폐기하지 않고 외부 integration profile을 추가한다.
우선 native C++ 서비스 한 곳과 인접 OTel spans를 연결한다. C++ 외 서비스는
application telemetry로 표시한다. 어떤 언어의 모든 함수나 자동 native fault capture가
지원된다고 확장 주장하지 않는다. CPU/RAM 부담 때문에 일반 PR 필수 gate보다
수동·예약 실행 후보가 적절하다. 전체 fork보다 pinned overlay/driver를 우선한다.

### R6. Archify — 보고서의 탐색 경험을 응용

[공식 저장소](https://github.com/tt-a1i/archify)는 독립 HTML, 노드 탐색,
route/reach 탐색과 export를 제공한다. authored reach는 실제 runtime impact 주장과
구분한다.

**적용 판단:** semantic node ID, 요청별 route focus, 프로세스 세대 구분,
출처 패널과 공유 가능한 standalone HTML을 응용한다. 현재 native paired edge 규칙을
유지하고, 설계도/정적 호출 관계/관측 RPC의 표시 종류를 분리한다. 전체 viewer 교체나
별도 frontend build system 도입은 첫 단계의 필수 조건으로 두지 않는다.
코드를 가져오는 경우 선택한 revision의 LICENSE/NOTICE와 배포 파일을 확인한다.

### R7. compiledb — 기존 적용을 기반으로 외부 소스 확보

[공식 저장소](https://github.com/nickdiego/compiledb)는 Make 계열 build에서 Clang
compilation database를 생성한다. 이 프로젝트는 이미
[Make/compiledb 검증](build-integration-v1.1.md)과
[`test_compiledb_integration.py`](../test/build_systems/test_compiledb_integration.py)를 갖고 있다.

**적용 판단:** 새 기능으로 다시 계획하지 않는다. 외부 C/C++ service를 붙일 때
compilation database → source index → binary Build ID → immutable bundle 경로를
재사용한다. 복수 build variant를 섞거나 경로만 같다고 source evidence를 수락하지 않는다.

### R8. 종료·시간·readiness 규칙

[Linux signal 문서](https://www.man7.org/linux/man-pages/man2/signal.2.html)에 따르면
SIGKILL은 catch할 수 없다. 따라서 kill 결과에서 crash handler의 PC 기록을 요구하는
테스트는 잘못된 수락 기준이다. [Python monotonic 문서](https://docs.python.org/3.12/library/time.html#time.monotonic)
는 기준점이 정의되지 않으므로 시계 비교에는 같은 domain을 확인해야 한다.
[Docker Compose startup 문서](https://docs.docker.com/compose/how-tos/startup-order/)
는 running과 ready를 구분하고 healthcheck 조건을 제공한다.

**적용 판단:** OOM/SIGKILL은 orchestrator/cgroup 증거와 마지막 관측 RPC를 연결하되
native crash PC가 없음을 표시한다. exit 137만으로 OOM 원인을 확정하지 않는다.
통신 준비는 health probe로 확인하고, 다른 clock domain의 deadline은 caller 로컬
timeout과 receiver 로컬 budget으로 제한한다. 전송 지연을 모르는 상대 TTL만으로
전역 deadline을 보장하거나 늦은 stock mutation을 안전하다고 판정하지 않는다.

## 4. 조사 당시 확인한 release 후보

GitHub `releases/latest` API로 공개 tag를 조회한 결과다. 설치·통합 PASS가 아니다.
최신 tag를 반드시 사용해야 하는 것은 아니며, spike 뒤 지원 matrix로 고정한다.

| 프로젝트 | 조회한 tag | 공개 시각 UTC | 자료 |
| --- | --- | --- | --- |
| OpenTelemetry Demo | `3.1.0` | 2026-09-18 18:03:28 | [release](https://github.com/open-telemetry/opentelemetry-demo/releases/tag/3.1.0) |
| Toxiproxy | `v2.12.0` | 2025-03-18 13:12:45 | [release](https://github.com/Shopify/toxiproxy/releases/tag/v2.12.0) |
| kind | `v0.33.0` | 2026-08-26 21:58:46 | [release](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0) |
| Archify | `v3.0.1` | 2026-09-28 15:33:07 | [release](https://github.com/tt-a1i/archify/releases/tag/v3.0.1) |

문서의 resource 안내와 feature 설명을 이 tag에 그대로 보장하지 않는다.
구현 첫 spike에서 tag SHA, 각 image digest, chart/node-image 버전, API 호환성과
실제 자원 소비량을 실행 manifest에 남긴다.

## 5. 범위 선택

| 후보 | 기대 가치 | 비용/불확실성 | 제안 |
| --- | --- | --- | --- |
| slot reuse 정확성/손실 규칙 | 보고서 기반 신뢰성 | 과거 세대 보존과 ABI 호환을 함께 결정해야 함 | 최우선, stable 수락 전 평가 |
| W3C HTTP adapter + 128비트 report matching | 외부 서비스 상관관계 | client/server span과 rpc_id 의미 차이 | v1.3 필수 |
| Toxiproxy + 재시작 ledger | 실제 경로 실패·응답 유실 설명 | fault 적용 관측과 업무 상태 oracle 필요 | v1.3 필수 |
| 일반 topology와 read-only MCP 조회 | 다른 프로젝트에서 재사용 | 그래프 배치·pagination·입력 상한 | v1.3 필수 |
| kind lifecycle/export profile | Kubernetes 장애 재현 | artifact 유실, 실행 신원·clock domain | v1.3 필수, 로컬 범위 |
| OpenTelemetry Demo overlay | 다언어 외부 검증 | native 지원 경계와 RAM/CI 비용 | 조건부 실험 profile |
| Chaos Mesh NetworkChaos | Pod/network 복합 장애 | privileged daemon과 CRD 운영 | 후속 선택 profile |
| 실시간 dashboard/remote agent/전언어 자동 계측 | 운영 확장 | 인증·transport·언어별 runtime 작업 규모 큼 | v1.4+ 별도 설계 |
| 실제 결제·알림 provider, 운영 쇼핑몰 완성 | 실제 사업 연동 | 본 native tracing 프로젝트 범위를 벗어남 | 현재 검증 목표 밖 |

## 6. 조사 확인 상태

- **PASS:** 기준 커밋/remote 일치, release/CI 조회, 지정 소스 확인, 공식 자료 확인,
  기존 slot reuse 캡처의 checksum과 현재 decoder 결과 확인.
- **기존 기록:** Docker N=8/16 및 build/consumer/browser 결과는 링크한 2026-10-09
  검증 문서의 결과이며 이번 조사에서 재실행하지 않았다.
- **NOT RUN:** 새 native 최소 재현, Toxiproxy 통합, W3C adapter, kind/Chaos Mesh,
  OTel Demo 계측, N=32와 쇼핑몰 soak, 큰 report 시간/RSS, graph/index coverage.

후속 조사에 대한 답은 “이 자료가 존재하는가”가 아니라 “고정된 소스와 실제 캡처로
어느 edge/원인을 설명할 수 있고 무엇이 unresolved인가”로 판단한다.
