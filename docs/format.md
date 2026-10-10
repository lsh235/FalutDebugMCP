# faultDebug shared-memory format (ABI v1)

The runtime and post-exit collector exchange a versioned, fixed-width little-endian
mapping. Python must treat the mapping as a byte buffer and decode the offsets below;
it must not depend on host C struct packing. The launcher creates a `memfd`, sizes it
for `sizeof(struct fd_shared_memory)`, passes its descriptor in `FAULTDEBUG_SHM_FD`,
and passes a write end of a readiness pipe in `FAULTDEBUG_READY_FD`.

The runtime writes `FD_STATUS_READY` only after configuration, thread storage,
alternate stacks, signal handlers, and the loaded-module table have succeeded. A
single byte `R` is written to the readiness FD after that flag is published. A
configuration/module/signal conflict is a startup failure: the status flag is set,
the readiness byte is `E`, and the process remains instrumentable only when the
launcher elects to continue. The collector must report the failure and never call
the mapping production-ready.

## Fixed layout

All integers are unsigned or signed two's-complement values in little-endian order.
The fixed layout for the default bounds is:

| Region | Offset | Size | Count |
| --- | ---: | ---: | ---: |
| `fd_shared_header` | 0 | 80 | 1 |
| `fd_thread_ring` | 80 | 196,648 | 64 |
| `fd_module_record` | 12,585,552 | 328 | 256 |
| `fd_crash_record` | 12,669,520 | 64 | 2 |

The physical mapping uses the fixed maximum layout above. The header's
`threads_offset`, `modules_offset`, and `crashes_offset` are authoritative and its
capacity fields are logical bounds, so a smaller configured capacity never changes
record offsets. `total_size` bounds every read. The default thread ring size is
`40 + 4096 * 48 = 196,648` bytes (the value is computed from the C layout, not this
table). A producer always invalidates `publication` to zero before rewriting a slot,
writes all fields, then release-stores `publication = 1`. Readers discard records
with a zero marker or a changed generation. The Python decoder samples the
publication marker and event sequence on both sides of a private record copy; RPC
records use the same check and crash records also check their monotonic timestamp.
A live writer that changes a record during the copy causes it to be omitted and
listed in the report's additive `snapshot_consistency.unstable_records` field. The
report is then marked `complete=false`. This gives per-record consistency, not a
single atomic cut of all rows in a live process.

## Thread generation retention

Two additive `fd_thread_header.flags` bits define the generation contract without
changing ABI v1 sizes or offsets:

- `FD_THREAD_GENERATION_COUNT` (bit 0): `event_count` and event sequences refer to
  the current generation and restart at zero when a slot is reused.
- `FD_THREAD_HISTORY_RETIRED` (bit 1): a previous thread generation occupied this
  slot. Its historical events and TID are unavailable; `FD_STATUS_PARTIAL` remains
  set for older readers, so a stable snapshot does not imply complete history.

`dropped_count` remains cumulative within the slot across generations and counts
within-generation ring evictions. It must not be reset to hide an earlier overflow.
Retired history is a separate limitation, not an additional numeric drop total;
the number of retired events is unknown. Decoder `threads[].retention` documents
these scopes and `retired_generations`, with `retired_event_count=null`.
Legacy rows without bit 0 keep their original counters and have no inferred scope.

Registration reserves the TID sentinel while counters, generation and flags are
updated. Old event slots remain tagged with their previous generation and are
excluded. Event copies compare generation as well as publication and sequence to
reject a same-sequence replacement during a live read. Generation exhaustion at
`UINT32_MAX` discloses thread overflow/partial rather than wrapping to an old identity.
TID zero still denotes a released slot; no former TID is reconstructed. Native crash
records match the registered live TID and generation before thread teardown.

## Optional RPC semantic sidecar

