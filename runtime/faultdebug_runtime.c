#define _GNU_SOURCE
#include "faultdebug/format.h"
#include "faultdebug/rpc.h"
#include <dlfcn.h>
#include <elf.h>
#include <link.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <ucontext.h>

#define FD_ALTSTACK_SIZE (64u * 1024u)
#define FD_STARTUP_ATTR __attribute__((constructor(101), no_instrument_function))
#define FD_NI __attribute__((no_instrument_function))

static struct fd_shared_memory *fd_map;
static size_t fd_map_size;
static struct fd_rpc_sidecar_header *fd_rpc_map;
static _Atomic uint32_t fd_status;
static _Atomic uint32_t fd_next_module;
static _Atomic uint64_t fd_rpc_sequence;
static uint32_t fd_process_generation = 1;
static pthread_key_t fd_key;
static int fd_key_ready;
static int fd_ready_fd = -1;
static _Atomic int fd_disabled;
static _Atomic int fd_crashing;
static _Atomic uint64_t fd_atomic64_probe;
static stack_t fd_altstacks[FD_MAX_THREADS];
static unsigned char fd_altstack_mem[FD_MAX_THREADS][FD_ALTSTACK_SIZE];

struct fd_tls { uint32_t slot, generation; uint64_t sequence; int registered; int in_runtime; };
static _Thread_local struct fd_tls fd_tls = { UINT32_MAX, 0, 0, 0, 0 };

static uint64_t FD_NI fd_now(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return 0;
  return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}
static uint64_t FD_NI fd_tid(void) { return (uint64_t)syscall(SYS_gettid); }
static void FD_NI fd_publish_status(uint32_t bits) {
  atomic_fetch_or_explicit(&fd_status, bits, memory_order_release);
  if (fd_map) __atomic_fetch_or(&fd_map->header.status_flags, bits, __ATOMIC_RELEASE);
}

static int FD_NI fd_rpc_prepare(void) {
  const size_t base = FD_RPC_SIDECAR_OFFSET;
  if (!fd_map || fd_map_size < base + sizeof(struct fd_rpc_sidecar_header)) return 0;
  size_t available = fd_map_size - base;
  struct fd_rpc_sidecar_header *h = (struct fd_rpc_sidecar_header *)((unsigned char *)fd_map + base);
  if (h->magic != 0 && (h->magic != FD_RPC_MAGIC || h->version != FD_RPC_SIDECAR_VERSION ||
                        h->header_size < sizeof(*h))) return 0;
  uint32_t capacity = h->event_capacity;
  if (capacity == 0) {
    available -= sizeof(*h);
    capacity = (uint32_t)(available / sizeof(struct fd_rpc_event));
    if (capacity > FD_RPC_MAX_EVENTS) capacity = FD_RPC_MAX_EVENTS;
  }
  if (capacity == 0 || capacity > FD_RPC_MAX_EVENTS ||
      sizeof(*h) + (size_t)capacity * sizeof(struct fd_rpc_event) > fd_map_size - base)
    return 0;
  if (h->magic == 0) {
    memset(h, 0, sizeof(*h));
    h->magic = FD_RPC_MAGIC;
    h->version = FD_RPC_SIDECAR_VERSION;
    h->header_size = (uint16_t)sizeof(*h);
    h->process_generation = fd_process_generation;
    h->events_offset = (uint32_t)sizeof(*h);
  }
  h->total_size = (uint32_t)(sizeof(*h) + (size_t)capacity * sizeof(struct fd_rpc_event));
  h->event_capacity = capacity;
  if (h->process_generation == 0) h->process_generation = fd_process_generation;
  if (h->events_offset < h->header_size ||
      (size_t)h->events_offset + (size_t)capacity * sizeof(struct fd_rpc_event) > h->total_size)
    return 0;
  fd_rpc_map = h;
  atomic_store_explicit(&fd_rpc_sequence, h->event_count, memory_order_relaxed);
  return 1;
}

