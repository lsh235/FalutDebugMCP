#define _DEFAULT_SOURCE
#include "faultdebug/rpc.h"

#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <time.h>

static _Atomic uint64_t fd_sequence;
static _Atomic uint64_t fd_sink;

__attribute__((noinline)) static void record_one(void) {
  uint64_t sequence = atomic_fetch_add_explicit(&fd_sequence, 1, memory_order_relaxed);
  atomic_fetch_add_explicit(&fd_sink, sequence + 1, memory_order_relaxed);
  struct fd_rpc_event event = {0};
  event.rpc_id = sequence + 1;
  event.trace_id_hi = UINT64_C(0x12345678);
  event.trace_id_lo = sequence;
  event.method_id = UINT64_C(0x42);
  event.start_monotonic_ns = sequence + 1;
  event.direction = FD_RPC_DIRECTION_OUTBOUND;
  (void)fd_rpc_emit(&event);
}

static void *writer_thread(void *unused) {
  (void)unused;
  for (unsigned int i = 0; i < 12000; ++i) record_one();
  return NULL;
}

static uint64_t now_ns(void) {
  struct timespec now;
  clock_gettime(CLOCK_MONOTONIC, &now);
  return (uint64_t)now.tv_sec * UINT64_C(1000000000) + (uint64_t)now.tv_nsec;
}

int main(int argc, char **argv) {
  unsigned int seconds = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 10) : 3;
  uint64_t deadline = now_ns() + (uint64_t)seconds * UINT64_C(1000000000);
  do {
    pthread_t writer;
    if (pthread_create(&writer, NULL, writer_thread, NULL) != 0) return 2;
    for (unsigned int i = 0; i < 12000; ++i) record_one();
    if (pthread_join(writer, NULL) != 0) return 3;
  } while (now_ns() < deadline);
  return atomic_load_explicit(&fd_sink, memory_order_relaxed) == UINT64_MAX ? 4 : 0;
}
