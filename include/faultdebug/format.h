#ifndef FAULTDEBUG_FORMAT_H
#define FAULTDEBUG_FORMAT_H

/* Version 1 of the little-endian, fixed-width shared-memory ABI. */
#include <stdint.h>
#include <stddef.h>

#define FD_ABI_MAGIC UINT32_C(0x31444646) /* "FFD1" in little endian */
#define FD_ABI_VERSION UINT16_C(1)
#define FD_MAX_THREADS 64u
#define FD_MAX_EVENTS_PER_THREAD 4096u
#define FD_MAX_MODULES 256u
#define FD_MAX_CRASH_RECORDS 2u

/* Optional semantic RPC sidecar.  The v1 mapping ends at
 * sizeof(struct fd_shared_memory); a producer may append this section at the
 * canonical aligned offset without changing any v1 offsets or version. */
#define FD_RPC_SIDECAR_ALIGNMENT 64u
#define FD_RPC_SIDECAR_VERSION UINT16_C(1)
#define FD_RPC_MAX_EVENTS 1024u
#define FD_RPC_MAGIC UINT32_C(0x31515052) /* "RPQ1" in little endian */
#define FD_RPC_SIDECAR_FLAG_LOSS UINT32_C(1) /* at least one slot was evicted */
#define FD_RPC_SIDECAR_FLAG_INCOMPLETE UINT32_C(2) /* process ended before all RPCs completed */

/* Environment variables owned by the launcher/runtime contract. */
#define FD_ENV_SHM_FD "FAULTDEBUG_SHM_FD"
#define FD_ENV_READY_FD "FAULTDEBUG_READY_FD"
#define FD_ENV_CONFIG "FAULTDEBUG_CONFIG"
#define FD_ENV_DISABLE "FAULTDEBUG_DISABLE"

enum fd_status_flags {
    FD_STATUS_READY             = UINT32_C(1) << 0,
    FD_STATUS_CRASHED           = UINT32_C(1) << 1,
    FD_STATUS_FROZEN            = UINT32_C(1) << 2,
    FD_STATUS_EVENT_OVERFLOW    = UINT32_C(1) << 3,
    FD_STATUS_THREAD_OVERFLOW   = UINT32_C(1) << 4,
    FD_STATUS_MODULE_OVERFLOW   = UINT32_C(1) << 5,
    FD_STATUS_CONFIG_ERROR      = UINT32_C(1) << 6,
    FD_STATUS_SIGNAL_CONFLICT   = UINT32_C(1) << 7,
    FD_STATUS_FORK_CHILD        = UINT32_C(1) << 8,
    FD_STATUS_PARTIAL            = UINT32_C(1) << 9
};

enum fd_event_type {
    FD_EVENT_ENTER = 1,
    FD_EVENT_EXIT = 2,
    FD_EVENT_DROP = 3,
    FD_EVENT_EVICT = 4,
    FD_EVENT_OVERFLOW = 5
};

/* Additive ABI v1 thread flags; no layout/offset changes.  Old readers still
 * see FD_STATUS_PARTIAL when a previous generation has been retired. */
enum fd_thread_flags {
    FD_THREAD_GENERATION_COUNT = UINT32_C(1) << 0,
    FD_THREAD_HISTORY_RETIRED = UINT32_C(1) << 1
};

enum fd_rpc_direction {
    FD_RPC_DIRECTION_INBOUND = 1,
    FD_RPC_DIRECTION_OUTBOUND = 2
};

enum fd_rpc_event_flags {
    FD_RPC_EVENT_START = UINT32_C(1) << 0,
    FD_RPC_EVENT_END = UINT32_C(1) << 1,
    FD_RPC_EVENT_INCOMPLETE = UINT32_C(1) << 2,
    FD_RPC_EVENT_LOSS = UINT32_C(1) << 3
};

enum fd_crash_signal_flags {
    FD_CRASH_SIGNAL_VALID = 1u << 0,
    FD_CRASH_SI_CODE_VALID = 1u << 1,
    FD_CRASH_FAULT_ADDR_VALID = 1u << 2,
    FD_CRASH_PC_VALID = 1u << 3,
    FD_CRASH_NESTED = 1u << 4
};

/* All offsets and sizes below are bytes. Atomics are represented as uint32/uint64
 * storage; producers use C11 atomics and readers use acquire loads. */
struct fd_event {
    uint64_t sequence;
    uint64_t monotonic_ns;
    uint64_t function_ptr;
    uint64_t callsite_ptr;
    uint32_t type;
    uint32_t generation;
    uint32_t publication; /* 0 while being rewritten, 1 when complete */
    uint32_t reserved;
};

