#include "trace.h"

#define FD_TRACE __attribute__((noinline))

extern "C" FD_TRACE void fd_grpc_trace_upstream_response() {
  asm volatile("" ::: "memory");
}

extern "C" FD_TRACE void fd_grpc_trace_proxy_received() {
  asm volatile("" ::: "memory");
}

extern "C" FD_TRACE void fd_grpc_trace_proxy_forwarded() {
  asm volatile("" ::: "memory");
}

extern "C" FD_TRACE void fd_grpc_trace_proxy_response() {
  asm volatile("" ::: "memory");
}

extern "C" FD_TRACE void fd_grpc_trace_proxy_fault_after_response() {
  // Keep the fault in an application-owned, symbolizable boundary.  It is
  // intentionally a real invalid store rather than raise(SIGSEGV), so the
  // artifact contains the proxy callback's instruction and fault address.
  volatile int* invalid = nullptr;
  *invalid = 7;
}

extern "C" FD_TRACE void fd_grpc_rpc_begin(
    uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
    uint64_t method_id, uint32_t direction, uint64_t timestamp_ns) {
  (void)fd_rpc_begin(rpc_id, trace_id_hi, trace_id_lo, method_id, direction,
                     timestamp_ns);
}

extern "C" FD_TRACE void fd_grpc_rpc_begin_attempt(
    uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
    uint64_t method_id, uint32_t direction, uint32_t attempt,
    uint64_t timestamp_ns) {
  (void)fd_rpc_begin_attempt(rpc_id, trace_id_hi, trace_id_lo, method_id,
                             direction, attempt, timestamp_ns);
}

extern "C" FD_TRACE void fd_grpc_rpc_end(
    uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
    uint64_t method_id, uint32_t direction, uint32_t status,
    uint64_t timestamp_ns, uint32_t flags) {
  (void)fd_rpc_end(rpc_id, trace_id_hi, trace_id_lo, method_id, direction,
                   status, timestamp_ns, flags);
}

extern "C" FD_TRACE void fd_grpc_rpc_end_attempt(
    uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
    uint64_t method_id, uint32_t direction, uint32_t attempt,
    uint32_t status, uint64_t timestamp_ns, uint32_t flags) {
  (void)fd_rpc_end_attempt(rpc_id, trace_id_hi, trace_id_lo, method_id,
                           direction, attempt, status, timestamp_ns, flags);
}
