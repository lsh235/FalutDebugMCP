#ifndef FAULTDEBUG_RPC_H
#define FAULTDEBUG_RPC_H

#include "faultdebug/format.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Publish one bounded, numeric-only semantic event.  The sequence,
 * publication, tid, and generation fields are owned by the runtime; values
 * supplied for those fields are ignored or filled when zero.  Returns 1 when
 * accepted, 0 when no optional sidecar was provisioned, and -1 for malformed
 * input.  This API does not install a gRPC interceptor and never records
 * payloads, metadata, method strings, or credentials.
 */
int fd_rpc_emit(const struct fd_rpc_event *event);

/* Convenience boundaries for interceptor implementations.  A begin/end pair
 * is correlated by rpc_id and the two trace-id words. */
int fd_rpc_begin(uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
                 uint64_t method_id, uint32_t direction,
                 uint64_t start_monotonic_ns);
int fd_rpc_end(uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
               uint64_t method_id, uint32_t direction, uint32_t status,
               uint64_t end_monotonic_ns, uint32_t flags);

/* v0.9 bounded attempt-aware boundaries.  The existing begin/end functions
 * remain ABI-compatible and mean attempt zero.  The attempt value occupies
 * the previously reserved numeric event word; v1 readers ignore it, while
 * v0.9 readers expose it as an optional field. */
int fd_rpc_begin_attempt(uint64_t rpc_id, uint64_t trace_id_hi,
                         uint64_t trace_id_lo, uint64_t method_id,
                         uint32_t direction, uint32_t attempt,
                         uint64_t start_monotonic_ns);
int fd_rpc_end_attempt(uint64_t rpc_id, uint64_t trace_id_hi,
                       uint64_t trace_id_lo, uint64_t method_id,
                       uint32_t direction, uint32_t attempt, uint32_t status,
                       uint64_t end_monotonic_ns, uint32_t flags);

#ifdef __cplusplus
}
#endif

#endif
