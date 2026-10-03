# v0.7 session manifest

The session manifest is a read-only projection over a bounded list of local
artifacts. It does not create runtime events or infer causal order.

The optional declaration accepted by the analyzer is:

```json
{
  "session": {
    "schema": 1,
    "session_id": "deployment-42",
    "participant_id": "proxy",
    "expected_participants": ["client", "proxy", "upstream"]
  }
}
```

`session_id` and `participant_id` are also accepted from `context` for
producer compatibility. Existing `context.trace_id` and
`context.correlation_id` remain valid legacy identity fallbacks. A fallback is
labelled `legacy_context`; it is never upgraded to runtime causality.

The collector registration API emits the same schema version with
`session.session_id` and process identity fields
`process_id`, `process_generation`, `parent_process_id`, and optional `role`.
The analyzer uses `role` as the participant label when present, then
`process_id`; an artifact index plus PID is only a local fallback identity.

The manifest keeps these classes separate:

- `observed.rpc_events`: committed events decoded from artifacts;
- `derived.process_relations`: unique joins calculated from observed endpoint
  evidence;
- `static_candidates`: static or caller-supplied possibilities; and
- `unresolved`: absent identity, incomplete artifacts, ambiguous joins,
  mismatches, and missing expected participants.

The participant projection copies only existing process, target, collector,
and allowlisted context fields. An artifact index and optional caller-supplied
artifact reference identify each row; PIDs are not treated as globally unique.

CLI:

```bash
fault-debug session-manifest artifacts/*.fault
fault-debug process-participants artifacts/*.fault
```

MCP provides `get_session_manifest(names, page)` and
`get_process_participants(names, page)`. Both are read-only, limited to 1,000
artifacts and 200 participants per page. ABI v1/v0.4-v0.6 artifacts remain
readable; artifacts without an explicit session declaration use the legacy
context fallback or report an unresolved session identity.
