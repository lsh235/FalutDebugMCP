# Incident report

The v0.6 incident report is a read-only projection of fields already present
in one or more local artifacts. Generate it with:

```bash
fault-debug incident-report artifacts/fault-1.fault artifacts/fault-2.fault
```

The MCP equivalent is `get_incident_report(names, page)`. The result keeps
the evidence classes separate:

* `observed.rpc_events` contains committed semantic RPC events;
* `observed.process_relations` contains explicit unique IPC/RPC endpoint joins;
* `static_candidates` contains static or caller-supplied possibilities; and
* `unresolved` contains absent streams, gaps, overflow, incomplete records,
  malformed data, and ambiguous endpoint joins.

The `fields` object copies explicit event `status`, `deadline_ns`,
`retry_count`/`attempt`, and `stream`/`streaming` values when supplied. The
report does not derive deadlines from timestamps, retries from repeated IDs,
stream type from phases, or status from process exit codes. Artifact target and
collector status are retained under `artifacts` with their original field
names. ABI v1 artifacts without semantic RPC events remain readable and show
an unresolved semantic stream.

The report is local and bounded by the supplied artifact list. It does not
send, encrypt, or redact artifacts, and it does not claim production incident
management or remote correlation.
