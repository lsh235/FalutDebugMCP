# Semantic RPC analysis contract

The original ABI v1 event ring records function addresses and call sites. It
does not turn a function name, a shared trace ID, or a parent PID into an RPC
observation. The optional v0.4 semantic sidecar is decoded only when the
artifact contains an explicit versioned stream.

The Python reader accepts the sidecar decoder's compact JSON shape:

```json
{
  "semantic_rpc_schema": 1,
  "rpc_events": [
    {
      "rpc_id": "opaque-or-numeric-id",
      "phase": "begin",
      "monotonic_ns": 123,
      "pid": 42,
      "method_id": 17,
      "status": 0
    }
  ]
}
```

`semantic_rpc_events` is accepted as an equivalent field, and the reader also
accepts the versioned `rpc_trace: {"schema": 1, "events": [...]}` form for
forward-compatible artifact writers. Event phases are limited to `begin`,
`send`, `receive`/`recv`, `status`, `end`, and `cancel`. The reader keeps the
numeric method ID and numeric or opaque trace identifiers; it rejects method
strings, metadata, credentials, request/response payloads, and header fields.
The runtime contract never supplies those sensitive values.

Every result has three separate evidence classes:

* `observed` contains only committed semantic events or explicit matching IPC
  endpoint pairs.
* `static_candidates` contains caller-supplied/static possibilities and is
  never merged into observed output.
* `unresolved` records an absent stream, non-unique endpoint pair, overflow,
  malformed evidence, or a provenance/version limitation.

An absent stream is an unresolved v1 result, preserving backward compatibility.
An unsupported schema, ABI mismatch, or conflicting Build ID is rejected with
an explicit error. A process relation is observed only when the RPC ID or IPC
message/channel pair has unique endpoint evidence and distinct process IDs;
shared trace IDs and parent PIDs alone do not establish causality.

The read-only MCP facade exposes:

* `get_rpc_trace(name, page)` for one artifact's semantic RPC stream;
* `get_process_relations(names, page)` for explicit cross-process IPC/RPC
  endpoint joins; and
* `get_evidence_summary(name)` for bounded counts and unresolved limits.

All tools retain 200-row pagination and use the existing artifact-root
allowlist. The existing `open_fault`, `get_thread_trace`, and static relation
tools retain their previous behavior.