static int FD_NI fd_rpc_direction_valid(uint32_t direction) {
  return direction == FD_RPC_DIRECTION_INBOUND || direction == FD_RPC_DIRECTION_OUTBOUND;
}
static void FD_NI fd_startup_error(uint32_t bit) {
  fd_publish_status(bit);
  if (fd_ready_fd >= 0) { char c = 'E'; (void)write(fd_ready_fd, &c, 1); }
  atomic_store_explicit(&fd_disabled, 1, memory_order_release);
}
static int FD_NI fd_parse_config(uint32_t *events, uint32_t *threads) {
  const char *s = getenv(FD_ENV_CONFIG);
  if (!s || !*s) return 0;
  char buf[256]; size_t n = strlen(s); if (n >= sizeof(buf)) return -1; memcpy(buf, s, n + 1);
  for (char *tok = strtok(buf, ","); tok; tok = strtok(NULL, ",")) {
    char *eq = strchr(tok, '='); if (!eq) return -1; *eq++ = 0;
    char *end = NULL; unsigned long v = strtoul(eq, &end, 10); if (!*eq || *end || v == 0) return -1;
    if (!strcmp(tok, "events") || !strcmp(tok, "event_capacity")) { if (v > FD_MAX_EVENTS_PER_THREAD) return -1; *events = (uint32_t)v; }
    else if (!strcmp(tok, "threads") || !strcmp(tok, "thread_capacity")) { if (v > FD_MAX_THREADS) return -1; *threads = (uint32_t)v; }
    else return -1;
  }
  return 0;
}
static void FD_NI fd_tls_destructor(void *p) {
  (void)p;
  if (fd_map && fd_tls.registered && fd_tls.slot < FD_MAX_THREADS)
    __atomic_store_n(&fd_map->threads[fd_tls.slot].header.tid, 0, __ATOMIC_RELEASE);
  fd_tls.registered = 0; fd_tls.slot = UINT32_MAX;
}