ABI v1 remains valid without semantic events. A v0.4 launcher may reserve an
optional sidecar at the next 64-byte aligned offset after the v1 mapping
(`12669696` bytes for the default bounds). The sidecar starts with a 64-byte
`fd_rpc_sidecar_header` and a bounded ring of 96-byte `fd_rpc_event` records.
Its own magic/version and `total_size` delimit the extension; v1 readers ignore
the trailing bytes. New readers ignore an absent zero-filled sidecar and reject
an explicitly malformed one.

RPC records contain only numeric `rpc_id`, 128-bit trace ID words, an opaque
`method_id`, direction, status, start/end monotonic timestamps, process/thread
generation, and publication/loss flags. They never contain method strings,
metadata, request/response payloads, or credentials. A release publication
marker is at the end of each record. Ring eviction increments
`dropped_count`, sets the sidecar loss flag, and marks the retained record with
`FD_RPC_EVENT_LOSS`; a crash sets the sidecar incomplete flag. `START` and
`END` records are correlated by `rpc_id` and trace ID, but the runtime does not
install a gRPC interceptor or infer missing terminal events. Applications call
the numeric-only `fd_rpc_emit`, `fd_rpc_begin`, and `fd_rpc_end` APIs from
their interceptor boundary when a sidecar was provisioned.

`fd_event.sequence` is monotonic for one thread generation. `function_ptr` is the
instrumented function address and `callsite_ptr` is the compiler call-site address
when supplied by the instrumentation ABI. Event types are `ENTER`, `EXIT`, `DROP`,
`EVICT`, and `OVERFLOW`. Drop/eviction records are ordinary events so loss is visible.

`fd_crash_record` is reserved before startup. The first valid crash record wins;
nested faults set `FD_CRASH_NESTED` and do not overwrite the first record. Its validity
bits distinguish absent `siginfo_t` fields from zero values. The signal handler only
writes this record, sets `FD_STATUS_CRASHED|FD_STATUS_FROZEN`, and restores default
termination behavior. It never allocates, locks, symbolises, or resumes execution.

Each module has a 32-byte BuildID buffer, a byte length, and flags: bit 0 means the
identifier was longer than the buffer and was explicitly truncated; bit 1 means the
identifier was fully captured. Length zero with no flags means the loaded object had
no GNU BuildID note. Consumers must retain the flags when presenting provenance.

## Status flags

`READY`, `CRASHED`, `FROZEN`, `EVENT_OVERFLOW`, `THREAD_OVERFLOW`, `MODULE_OVERFLOW`,
`CONFIG_ERROR`, `SIGNAL_CONFLICT`, `FORK_CHILD`, and `PARTIAL` are bit flags. A reader
must preserve unknown bits for forward compatibility. `FROZEN` means event producers
must stop publishing after a crash; it does not mean the process terminated cleanly.
Event, thread, or module overflow makes the decoded report incomplete even when the
mapping is structurally valid. RPC sidecar loss/incomplete flags and records changed
during a live read also make the report incomplete.

## Collection deadlines

The post-exit collector uses the supplied timeout as one monotonic deadline for
both the readiness byte and target-exit wait. Missing readiness returns
`phase=ready_timeout`; a target that remains alive after readiness returns
`phase=wait_timeout`. The resident Unix-socket agent closes an accepted request
connection that sends no bytes within its 250 ms receive deadline, then returns
to accepting requests or observing shutdown.

## Environment contract

* `FAULTDEBUG_SHM_FD`: decimal open descriptor for the mapping; inherited by the
  instrumented process and closed by the launcher after process exit.
* `FAULTDEBUG_READY_FD`: decimal write descriptor for one readiness byte (`R` or `E`).
* `FAULTDEBUG_CONFIG`: optional ASCII `key=value,key=value` bounds/configuration.
* `FAULTDEBUG_DISABLE`: if set to a non-empty value, instrumentation is disabled.

The runtime does not use the file wrapper or symbolization in the hot path. The
post-exit collector owns decoding and finalization of the mapping/file artifact.
