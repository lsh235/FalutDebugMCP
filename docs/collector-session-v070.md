# v0.7 local session and collector contract

v0.7 adds a launcher and local collector contract around the existing ABI v1
mapping. The shared-memory layout is unchanged. A launch receives or creates a
bounded ASCII `session_id`; every target gets a fresh `process_id` unless a
supervisor supplies one. The process identity also carries
`process_generation`, optional `parent_process_id`, and an optional bounded
`role`.

The target receives these values through:

* `FAULTDEBUG_SESSION_ID`
* `FAULTDEBUG_PROCESS_ID`
* `FAULTDEBUG_PROCESS_GENERATION`
* `FAULTDEBUG_PARENT_PROCESS_ID`
* `FAULTDEBUG_PROCESS_ROLE`

Completed reports expose `session: {schema: 1, session_id}` and
`process.identity`, including the target PID and launcher parent PID. Existing
artifacts without this envelope remain readable. Legacy `context.trace_id` and
`context.correlation_id` remain compatibility grouping inputs; they do not prove
causal order.

`faultdebug.collector.register_process()` writes a mode-0600 registration
manifest atomically under the caller's registry directory. It contains session
and process identity, PID, registration time, and artifact directory. File
descriptors are deliberately not serialized because they are process-local;
the registering launcher retains them and may call `collect_registered()`.
The manifest is removed after collection. This is a local registration path,
not remote delivery.

The collector waits with Linux `pidfd_open` when available, avoiding PID reuse;
the existing `/proc` polling fallback remains for older platforms. Collector
JSON is written with a same-directory temporary file, fsync, atomic rename, and
directory fsync.

FDAR artifact writes use the same-directory temporary file and fsync before an
exclusive hard-link publication. A writer crash can leave only a private
temporary file; `recover_artifacts()` removes old temporary files while
preserving valid final artifacts. No encryption, remote transport, payload
collection, or credential collection is implemented.
