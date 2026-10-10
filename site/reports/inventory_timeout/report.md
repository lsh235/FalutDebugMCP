# 쇼핑몰 서비스 장애 보고서

Session: `fdshop-b7b99f7b08-inventory-timeout`

애플리케이션 프로세스 8개 · 관측된 RPC 호출 16개

## 장애 발생 위치와 이유

- **inventory / inventory_latency**: Injected 900 ms inventory delay exceeds the checkout RPC timeout of 300 ms.
  - 검증 상태: `corroborated_rpc`; RPC `4000000001`; 요청 `inventory_timeout-1`.
  - 소스 근거: `test/shop/service.py:165` (immutable bundle SHA-256).
- **inventory / inventory_latency**: Injected 900 ms inventory delay exceeds the checkout RPC timeout of 300 ms.
  - 검증 상태: `corroborated_rpc`; RPC `4000000002`; 요청 `inventory_timeout-0`.
  - 소스 근거: `test/shop/service.py:165` (immutable bundle SHA-256).
- **inventory / inventory_latency**: Injected 900 ms inventory delay exceeds the checkout RPC timeout of 300 ms.
  - 검증 상태: `corroborated_rpc`; RPC `4000000003`; 요청 `inventory_timeout-2`.
  - 소스 근거: `test/shop/service.py:165` (immutable bundle SHA-256).
- **inventory / expired_before_reservation**: Caller deadline expired before stock mutation; no reservation was created.
  - 검증 상태: `corroborated_rpc_status`; RPC `4000000001`; 요청 `inventory_timeout-1`.
  - 소스 근거: `test/shop/service.py:170` (immutable bundle SHA-256).
- **inventory / inventory_latency**: Injected 900 ms inventory delay exceeds the checkout RPC timeout of 300 ms.
  - 검증 상태: `corroborated_rpc`; RPC `4000000004`; 요청 `inventory_timeout-3`.
  - 소스 근거: `test/shop/service.py:165` (immutable bundle SHA-256).
- **inventory / expired_before_reservation**: Caller deadline expired before stock mutation; no reservation was created.
  - 검증 상태: `corroborated_rpc_status`; RPC `4000000002`; 요청 `inventory_timeout-0`.
  - 소스 근거: `test/shop/service.py:170` (immutable bundle SHA-256).
- **inventory / expired_before_reservation**: Caller deadline expired before stock mutation; no reservation was created.
  - 검증 상태: `corroborated_rpc_status`; RPC `4000000003`; 요청 `inventory_timeout-2`.
  - 소스 근거: `test/shop/service.py:170` (immutable bundle SHA-256).
- **inventory / expired_before_reservation**: Caller deadline expired before stock mutation; no reservation was created.
  - 검증 상태: `corroborated_rpc_status`; RPC `4000000004`; 요청 `inventory_timeout-3`.
  - 소스 근거: `test/shop/service.py:170` (immutable bundle SHA-256).

## 실제 서비스 호출

| 요청 | 경로 | HTTP | 시간 ms | RPC |
|---|---|---:|---:|---|
| inventory_timeout-0 | gateway → cart /cart | 200 | 5.3 | 1000000005 |
| inventory_timeout-1 | gateway → cart /cart | 200 | 4.87 | 1000000006 |
| inventory_timeout-1 | cart → catalog /products | 200 | 2.42 | 3000000001 |
| inventory_timeout-0 | cart → catalog /products | 200 | 2.55 | 3000000002 |
| inventory_timeout-1 | gateway → checkout /checkout | 504 | 303.87 | 1000000007 |
| inventory_timeout-0 | gateway → checkout /checkout | 504 | 605.45 | 1000000008 |
| inventory_timeout-1 | checkout → inventory /reserve | 504 | 301.42 | 4000000001 |
| inventory_timeout-0 | checkout → inventory /reserve | 504 | 301.79 | 4000000002 |
| inventory_timeout-2 | gateway → cart /cart | 200 | 2.5 | 1000000011 |
| inventory_timeout-2 | cart → catalog /products | 200 | 1.18 | 3000000003 |
| inventory_timeout-2 | gateway → checkout /checkout | 504 | 599.63 | 1000000012 |
| inventory_timeout-2 | checkout → inventory /reserve | 504 | 301.55 | 4000000003 |
| inventory_timeout-3 | gateway → cart /cart | 200 | 2.41 | 1000000015 |
| inventory_timeout-3 | cart → catalog /products | 200 | 1.15 | 3000000004 |
| inventory_timeout-3 | gateway → checkout /checkout | 504 | 599.05 | 1000000016 |
| inventory_timeout-3 | checkout → inventory /reserve | 504 | 301.37 | 4000000004 |

