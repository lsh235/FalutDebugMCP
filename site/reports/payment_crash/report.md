# 쇼핑몰 서비스 장애 보고서

Session: `fdshop-79b082f93e-payment-crash`

애플리케이션 프로세스 8개 · 관측된 RPC 호출 6개

## 장애 발생 위치와 이유

- **payment / payment_native_trap**: Injected invalid authorization transition calls the native payment invariant trap.
  - 검증 상태: `corroborated_rpc_and_native_crash`; RPC `4000000002`; 요청 `payment_crash-0`.
  - 소스 근거: `test/shop/service.py:185` (immutable bundle SHA-256).

## 실제 서비스 호출

| 요청 | 경로 | HTTP | 시간 ms | RPC |
|---|---|---:|---:|---|
| payment_crash-0 | gateway → cart /cart | 200 | 3.27 | 1000000003 |
| payment_crash-0 | cart → catalog /products | 200 | 1.47 | 3000000001 |
| payment_crash-0 | gateway → checkout /checkout | 502 | 273.27 | 1000000004 |
| payment_crash-0 | checkout → inventory /reserve | 200 | 1.36 | 4000000001 |
| payment_crash-0 | checkout → payment /authorize | 502 | 268.07 | 4000000002 |
| payment_crash-0 | checkout → inventory /release | 200 | 1.85 | 4000000003 |

## 증거의 한계

- Application reasons are self-reported; hashes identify frozen evidence, not authenticity.
- Native function traces cover the C++ boundary module, not Python call stacks.
- Parent RPC IDs come from application propagation; shared trace IDs alone do not establish causality.
- A receiver may finish after the caller times out; caller and receiver statuses are distinct.

미해결 증거 항목: 6. 전체 항목은 report.json과 HTML에서 확인합니다.

## 증거 파일

- `cart/fault-9.fault` — checksummed_native_capture, SHA-256 `d36053acf068e77667016597a1aa0de665b7156db6e6536df9e98bcf10101b70`
- `catalog/fault-9.fault` — checksummed_native_capture, SHA-256 `b0cd895b46a3f93365887fb118934a25014e299665d408da18f700fb91c8d962`
- `checkout/fault-8.fault` — checksummed_native_capture, SHA-256 `ac974663f67f214576e16af32626ab8409306ef566d7e13664524fea9d43af36`
- `gateway/fault-9.fault` — checksummed_native_capture, SHA-256 `111d28ac55d061b4495c55cf0f1e4b0ccf5bc6962690dcd7f10f8fdd710e0708`
- `inventory/fault-7.fault` — checksummed_native_capture, SHA-256 `b60ece6769dcbe65a6e48650678edb6c2070e7519d9d0b547ea79f587890c2cf`
- `notification/fault-8.fault` — checksummed_native_capture, SHA-256 `9666a60d7f94da797e68e877afedc40ffb37a83edac33974d4ea1e9d3ebd738c`
- `payment/fault-7.fault` — checksummed_native_capture, SHA-256 `5ab49a4361a3e3ead713e48137aecfaf8888f198e85c739a28331eff38c5d814`
- `shipping/fault-8.fault` — checksummed_native_capture, SHA-256 `62e31a817192a1bbc3b2590890449d9cd05bcc3b95dd54f2351ebab6fddb2dbf`
- `cart/events.jsonl` — application_self_report, SHA-256 `8ccd6ec80ac8096ca1bfe9a6f5d98ac3fef74e04eac86f92c115b780c30cfa97`
- `catalog/events.jsonl` — application_self_report, SHA-256 `6ad2e06e874a2a002f2346e6b848a4c55717ebb769eacc42ddc8707ff00646ba`
- `checkout/events.jsonl` — application_self_report, SHA-256 `71d3ac80740697bd8d17f65ac1b93259af433efe29a7437dd3f7836cbc57b79e`
- `gateway/events.jsonl` — application_self_report, SHA-256 `7d6e5afa6d19111bd34ccd3f211389d22a7dd7e6aebe2c547fcebd9b540a3132`
- `inventory/events.jsonl` — application_self_report, SHA-256 `ce40d8216ed96d757805f2f03241c442739720707f1903c684721f95ef33dc1f`
- `notification/events.jsonl` — application_self_report, SHA-256 `5559e1a6d11b3dc6344aa7c457612483592e341aac58cb5bb1cf9d1fdddf43cb`
- `payment/events.jsonl` — application_self_report, SHA-256 `0e13a27fddb75c7978ac40d42091bd20604a1bcde59dd2af2ffb216bf25990aa`
- `shipping/events.jsonl` — application_self_report, SHA-256 `1961879ebdf27334b2b60dc2557c31d8f0133c1d79ce92624a551cfb3ae063f7`
