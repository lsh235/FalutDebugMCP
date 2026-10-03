# v0.3.0 gRPC 비동기 프록시 검증 기록

## 구현 범위

v0.3.0은 기존 C/C++ 함수 이력 수집기가 실제 비동기 gRPC 프록시 프로세스의
장애 직전 흐름을 fault 파일로 보존할 수 있는지 검증한다.

테스트 프로그램은 다음 세 프로세스로 구성된다.

1. CompletionQueue 기반 비동기 upstream 서버
2. CompletionQueue 기반 비동기 proxy 서버
3. unary RPC client

proxy는 downstream 요청을 비동기 upstream RPC로 전달하고 응답을 반환한다.
`--fault-after-response`를 사용하면 downstream 응답 completion 이후
애플리케이션 소유 함수에서 null pointer 접근을 실행한다.

## 빌드 연결

`test/CMakeLists.txt`의 `FAULTDEBUG_BUILD_GRPC_PROXY` 옵션이 켜져 있고
`gRPC::grpc++`, `protobuf::libprotobuf`, `protobuf::protoc`,
`gRPC::grpc_cpp_plugin`을 찾을 수 있을 때만 `fd_grpc_async_proxy`를 만든다.

빌드 시 `echo.proto`에서 다음 파일을 생성한다.

```text
echo.pb.cc
echo.pb.h
echo.grpc.pb.cc
echo.grpc.pb.h
```

gRPC 내부와 생성된 protobuf 코드는 blanket `-finstrument-functions` 대상에서
제외한다. 대신 `trace.cc`의 애플리케이션 소유 경계 함수만 계측한다.
이 정책은 4,096개 이벤트 링이 gRPC 의존성 내부 호출로 소진되는 것을 막는다.

## 검증 명령

```sh
cmake -S . -B build -G Ninja \
  -DFAULTDEBUG_BUILD_TESTS=ON \
  -DFAULTDEBUG_BUILD_GRPC_PROXY=ON \
  -DCMAKE_C_COMPILER="$PWD/.tools/bin/clang" \
  -DCMAKE_CXX_COMPILER="$PWD/.tools/bin/clang++"

cmake --build build --target fd_grpc_async_proxy -j2

.venv/bin/python test/grpc_proxy_test.py \
  --build-dir build \
  --output /tmp/fd-grpc-v030 \
  --timeout 90
```

gRPC가 없는 환경에서는 fixture가 `SKIPPED`가 되고 기존 C/C++ fixture 빌드는
계속 진행된다.

## 검증 결과

v0.3.0 검증 보고서는 `PASS 12`, `FAIL 0`, `NOT RUN 0`이었다.

검증한 내용은 다음과 같다.

- client가 `upstream:faultdebug-grpc` 응답을 수신
- proxy가 실제 `SIGSEGV`로 종료
- fault 파일의 FDAR checksum과 헤더 검증
- `si_code=SEGV_MAPERR`, `fault_address=0`, 유효한 PC 확인
- proxy 모듈 Build ID와 주소 범위 확인
- 함수 이벤트 순서, 세대, enter/exit prefix 확인
- `received → forwarded → response → fault_after_response` 경계 확인
- 장애 위치를 `trace.cc:26`의
  `fd_grpc_trace_proxy_fault_after_response`로 독립 해석
- Build ID가 일치하는 source bundle을 통한 재해석
- `max-calls=1` 정상 종료에서 fault 파일이 생성되지 않음
- timeout 시 proxy runner와 실제 target의 process group 정리

fault 파일과 보고서는 테스트 실행 시 지정한 output 디렉토리에 남긴다.
실제 실행에서 생성된 예시는 다음과 같다.

```text
/tmp/fd-grpc-final-root2/report.json
/tmp/fd-grpc-final-root2/artifacts/fault-59352.fault
```

## 현재 한계와 다음 단계

이 버전은 함수 경계 증거를 검증한다. fault 파일에는 아직 RPC ID, 메서드명,
client/server 방향, gRPC status, metadata trace ID가 들어가지 않는다. 따라서
여러 daemon의 RPC를 fault 파일만으로 인과 연결하는 기능은 다음 단계의 범위다.

다음 단계에서는 gRPC client/server interceptor에서 bounded semantic RPC ring을
기록하고, MCP가 관측 RPC 이벤트, 정적 호출 가능성, 복원 불가능한 구간을
분리해서 반환하도록 확장한다.
