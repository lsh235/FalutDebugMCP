# 쇼핑몰 서비스 장애 보고서

Session: `fdshop-5f822ec7a2-success`

애플리케이션 프로세스 8개 · 관측된 RPC 호출 31개

## 장애 발생 위치와 이유

관측된 장애 원인 이벤트 없음. 성공 여부는 주문 결과를 별도로 확인해야 합니다.

## 실제 서비스 호출

| 요청 | 경로 | HTTP | 시간 ms | RPC |
|---|---|---:|---:|---|
| success-0 | gateway → cart /cart | 200 | 39.69 | 1000000005 |
| success-1 | gateway → cart /cart | 200 | 7.42 | 1000000006 |
| success-0 | cart → catalog /products | 200 | 2.72 | 3000000001 |
| success-1 | cart → catalog /products | 200 | 2.57 | 3000000002 |
| success-1 | gateway → checkout /checkout | 200 | 8.44 | 1000000007 |
| success-0 | gateway → checkout /checkout | 200 | 13.52 | 1000000008 |
| success-1 | checkout → inventory /reserve | 200 | 1.48 | 4000000001 |
| success-1 | checkout → payment /authorize | 200 | 1.34 | 4000000002 |
| success-1 | checkout → shipping /ship | 200 | 1.24 | 4000000003 |
| success-1 | checkout → notification /notify | 200 | 1.28 | 4000000004 |
| success-0 | checkout → inventory /reserve | 200 | 1.44 | 4000000005 |
| success-0 | checkout → payment /authorize | 200 | 1.28 | 4000000006 |
| success-2 | gateway → cart /cart | 200 | 2.89 | 1000000011 |
| success-0 | checkout → shipping /ship | 200 | 1.18 | 4000000007 |
| success-2 | cart → catalog /products | 200 | 1.24 | 3000000003 |
| success-0 | checkout → notification /notify | 200 | 1.14 | 4000000008 |
| success-2 | gateway → checkout /checkout | 200 | 6.98 | 1000000012 |
| success-2 | checkout → inventory /reserve | 200 | 1.41 | 4000000009 |
| success-2 | checkout → payment /authorize | 200 | 1.19 | 4000000010 |
| success-3 | gateway → cart /cart | 200 | 2.62 | 1000000015 |
| success-2 | checkout → shipping /ship | 200 | 1.1 | 4000000011 |
| success-3 | cart → catalog /products | 200 | 1.21 | 3000000004 |
| success-2 | checkout → notification /notify | 200 | 1.29 | 4000000012 |
| success-3 | gateway → checkout /checkout | 200 | 5.74 | 1000000016 |
| success-3 | checkout → inventory /reserve | 200 | 1.26 | 4000000013 |
| success-3 | checkout → payment /authorize | 200 | 0.98 | 4000000014 |
| success-3 | checkout → shipping /ship | 200 | 0.96 | 4000000015 |
| success-3 | checkout → notification /notify | 200 | 0.96 | 4000000016 |
| success-0 | gateway → cart /cart | 200 | 2.65 | 1000000019 |
| success-0 | cart → catalog /products | 200 | 1.28 | 3000000005 |
| success-0 | gateway → checkout /checkout | 200 | 1.19 | 1000000020 |

## 증거의 한계

- Application reasons are self-reported; hashes identify frozen evidence, not authenticity.
- Native function traces cover the C++ boundary module, not Python call stacks.
- Parent RPC IDs come from application propagation; shared trace IDs alone do not establish causality.
- A receiver may finish after the caller times out; caller and receiver statuses are distinct.

미해결 증거 항목: 6. 전체 항목은 report.json과 HTML에서 확인합니다.

## 증거 파일

- `cart/fault-9.fault` — checksummed_native_capture, SHA-256 `84db7c143285dd390d7eea5909212edc1f2076d021b33ce60e4d199c13846c3e`
- `catalog/fault-7.fault` — checksummed_native_capture, SHA-256 `f9da6d5d92e58bfad55cadd563a3cbfce9f72df4cfe044dc484cb1e216e9e640`
- `checkout/fault-8.fault` — checksummed_native_capture, SHA-256 `2bac376be2c9e5ee799ae2254cf2402d4436c1957550f4fa7853c29c3e7b3d08`
- `gateway/fault-7.fault` — checksummed_native_capture, SHA-256 `d614ab8e020fd5359ae786c30005f6e9b82841729cee29a544a0abf4bff38a50`
- `inventory/fault-9.fault` — checksummed_native_capture, SHA-256 `9b04ce00f3e00b2eb055ec135a00a33165ed4436b391ff7097caa6a01d2c5f24`
- `notification/fault-8.fault` — checksummed_native_capture, SHA-256 `cd0d7f695060af4d9c88c90a858f4db36fd8d27c7044b37281c8aeef3db314e6`
- `payment/fault-8.fault` — checksummed_native_capture, SHA-256 `43a4a7b75af81136e64c39d006d56a2a5e9f9f3f8cc4e1132fd1aa6994c0ee9d`
- `shipping/fault-8.fault` — checksummed_native_capture, SHA-256 `5624f0cfeb770ff270ea41a5e0e4bf894473e87cabad54ea56c8696f2b23adee`
- `cart/events.jsonl` — application_self_report, SHA-256 `dcbe73eeccaca52121b70cdf222885f7227929b1d1faf971537f8f9df56f2508`
- `catalog/events.jsonl` — application_self_report, SHA-256 `1a73608de0edb3fb7df380daebf8cc162585b732979d7ca747d2d7238493cfef`
- `checkout/events.jsonl` — application_self_report, SHA-256 `4e09d7664a67929cb0b93b8a8cb0d4f294d060ea2426d10cead8e3dcbc17ff82`
- `gateway/events.jsonl` — application_self_report, SHA-256 `54baba7ca23fb20e80c9daaf9c76614db50290faf1817f90e3f011ed1eb7bf17`
- `inventory/events.jsonl` — application_self_report, SHA-256 `ad523260f72e0c4b5dae09115c79cebe1874399c9062cc43358b69b9ebccab6b`
- `notification/events.jsonl` — application_self_report, SHA-256 `88863626beb67786cdd63dc7253af3817f19b1268acd3b227d2874a369e0e97c`
- `payment/events.jsonl` — application_self_report, SHA-256 `562b4f518088053d7f8a14949bcc064b75fb2df9ac4e44f4b9ee8f856dd21777`
- `shipping/events.jsonl` — application_self_report, SHA-256 `d26ea1b9184153821f3944fcc5a09b5c547fc3bcf018395d9f1ee31049dfc5b3`
