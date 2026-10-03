#ifndef FAULTDEBUG_GRPC_PROXY_TRACE_H
#define FAULTDEBUG_GRPC_PROXY_TRACE_H

#include "faultdebug/rpc.h"

#include <cstdint>

// These small application-owned boundaries are compiled with
// -finstrument-functions.  The gRPC implementation and generated protobuf
// glue stay outside the function ring; this keeps the fixture representative
// of selective production instrumentation.
extern "C" void fd_grpc_trace_upstream_response();
extern "C" void fd_grpc_trace_proxy_received();
extern "C" void fd_grpc_trace_proxy_forwarded();
extern "C" void fd_grpc_trace_proxy_response();
extern "C" void fd_grpc_trace_proxy_fault_after_response();

// Stable numeric method IDs are part of this fixture's application contract;
// no method strings or request/response payloads are passed to the runtime.
static constexpr uint64_t FD_GRPC_METHOD_FORWARD = UINT64_C(0x464f525741524401);
static constexpr uint64_t FD_GRPC_METHOD_STREAM = UINT64_C(0x53545245414d01);

extern "C" void fd_grpc_rpc_begin(uint64_t rpc_id, uint64_t trace_id_hi,
                                   uint64_t trace_id_lo, uint64_t method_id,
                                   uint32_t direction, uint64_t timestamp_ns);
extern "C" void fd_grpc_rpc_end(uint64_t rpc_id, uint64_t trace_id_hi,
                                 uint64_t trace_id_lo, uint64_t method_id,
                                 uint32_t direction, uint32_t status,
                                 uint64_t timestamp_ns, uint32_t flags);
extern "C" void fd_grpc_rpc_begin_attempt(uint64_t rpc_id,
                                           uint64_t trace_id_hi,
                                           uint64_t trace_id_lo,
                                           uint64_t method_id,
                                           uint32_t direction,
                                           uint32_t attempt,
                                           uint64_t timestamp_ns);
extern "C" void fd_grpc_rpc_end_attempt(uint64_t rpc_id,
                                         uint64_t trace_id_hi,
                                         uint64_t trace_id_lo,
                                         uint64_t method_id,
                                         uint32_t direction,
                                         uint32_t attempt, uint32_t status,
                                         uint64_t timestamp_ns, uint32_t flags);

#endif