## 증거의 한계

- Application reasons are self-reported; hashes identify frozen evidence, not authenticity.
- Native function traces cover the C++ boundary module, not Python call stacks.
- Parent RPC IDs come from application propagation; shared trace IDs alone do not establish causality.
- A receiver may finish after the caller times out; caller and receiver statuses are distinct.

미해결 증거 항목: 8. 전체 항목은 report.json과 HTML에서 확인합니다.

## 증거 파일

- `cart/fault-8.fault` — checksummed_native_capture, SHA-256 `9e37e37dc012f915f4a1bfbec462ccc025c6f5661c0a97db963a72be9a857fd1`
- `catalog/fault-8.fault` — checksummed_native_capture, SHA-256 `cb8c6a2c3d17eb17e7be3cb72beee399d6ea290c2d6806b9e301b5e2b7da6218`
- `checkout/fault-8.fault` — checksummed_native_capture, SHA-256 `95d37a1491a124650d5f5fbf5eb70c69ed4b61d2e9be37b95a46f7089aa81713`
- `gateway/fault-7.fault` — checksummed_native_capture, SHA-256 `b08414dee54ddc61adfc1cee86281f05f7ea11a1212db2d7e159ddfb0e8e8a3d`
- `inventory/fault-8.fault` — checksummed_native_capture, SHA-256 `68218df06659a961866d6d57b451943258fff615621f734246f70fe2fa853796`
- `notification/fault-8.fault` — checksummed_native_capture, SHA-256 `14ffa8892f90d716c02858c988fea90e625c6ece61ba0c1e552bc3c8eaa4b8cb`
- `payment/fault-8.fault` — checksummed_native_capture, SHA-256 `ae4195d97802457f1e5444b96956208687ec4245ca542435a563a05f5f7ec22a`
- `shipping/fault-7.fault` — checksummed_native_capture, SHA-256 `a42be23de04be8dd79a1660e4cdc1041de70d942a0cf301cac4bd724a58c5593`
- `cart/events.jsonl` — application_self_report, SHA-256 `60154518be1f8c743178498cce5ffabad027290f5ddb8b4ff30be38e8f7c8c9c`
- `catalog/events.jsonl` — application_self_report, SHA-256 `5e742aa500617d796d7f7d9bb65154200604fa1e6e2de96ac92e5ff1534192a9`
- `checkout/events.jsonl` — application_self_report, SHA-256 `c4cf99653a094818693e6e5c37055e22e863ae6ddcb14da101df2c197c8c5a4f`
- `gateway/events.jsonl` — application_self_report, SHA-256 `fc01b7704ed48b9c991866e747e5717a9f4158f55b95cb6d5d88d544ef650eff`
- `inventory/events.jsonl` — application_self_report, SHA-256 `1b5db3506683094de442c911f77cf424ff8ee1e8da9cc45c1d927603e8b4ce8a`
- `notification/events.jsonl` — application_self_report, SHA-256 `790412b5e40ab500f305f7f3561a5be9a77e57a067876ec2d8667d02e00daae2`
- `payment/events.jsonl` — application_self_report, SHA-256 `58f4a767eed4c6f3aee1fc05df0d23f1cc0660e6ed8d12ee43155bd31985b392`
- `shipping/events.jsonl` — application_self_report, SHA-256 `fd816f8925a4623ae399b3d3147a2fbe020698b2bcc2c9d289040d7394f79640`
