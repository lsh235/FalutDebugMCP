# N개 프로세스 쇼핑몰 장애 실험

기본 8개 서비스(게이트웨이·상품·장바구니·주문·재고·결제·배송·알림)를 각각
별도 Docker 컨테이너에서 실행합니다. N을 늘리면 추가 risk 워커를 실제 주문
흐름에서 모두 호출합니다. N은 애플리케이션 프로세스 수이며, 컨테이너의
collector와 init 프로세스는 별도입니다.

```sh
docker build -f test/shop/Dockerfile -t faultdebug-shop:dev .
.venv/bin/python test/shop/run.py --processes 8 --requests 4 --concurrency 2 \
  --output build/shop-run
.venv/bin/python -m http.server 8870 --bind 127.0.0.1 --directory build/shop-run
```

`http://127.0.0.1:8870/index.html`에서 시나리오를 선택합니다. 재고 부족, 결제
거절, 응답 지연, 알림 장애, 실제 네이티브 crash를 주입합니다. HTML은 실제
서비스 간 연결과 실패 전파를 보여주고, 호출 행을 선택하면 native RPC ID,
호출자 상태·시간, 수신자 종료 여부와 상태를 확인할 수 있습니다. 실패 설명의
소스와 crash 명령 주소는 검증된 소스 번들에서 확인합니다.

```sh
# 16개 프로세스 / 동시 요청 4개 / 정상 주문 24건 및 결제 거절 24건
.venv/bin/python test/shop/run.py --processes 16 --requests 24 --concurrency 4 \
  --scenarios success payment_decline --output build/shop-scale
# 브라우저에서 직접 실험
.venv/bin/python test/shop/manage.py up --processes 8 --output build/shop-live
# http://127.0.0.1:8860
.venv/bin/python test/shop/manage.py stop --output build/shop-live
```

N 범위는 8..32입니다. 기존 출력 폴더는 덮어쓰지 않습니다. 자동 테스트는
자신이 생성한 Compose 프로젝트만 정리합니다. 직접 실행한 실험은 `stop`으로
정상 종료·수집해야 `build/shop-live/report`에 보고서가 만들어집니다. 결제 crash
후에는 새 실험 폴더로 재시작합니다. 화면의 보고서 링크는 8870 포트의 사전
검증 보고서이며, 방금 실행한 주문의 실시간 보고서라는 의미는 아닙니다.

정상 주문과 주문 재실행의 중복 결제 방지, 실패 주문 미완료, 결제 실패 시
재고 예약 해제, timeout 이후 재고 변경 방지, 알림 장애 시 주문 유지까지
검사합니다. 애플리케이션 이유 설명은 native RPC 및 상태와 대조하지만,
로그 자체의 진위를 보증하지는 않습니다. Python 호출 스택을 추적하는 기능은
아니며 C++ 경계 모듈의 함수 이벤트와 crash를 수집합니다. 외부 고객 요청,
미도달 서비스, crash로 끝나지 못한 RPC 등의 증거 공백은 그대로 표시합니다.

전체 문서는 `report.md`, 구조화된 증거는 `report.json`으로 제공하며, HTML에서
선택한 요청을 인쇄할 수 있습니다. 주문과 결제는 메모리 기반 모의 데이터입니다.
Docker Compose 실행은 검증하며 Kubernetes와 실제 결제 사업자 연동은
**NOT RUN**입니다. [전체 안내](shopping-fault-lab.md)와
[검증 기록](shopping-fault-lab.validation.md)을 참고하세요.
