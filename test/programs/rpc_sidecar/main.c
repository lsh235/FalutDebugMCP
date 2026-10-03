#define _GNU_SOURCE
#include "faultdebug/rpc.h"

#include <dlfcn.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>

typedef int (*emit_fn)(const struct fd_rpc_event *);
typedef int (*begin_fn)(uint64_t, uint64_t, uint64_t, uint64_t, uint32_t, uint64_t);
typedef int (*end_fn)(uint64_t, uint64_t, uint64_t, uint64_t, uint32_t, uint32_t, uint64_t, uint32_t);
typedef int (*begin_attempt_fn)(uint64_t, uint64_t, uint64_t, uint64_t, uint32_t, uint32_t, uint64_t);
typedef int (*end_attempt_fn)(uint64_t, uint64_t, uint64_t, uint64_t, uint32_t, uint32_t, uint32_t, uint64_t, uint32_t);

static int fail(const char *message) { fprintf(stderr, "rpc sidecar probe: %s\n", message); return 1; }

int main(int argc, char **argv) {
  if (argc != 2) return fail("runtime path is required");
  size_t size = FD_RPC_SIDECAR_OFFSET + sizeof(struct fd_rpc_sidecar_header) +
                8u * sizeof(struct fd_rpc_event);
  int shmfd = (int)syscall(SYS_memfd_create, "faultdebug-rpc-probe", MFD_CLOEXEC);
  if (shmfd < 0 || ftruncate(shmfd, (off_t)size) != 0) return fail("cannot create mapping");
  void *mapping = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, shmfd, 0);
  if (mapping == MAP_FAILED) return fail("cannot map sidecar");
  int ready[2];
  if (pipe(ready) != 0) return fail("cannot create readiness pipe");
  char fd_text[32];
  snprintf(fd_text, sizeof(fd_text), "%d", shmfd); setenv(FD_ENV_SHM_FD, fd_text, 1);
  snprintf(fd_text, sizeof(fd_text), "%d", ready[1]); setenv(FD_ENV_READY_FD, fd_text, 1);
  void *handle = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
  if (!handle) return fail(dlerror() ? dlerror() : "runtime load failed");
  char marker = 0;
  if (read(ready[0], &marker, 1) != 1 || marker != 'R') return fail("runtime did not become ready");
  emit_fn emit = (emit_fn)dlsym(handle, "fd_rpc_emit");
  begin_fn begin = (begin_fn)dlsym(handle, "fd_rpc_begin");
  end_fn end = (end_fn)dlsym(handle, "fd_rpc_end");
  begin_attempt_fn begin_attempt = (begin_attempt_fn)dlsym(handle, "fd_rpc_begin_attempt");
  end_attempt_fn end_attempt = (end_attempt_fn)dlsym(handle, "fd_rpc_end_attempt");
  if (!emit || !begin || !end || !begin_attempt || !end_attempt) return fail("producer API is not exported");
  struct fd_rpc_event event;
  memset(&event, 0, sizeof(event));
  event.rpc_id = 0x1234; event.trace_id_hi = 0xaaaa; event.trace_id_lo = 0xbbbb;
  event.method_id = 0x42; event.direction = FD_RPC_DIRECTION_INBOUND;
  event.start_monotonic_ns = 10; event.end_monotonic_ns = 20;
  if (emit(&event) != 1) return fail("fd_rpc_emit rejected a valid event");
  if (begin(0x1235, 1, 2, 0x43, FD_RPC_DIRECTION_OUTBOUND, 30) != 1 ||
      end(0x1235, 1, 2, 0x43, FD_RPC_DIRECTION_OUTBOUND, 0, 40, 0) != 1)
    return fail("begin/end producer API failed");
  if (begin_attempt(0x1236, 1, 2, 0x43, FD_RPC_DIRECTION_OUTBOUND, 2, 50) != 1 ||
      end_attempt(0x1236, 1, 2, 0x43, FD_RPC_DIRECTION_OUTBOUND, 2, 14, 60, 0) != 1)
    return fail("attempt-aware producer API failed");
  event.direction = 99;
  if (emit(&event) != -1) return fail("invalid direction was accepted");
  struct fd_rpc_sidecar_header *sidecar = (struct fd_rpc_sidecar_header *)
      ((unsigned char *)mapping + FD_RPC_SIDECAR_OFFSET);
  if (sidecar->magic != FD_RPC_MAGIC || sidecar->event_capacity != 8 ||
      sidecar->event_count != 5 || sidecar->process_generation == 0)
    return fail("sidecar header was not initialized correctly");
  struct fd_rpc_event *events = (struct fd_rpc_event *)
      ((unsigned char *)sidecar + sidecar->events_offset);
  if (events[0].publication != 1 || events[0].rpc_id != 0x1234 ||
      events[0].process_generation == 0 || events[0].thread_generation == 0 ||
      events[1].publication != 1 || events[1].flags != FD_RPC_EVENT_START ||
      events[2].publication != 1 || !(events[2].flags & FD_RPC_EVENT_END) ||
      events[3].reserved != 2 || events[4].reserved != 2)
    return fail("published event fields are invalid");
  for (unsigned int i = 0; i < 8; ++i) {
    event.rpc_id = 0x9000u + i; event.direction = FD_RPC_DIRECTION_INBOUND;
    if (emit(&event) != 1) return fail("bounded ring rejected a valid event");
  }
  if (sidecar->dropped_count != 5 || !(sidecar->flags & FD_RPC_SIDECAR_FLAG_LOSS) ||
      !(events[0].flags & FD_RPC_EVENT_LOSS))
    return fail("ring loss was not disclosed");
  dlclose(handle); close(ready[0]); close(ready[1]); munmap(mapping, size); close(shmfd);
  return 0;
}
