# Fault execution flow report

Evidence: **limited**

Artifact: `{"path": "/home/sra235/2026/faultDebugMCP/build-v13-p0-hosted-shop-final/shopping-fault-evidence/shop-ci-n8/payment_crash/evidence/payment/fault-7.fault", "sha256": "5ab49a4361a3e3ead713e48137aecfaf8888f198e85c739a28331eff38c5d814", "format": "FDAR", "checksum_verified": true}`

## Captured fault sites

- SIGILL · TID 8 / generation 1
  PC: `0x7f5a4dc9b194` · function: `"_ZL31payment_authorization_invariantv"`
  Fault address: `0x7f5a4dc9b194`
  Last observed event: `thread-0-event-3` (temporal context only)

## Observed execution flow

### TID 8 / generation 1

Retained: 4 · omitted from view: 0 · dropped: 0

| Sequence | Event | Function | Evidence |
| --- | --- | --- | --- |
| 0 | enter | `"shop_request_boundary"` | verified source |
| 1 | exit | `"shop_request_boundary"` | verified source |
| 2 | enter | `"shop_payment_fault"` | verified source |
| 3 | enter | `"_ZL31payment_authorization_invariantv"` | verified source |

## Evidence limits and diagnostics

- `{"reason": "capture_completeness_unconfirmed"}`
- `{"reason": "rpc_capture_incomplete"}`
- FD-INCOMPLETE-TRACE: A retained thread trace has unbalanced enter/exit events; interruption or ring loss may have removed context.
- Recorded order and instrumented nesting do not establish the root cause or a direct call through uninstrumented code.
- The last recorded event before a crash is temporal context, not proof that the event caused the crash.
- Unmatched entries describe retained instrumentation, not an operating-system stack unwind.
- Threads are separated by TID and generation; no cross-thread causality is inferred.
- Static call candidates are kept separate from runtime observations. Source text requires a verified bundle.

## Verified source

### "c:@F@shop_request_boundary"

File: `"/home/sra235/2026/faultDebugMCP/build-v13-p0-hosted-shop-final/shopping-fault-evidence/shop-ci-n8/bundle/source/test/shop/boundary.cc"` · lines 5–7

    extern "C" __attribute__((noinline)) void shop_request_boundary() {
      asm volatile("" ::: "memory");
    }

### "c:@F@shop_payment_fault"

File: `"/home/sra235/2026/faultDebugMCP/build-v13-p0-hosted-shop-final/shopping-fault-evidence/shop-ci-n8/bundle/source/test/shop/boundary.cc"` · lines 15–17

    extern "C" __attribute__((noinline)) void shop_payment_fault() {
      payment_authorization_invariant();
    }

### "c:boundary.cc@F@payment_authorization_invariant#"

File: `"/home/sra235/2026/faultDebugMCP/build-v13-p0-hosted-shop-final/shopping-fault-evidence/shop-ci-n8/bundle/source/test/shop/boundary.cc"` · lines 9–13

    __attribute__((noinline)) static void payment_authorization_invariant() {
      // Controlled SIGILL: a payment authorization state transition is invalid.
      // Keep the instruction in this source file for Build-ID verified resolution.
      __builtin_trap();
    }


Interactive flow: open `report.html`. Print / save PDF from the browser.