static int FD_NI fd_register_thread(void) {
  if (!fd_map || atomic_load_explicit(&fd_disabled, memory_order_relaxed) || fd_tls.registered) return 0;
  uint32_t slot = UINT32_MAX;
  uint64_t tid = fd_tid();
  uint32_t limit = fd_map->header.thread_capacity < FD_MAX_THREADS ? fd_map->header.thread_capacity : FD_MAX_THREADS;
  for (uint32_t i = 0; i < limit; ++i) {
    uint64_t empty = 0;
    if (__atomic_compare_exchange_n(&fd_map->threads[i].header.tid, &empty, tid, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) { slot = i; break; }
  }
  if (slot == UINT32_MAX) {
    fd_publish_status(FD_STATUS_THREAD_OVERFLOW);
    return -1;
  }
  fd_tls.slot = slot; fd_tls.generation = 1; fd_tls.sequence = 0; fd_tls.registered = 1;
  struct fd_thread_ring *ring = &fd_map->threads[slot];
  ring->header.generation += 1; fd_tls.generation = ring->header.generation;
  ring->header.event_capacity = fd_map->header.event_capacity;
  stack_t ss = { .ss_sp = fd_altstack_mem[slot], .ss_size = FD_ALTSTACK_SIZE, .ss_flags = 0 };
  fd_altstacks[slot] = ss;
  if (sigaltstack(&ss, NULL) != 0) { fd_publish_status(FD_STATUS_PARTIAL); }
  if (fd_key_ready) pthread_setspecific(fd_key, &fd_tls);
  return 0;
}
static void FD_NI fd_record(uint32_t type, uintptr_t fn, uintptr_t caller) {
  if (!fd_map || atomic_load_explicit(&fd_disabled, memory_order_relaxed) ||
      atomic_load_explicit(&fd_crashing, memory_order_acquire)) return;
  if (fd_tls.in_runtime) return;
  fd_tls.in_runtime = 1;
  if (!fd_tls.registered && fd_register_thread() != 0) { fd_tls.in_runtime = 0; return; }
  struct fd_thread_ring *ring = &fd_map->threads[fd_tls.slot];
  uint32_t cap = ring->header.event_capacity;
  if (cap == 0 || cap > FD_MAX_EVENTS_PER_THREAD) { fd_tls.in_runtime = 0; return; }
  uint64_t seq = fd_tls.sequence++;
  struct fd_event *ev = &ring->events[seq % cap];
  __atomic_store_n(&ev->publication, 0, __ATOMIC_RELEASE);
  ev->sequence = seq; ev->monotonic_ns = fd_now(); ev->function_ptr = (uint64_t)fn;
  ev->callsite_ptr = (uint64_t)caller; ev->type = type; ev->generation = fd_tls.generation;
  if (seq >= cap) {
    __atomic_fetch_add(&ring->header.dropped_count, 1, __ATOMIC_RELAXED);
    fd_publish_status(FD_STATUS_EVENT_OVERFLOW);
    if ((seq % cap) == 0) ev->type = FD_EVENT_EVICT;
  }
  __atomic_store_n(&ev->publication, 1, __ATOMIC_RELEASE);
  __atomic_fetch_add(&ring->header.event_count, 1, __ATOMIC_RELAXED);
  fd_tls.in_runtime = 0;
}

void FD_NI __cyg_profile_func_enter(void *this_fn, void *call_site) { fd_record(FD_EVENT_ENTER, (uintptr_t)this_fn, (uintptr_t)call_site); }
void FD_NI __cyg_profile_func_exit(void *this_fn, void *call_site) { fd_record(FD_EVENT_EXIT, (uintptr_t)this_fn, (uintptr_t)call_site); }

static void FD_NI fd_crash_handler(int sig, siginfo_t *si, void *uctx) {
  int expected = 0;
  if (!atomic_compare_exchange_strong_explicit(&fd_crashing, &expected, 1, memory_order_acq_rel, memory_order_relaxed)) {
    signal(sig, SIG_DFL); syscall(SYS_tgkill, (pid_t)getpid(), (pid_t)fd_tid(), sig); _exit(128 + sig);
  }
  if (fd_map) {
    struct fd_crash_record *cr = &fd_map->crashes[0];
    uint32_t pub = 0;
    if (__atomic_compare_exchange_n(&cr->publication, &pub, 2, 0, __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
      cr->flags = FD_CRASH_SIGNAL_VALID;
      cr->signal_number = (uint32_t)sig;
      if (si) {
        cr->si_code = si->si_code; cr->flags |= FD_CRASH_SI_CODE_VALID;
        if ((sig == SIGSEGV || sig == SIGBUS || sig == SIGILL || sig == SIGFPE) && si->si_code > 0) {
          cr->fault_address = (uint64_t)(uintptr_t)si->si_addr; cr->flags |= FD_CRASH_FAULT_ADDR_VALID;
        }
      }
      cr->tid = fd_tid(); cr->monotonic_ns = fd_now();
#if defined(REG_RIP)
      if (uctx) { cr->program_counter = (uint64_t)((ucontext_t *)uctx)->uc_mcontext.gregs[REG_RIP]; cr->flags |= FD_CRASH_PC_VALID; }
#elif defined(REG_EIP)
      if (uctx) { cr->program_counter = (uint64_t)((ucontext_t *)uctx)->uc_mcontext.gregs[REG_EIP]; cr->flags |= FD_CRASH_PC_VALID; }
#endif
      __atomic_store_n(&cr->publication, 1, __ATOMIC_RELEASE);
    }
    fd_publish_status(FD_STATUS_CRASHED | FD_STATUS_FROZEN);
    if (fd_rpc_map) __atomic_fetch_or(&fd_rpc_map->flags, FD_RPC_SIDECAR_FLAG_INCOMPLETE, __ATOMIC_RELEASE);
  }
  struct sigaction dfl; memset(&dfl, 0, sizeof(dfl)); dfl.sa_handler = SIG_DFL; sigemptyset(&dfl.sa_mask); sigaction(sig, &dfl, NULL);
  sigset_t unblock; sigemptyset(&unblock); sigaddset(&unblock, sig); sigprocmask(SIG_UNBLOCK, &unblock, NULL);
  syscall(SYS_tgkill, (pid_t)getpid(), (pid_t)fd_tid(), sig);
  for (;;) pause();
}

static int FD_NI fd_module_cb(struct dl_phdr_info *info, size_t size, void *data) {
  (void)size; (void)data;
  uint32_t n = atomic_fetch_add_explicit(&fd_next_module, 1, memory_order_relaxed);
  if (!fd_map || n >= fd_map->header.module_capacity || n >= FD_MAX_MODULES) { fd_publish_status(FD_STATUS_MODULE_OVERFLOW); return 1; }
  struct fd_module_record *m = &fd_map->modules[n];
  m->load_bias = (uint64_t)info->dlpi_addr;
  m->text_start = UINT64_MAX; m->text_end = 0;
  size_t len = info->dlpi_name ? strlen(info->dlpi_name) : 0;
  if (len > sizeof(m->path)-1) len = sizeof(m->path)-1;
  if (len) memcpy(m->path, info->dlpi_name, len);
  m->path[len] = 0; m->path_length = (uint32_t)len;
  for (size_t i = 0; i < info->dlpi_phnum; ++i) if (info->dlpi_phdr[i].p_type == PT_NOTE) {
    const unsigned char *p = (const unsigned char *)(info->dlpi_addr + info->dlpi_phdr[i].p_vaddr);
    const unsigned char *end = p + info->dlpi_phdr[i].p_memsz;
    while (p + 12 <= end) {
      uint32_t namesz, descsz, type;
      memcpy(&namesz, p, 4); memcpy(&descsz, p + 4, 4); memcpy(&type, p + 8, 4); p += 12;
      size_t na = (namesz + 3u) & ~3u, da = (descsz + 3u) & ~3u;
      if (p + na + da > end) break;
      if (type == 3 && namesz >= 3 && memcmp(p, "GNU", 3) == 0) {
        size_t take = descsz < sizeof(m->build_id) ? descsz : sizeof(m->build_id);
        memcpy(m->build_id, p + na, take); m->build_id_length = (uint32_t)take;
        m->build_id_flags = (take == descsz) ? 2u : 1u;
        break;
      }
      p += na + da;
    }
  }
  for (size_t i = 0; i < info->dlpi_phnum; ++i) if (info->dlpi_phdr[i].p_type == PT_LOAD && (info->dlpi_phdr[i].p_flags & PF_X)) {
    uint64_t s = (uint64_t)info->dlpi_addr + info->dlpi_phdr[i].p_vaddr;
    if (s < m->text_start) m->text_start = s;
    if (s + info->dlpi_phdr[i].p_memsz > m->text_end) m->text_end = s + info->dlpi_phdr[i].p_memsz;
  }
  __atomic_store_n(&m->publication, 1, __ATOMIC_RELEASE); return 0;
}

static void FD_NI fd_atfork_child(void) {
  /* Preserve the fact that this process forked before the child detaches from
   * the parent's mapping.  The child is intentionally disabled until a
   * supervisor launches it with a fresh mapping. */
  if (fd_map) fd_publish_status(FD_STATUS_FORK_CHILD);
  atomic_store_explicit(&fd_disabled, 1, memory_order_release);
  if (fd_map) { munmap(fd_map, fd_map_size); fd_map = NULL; fd_rpc_map = NULL; }
  if (fd_ready_fd >= 0) { close(fd_ready_fd); fd_ready_fd = -1; }
}

static int FD_NI fd_parse_process_generation(void) {
  const char *value = getenv("FAULTDEBUG_PROCESS_GENERATION");
  if (!value || !*value) return 0;
  char *end = NULL;
  unsigned long parsed = strtoul(value, &end, 10);
  if (end == value || *end != '\0' || parsed == 0 || parsed > UINT32_MAX) return -1;
  fd_process_generation = (uint32_t)parsed;
  return 0;
}

static void FD_NI fd_startup(void) {
  const char *fd_s = getenv(FD_ENV_SHM_FD), *ready = getenv(FD_ENV_READY_FD);
  if (!fd_s || !ready || getenv(FD_ENV_DISABLE)) { atomic_store(&fd_disabled, 1); return; }
  int fd = atoi(fd_s); fd_ready_fd = atoi(ready); struct stat st;
  if (fstat(fd, &st) != 0 || st.st_size < (off_t)sizeof(struct fd_shared_memory)) { fd_startup_error(FD_STATUS_CONFIG_ERROR); return; }
  fd_map_size = (size_t)st.st_size; fd_map = mmap(NULL, fd_map_size, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
  if (fd_map == MAP_FAILED) { fd_map = NULL; fd_startup_error(FD_STATUS_CONFIG_ERROR); return; }
  if (!atomic_is_lock_free(&fd_atomic64_probe)) { fd_startup_error(FD_STATUS_CONFIG_ERROR); return; }
  fd_map->header.magic = FD_ABI_MAGIC; fd_map->header.abi_version = FD_ABI_VERSION; fd_map->header.header_size = sizeof(struct fd_shared_header);
  uint32_t event_capacity = FD_MAX_EVENTS_PER_THREAD, thread_capacity = FD_MAX_THREADS;
  if (fd_parse_config(&event_capacity, &thread_capacity) != 0) { fd_startup_error(FD_STATUS_CONFIG_ERROR); return; }
  if (fd_parse_process_generation() != 0) { fd_startup_error(FD_STATUS_CONFIG_ERROR); return; }
  fd_map->header.total_size = (uint32_t)fd_map_size; fd_map->header.event_capacity = event_capacity; fd_map->header.thread_capacity = thread_capacity; fd_map->header.module_capacity = FD_MAX_MODULES; fd_map->header.crash_capacity = FD_MAX_CRASH_RECORDS;
  fd_map->header.creator_pid = (uint64_t)getpid(); fd_map->header.start_monotonic_ns = fd_now(); fd_map->header.threads_offset = offsetof(struct fd_shared_memory, threads); fd_map->header.modules_offset = offsetof(struct fd_shared_memory, modules); fd_map->header.crashes_offset = offsetof(struct fd_shared_memory, crashes);
  if (fd_map_size >= FD_RPC_SIDECAR_OFFSET + sizeof(struct fd_rpc_sidecar_header) && !fd_rpc_prepare())
    fd_publish_status(FD_STATUS_PARTIAL);
  pthread_key_create(&fd_key, fd_tls_destructor); fd_key_ready = 1; pthread_atfork(NULL, NULL, fd_atfork_child); dl_iterate_phdr(fd_module_cb, NULL);
  if (atomic_load_explicit(&fd_status, memory_order_acquire) & FD_STATUS_MODULE_OVERFLOW) { fd_startup_error(FD_STATUS_MODULE_OVERFLOW); return; }
  struct sigaction sa; memset(&sa, 0, sizeof(sa)); sigemptyset(&sa.sa_mask); sa.sa_sigaction = fd_crash_handler; sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
  int sigs[] = { SIGSEGV, SIGABRT, SIGBUS, SIGILL, SIGFPE };
  for (size_t i=0; i<sizeof(sigs)/sizeof(sigs[0]); ++i) {
    struct sigaction old;
    if (sigaction(sigs[i], NULL, &old) != 0 ||
        (old.sa_handler != SIG_DFL && old.sa_handler != SIG_IGN && old.sa_sigaction != NULL)) {
      fd_publish_status(FD_STATUS_SIGNAL_CONFLICT);
      continue;
    }
    if (sigaction(sigs[i], &sa, NULL) != 0) fd_publish_status(FD_STATUS_SIGNAL_CONFLICT);
  }
  if (atomic_load_explicit(&fd_status, memory_order_acquire) & FD_STATUS_SIGNAL_CONFLICT) { fd_startup_error(FD_STATUS_SIGNAL_CONFLICT); return; }
  fd_map->header.ready_monotonic_ns = fd_now(); fd_publish_status(FD_STATUS_READY); if (fd_ready_fd >= 0) { char c = 'R'; (void)write(fd_ready_fd, &c, 1); }
}
FD_STARTUP_ATTR static void fd_constructor(void) { fd_startup(); }

int FD_NI fd_rpc_emit(const struct fd_rpc_event *input) {
  if (!input || !fd_map || !fd_rpc_map || atomic_load_explicit(&fd_disabled, memory_order_relaxed) ||
      atomic_load_explicit(&fd_crashing, memory_order_acquire)) return input ? 0 : -1;
  if (!fd_rpc_direction_valid(input->direction)) return -1;
  if (fd_tls.in_runtime) return 0;
  fd_tls.in_runtime = 1;
  if (!fd_tls.registered && fd_register_thread() != 0) { fd_tls.in_runtime = 0; return 0; }
  uint64_t sequence = atomic_fetch_add_explicit(&fd_rpc_sequence, 1, memory_order_relaxed);
  uint32_t capacity = fd_rpc_map->event_capacity;
  struct fd_rpc_event *events = (struct fd_rpc_event *)((unsigned char *)fd_rpc_map + fd_rpc_map->events_offset);
  struct fd_rpc_event *out = &events[sequence % capacity];
  __atomic_store_n(&out->publication, 0, __ATOMIC_RELEASE);
  out->sequence = sequence;
  out->rpc_id = input->rpc_id;
  out->trace_id_hi = input->trace_id_hi;
  out->trace_id_lo = input->trace_id_lo;
  out->method_id = input->method_id;
  out->start_monotonic_ns = input->start_monotonic_ns;
  out->end_monotonic_ns = input->end_monotonic_ns;
  out->tid = input->tid ? input->tid : fd_tid();
  out->process_generation = input->process_generation ? input->process_generation : fd_rpc_map->process_generation;
  out->thread_generation = input->thread_generation ? input->thread_generation : fd_tls.generation;
  out->direction = input->direction;
  out->status = input->status;
  out->flags = input->flags;
  if (sequence >= capacity) {
    out->flags |= FD_RPC_EVENT_LOSS;
    __atomic_fetch_add(&fd_rpc_map->dropped_count, 1, __ATOMIC_RELAXED);
    __atomic_fetch_or(&fd_rpc_map->flags, FD_RPC_SIDECAR_FLAG_LOSS, __ATOMIC_RELEASE);
    fd_publish_status(FD_STATUS_EVENT_OVERFLOW);
  }
  /* reserved is the optional numeric attempt field in the v0.9 contract. */
  out->reserved = input->reserved; out->reserved2 = 0;
  __atomic_store_n(&out->publication, 1, __ATOMIC_RELEASE);
  __atomic_fetch_add(&fd_rpc_map->event_count, 1, __ATOMIC_RELAXED);
  fd_tls.in_runtime = 0;
  return 1;
}

int FD_NI fd_rpc_begin(uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
                      uint64_t method_id, uint32_t direction, uint64_t start_monotonic_ns) {
  return fd_rpc_begin_attempt(rpc_id, trace_id_hi, trace_id_lo, method_id,
                              direction, 0, start_monotonic_ns);
}

int FD_NI fd_rpc_begin_attempt(uint64_t rpc_id, uint64_t trace_id_hi,
                               uint64_t trace_id_lo, uint64_t method_id,
                               uint32_t direction, uint32_t attempt,
                               uint64_t start_monotonic_ns) {
  struct fd_rpc_event event;
  memset(&event, 0, sizeof(event));
  event.rpc_id = rpc_id; event.trace_id_hi = trace_id_hi; event.trace_id_lo = trace_id_lo;
  event.method_id = method_id; event.direction = direction; event.start_monotonic_ns = start_monotonic_ns;
  event.reserved = attempt;
  event.flags = FD_RPC_EVENT_START;
  return fd_rpc_emit(&event);
}

int FD_NI fd_rpc_end(uint64_t rpc_id, uint64_t trace_id_hi, uint64_t trace_id_lo,
                    uint64_t method_id, uint32_t direction, uint32_t status,
                    uint64_t end_monotonic_ns, uint32_t flags) {
  return fd_rpc_end_attempt(rpc_id, trace_id_hi, trace_id_lo, method_id,
                            direction, 0, status, end_monotonic_ns, flags);
}

int FD_NI fd_rpc_end_attempt(uint64_t rpc_id, uint64_t trace_id_hi,
                             uint64_t trace_id_lo, uint64_t method_id,
                             uint32_t direction, uint32_t attempt,
                             uint32_t status, uint64_t end_monotonic_ns,
                             uint32_t flags) {
  struct fd_rpc_event event;
  memset(&event, 0, sizeof(event));
  event.rpc_id = rpc_id; event.trace_id_hi = trace_id_hi; event.trace_id_lo = trace_id_lo;
  event.method_id = method_id; event.direction = direction; event.status = status;
  event.reserved = attempt;
  event.end_monotonic_ns = end_monotonic_ns; event.flags = flags | FD_RPC_EVENT_END;
  return fd_rpc_emit(&event);
}
