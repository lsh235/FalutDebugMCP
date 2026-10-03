#ifndef FAULTDEBUG_RPC_SCOPE_HPP
#define FAULTDEBUG_RPC_SCOPE_HPP

#include "faultdebug/rpc.h"

#include <chrono>
#include <cstdint>

namespace faultdebug {

/*
 * A small application-owned numeric RPC span.  It records no method text,
 * payload, metadata, or credentials.  Construction publishes a begin event;
 * destruction publishes an end event unless finish() was called.  If the
 * optional sidecar is absent, the scope becomes a no-op and accepted() is
 * false, preserving the ABI v1 launch path.
 */
class rpc_span_scope final {
 public:
  rpc_span_scope(uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
                 uint64_t method_id, uint32_t direction,
                 uint32_t attempt = 0,
                 uint64_t start_monotonic_ns = now_monotonic_ns()) noexcept
      : rpc_id_(rpc_id),
        trace_id_hi_(trace_id_hi),
        trace_id_lo_(trace_id_lo),
        method_id_(method_id),
        direction_(direction),
        attempt_(attempt),
        active_(fd_rpc_begin_attempt(rpc_id_, trace_id_hi_, trace_id_lo_,
                                     method_id_, direction_, attempt_,
                                     start_monotonic_ns) > 0) {}

  rpc_span_scope(const rpc_span_scope&) = delete;
  rpc_span_scope& operator=(const rpc_span_scope&) = delete;

  ~rpc_span_scope() noexcept { finish(0); }

  bool accepted() const noexcept { return active_; }

  void finish(uint32_t status,
              uint32_t flags = FD_RPC_EVENT_END) noexcept {
    if (!active_) return;
    (void)fd_rpc_end_attempt(rpc_id_, trace_id_hi_, trace_id_lo_, method_id_,
                             direction_, attempt_, status, now_monotonic_ns(),
                             flags | FD_RPC_EVENT_END);
    active_ = false;
  }

  void incomplete(uint32_t status) noexcept {
    finish(status, FD_RPC_EVENT_END | FD_RPC_EVENT_INCOMPLETE);
  }

 private:
  static uint64_t now_monotonic_ns() noexcept {
    return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
  }

  uint64_t rpc_id_;
  uint64_t trace_id_hi_;
  uint64_t trace_id_lo_;
  uint64_t method_id_;
  uint32_t direction_;
  uint32_t attempt_;
  bool active_;
};

}  // namespace faultdebug

#endif
