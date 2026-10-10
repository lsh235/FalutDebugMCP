# Fault execution flow report

Evidence: **limited**

Artifact: `{"path": "/home/sra235/2026/faultDebugMCP/build/showcase-c-capture/fault-674932.fault", "sha256": "683a017fe00c2cbb418568ea8bc0fdd66457b8e99e971da50a99facdf90bf087", "format": "FDAR", "checksum_verified": true}`

## Captured fault sites

- SIGSEGV · TID 674932 / generation 1
  PC: `0x589633536344` · function: `"fd_segv"`
  Fault address: `0x7040c5dc4000`
  Last observed event: `thread-0-event-1` (temporal context only)

## Observed execution flow

### TID 674932 / generation 1

Retained: 2 · omitted from view: 0 · dropped: 0

| Sequence | Event | Function | Evidence |
| --- | --- | --- | --- |
| 0 | enter | `"main"` | ambiguous_function_index |
| 1 | enter | `"fd_segv"` | verified source |

## Evidence limits and diagnostics

- `{"reason": "capture_completeness_unconfirmed"}`
- `{"reason": "rpc_capture_incomplete"}`
- FD-MISSING-SYMBOL: No unique symbol could be verified for this address.
- FD-INCOMPLETE-TRACE: A retained thread trace has unbalanced enter/exit events; interruption or ring loss may have removed context.
- Recorded order and instrumented nesting do not establish the root cause or a direct call through uninstrumented code.
- The last recorded event before a crash is temporal context, not proof that the event caused the crash.
- Unmatched entries describe retained instrumentation, not an operating-system stack unwind.
- Threads are separated by TID and generation; no cross-thread causality is inferred.
- Static call candidates are kept separate from runtime observations. Source text requires a verified bundle.

## Verified source

### "c:main.c@F@fd_segv"

File: `"/home/sra235/2026/faultDebugMCP/build/showcase-c-bundle/source/test/programs/signals/main.c"` · lines 8–8

    __attribute__((noinline)) static void fd_segv(void){size_t p=(size_t)sysconf(_SC_PAGESIZE);if(!p)_exit(90);void *x=mmap(0,p,PROT_NONE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);if(x==MAP_FAILED)_exit(90);volatile char *q=(volatile char*)x;(void)*q;}


Interactive flow: open `report.html`. Print / save PDF from the browser.
