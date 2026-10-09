#include "faultdebug/rpc.h"

// Python business services publish numeric RPC spans through the native runtime.
// Native function traces describe these boundaries, not Python call stacks.
extern "C" __attribute__((noinline)) void shop_request_boundary() {
  asm volatile("" ::: "memory");
}

__attribute__((noinline)) static void payment_authorization_invariant() {
  // Controlled SIGILL: a payment authorization state transition is invalid.
  // Keep the instruction in this source file for Build-ID verified resolution.
  __builtin_trap();
}

extern "C" __attribute__((noinline)) void shop_payment_fault() {
  payment_authorization_invariant();
}