struct fd_thread_header {
    uint64_t tid;
    uint32_t generation;
    uint32_t flags;
    uint64_t event_count; /* current generation if FD_THREAD_GENERATION_COUNT */
    uint64_t dropped_count; /* cumulative within-generation evictions for slot */
    uint32_t event_capacity;
    uint32_t reserved;
};

struct fd_thread_ring {
    struct fd_thread_header header;
    struct fd_event events[FD_MAX_EVENTS_PER_THREAD];
};

struct fd_crash_record {
    uint32_t publication;
    uint32_t flags;
    uint32_t signal_number;
    int32_t si_code;
    uint64_t fault_address;
    uint64_t program_counter;
    uint64_t tid;
    uint64_t monotonic_ns;
    uint64_t thread_generation;
    uint64_t reserved;
};

struct fd_module_record {
    uint32_t publication;
    uint32_t path_length;
    uint64_t load_bias;
    uint64_t text_start;
    uint64_t text_end;
    uint32_t build_id_length;
    uint32_t build_id_flags;
    uint8_t build_id[32];
    char path[256];
};

struct fd_shared_header {
    uint32_t magic;
    uint16_t abi_version;
    uint16_t header_size;
    uint32_t total_size;
    uint32_t status_flags;
    uint32_t event_capacity;
    uint32_t thread_capacity;
    uint32_t module_capacity;
    uint32_t crash_capacity;
    uint64_t creator_pid;
    uint64_t start_monotonic_ns;
    uint64_t ready_monotonic_ns;
    uint64_t crash_monotonic_ns;
    uint32_t threads_offset;
    uint32_t modules_offset;
    uint32_t crashes_offset;
    uint32_t reserved;
};

struct fd_shared_memory {
    struct fd_shared_header header;
    struct fd_thread_ring threads[FD_MAX_THREADS];
    struct fd_module_record modules[FD_MAX_MODULES];
    struct fd_crash_record crashes[FD_MAX_CRASH_RECORDS];
};

/* This header is deliberately outside fd_shared_memory so existing ABI v1
 * launchers and readers continue to use the original fixed layout. */
struct fd_rpc_sidecar_header {
    uint32_t magic;
    uint16_t version;
    uint16_t header_size;
    uint32_t total_size;
    uint32_t event_capacity;
    uint64_t event_count;
    uint64_t dropped_count;
    uint32_t process_generation;
    uint32_t flags;
    uint32_t events_offset;
    uint32_t reserved;
    uint64_t reserved2;
    uint64_t reserved3;
};

/* Numeric-only by design: callers provide stable IDs, never method names,
 * metadata, request/response payloads, or credentials. */
struct fd_rpc_event {
    uint64_t sequence;
    uint64_t rpc_id;
    uint64_t trace_id_hi;
    uint64_t trace_id_lo;
    uint64_t method_id;
    uint64_t start_monotonic_ns;
    uint64_t end_monotonic_ns;
    uint64_t tid;
    uint32_t process_generation;
    uint32_t thread_generation;
    uint32_t direction;
    uint32_t status;
    uint32_t flags;
    uint32_t publication;
    uint32_t reserved;
    uint32_t reserved2;
};

#define FD_RPC_SIDECAR_OFFSET \
    ((sizeof(struct fd_shared_memory) + (FD_RPC_SIDECAR_ALIGNMENT - 1u)) & \
     ~(size_t)(FD_RPC_SIDECAR_ALIGNMENT - 1u))

#define FD_OFFSET(type, member) offsetof(type, member)

#if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
_Static_assert(sizeof(struct fd_event) == 48, "fd_event ABI drift");
_Static_assert(sizeof(struct fd_thread_header) == 40, "fd_thread_header ABI drift");
_Static_assert(sizeof(struct fd_crash_record) == 64, "fd_crash_record ABI drift");
_Static_assert(sizeof(struct fd_module_record) == 328, "fd_module_record ABI drift");
_Static_assert(sizeof(struct fd_shared_header) == 80, "fd_shared_header ABI drift");
_Static_assert(offsetof(struct fd_shared_memory, threads) == 80, "fd_shared_memory offset drift");
_Static_assert(sizeof(struct fd_rpc_sidecar_header) == 64, "fd_rpc_sidecar_header ABI drift");
_Static_assert(sizeof(struct fd_rpc_event) == 96, "fd_rpc_event ABI drift");
_Static_assert(FD_RPC_SIDECAR_OFFSET % FD_RPC_SIDECAR_ALIGNMENT == 0, "RPC sidecar alignment drift");
#endif

#endif
