# v0.9 incident-centric evidence queries

v0.9 adds incident query projections over the v0.8 SQLite evidence store.
The base store schema remains v2 for compatibility; `incident`,
`incident_artifact`, and `source_reference` are additive tables created during
the next writable store open. A v0.8 database therefore remains readable by
the v0.8 artifact/session APIs, while v0.9 incident queries become available
after the additive tables are initialized.

Incident IDs are accepted only from artifact/agent declarations such as
`collector.incident_id`. A shared `session_id` never creates an incident or a
causal relation. Trigger and peer snapshot artifacts retain their declared
`evidence_class`, collector phase, partial status, and process identity.

Evidence classes in an incident slice remain separate:

- `observed`: semantic RPC records and resident-agent snapshots;
- `derived`: explicit process relations already supported by the analyzer;
- `static_candidates`: possible static explanations;
- `unresolved`: missing, partial, ambiguous, or unavailable evidence; and
- `hypotheses`: caller-supplied hypotheses.

CLI:

```bash
fault-debug evidence-incidents --db out/evidence.sqlite3
fault-debug evidence-incident --db out/evidence.sqlite3 --incident-id INCIDENT
fault-debug evidence-unresolved --db out/evidence.sqlite3 --incident-id INCIDENT
fault-debug evidence-sources --db out/evidence.sqlite3 \
  --incident-id INCIDENT --bundle build/bundle --function-id FUNCTION_ID
```

MCP exposes read-only `list_incidents`, `get_incident_slice`,
`get_unresolved`, and `get_source_evidence`. Results use deterministic
incident/artifact ordering, bounded 200-row pages, and structured error
objects for query failures. Incident slices cap event expansion at 1,000
observed RPC records; `event_total` counts observed RPC records only, while
peer snapshots and unresolved/static/hypothesis classes remain separate.
Truncation is reported as unresolved evidence.

`get_source_evidence` verifies the supplied immutable bundle, resolves the
captured function index or declared file/line reference, and returns exact
bundle-relative file, line range, and SHA-256 citations. It does not return a
source citation when the bundle, index, file, line, or hash cannot be
verified. Remote source lookup, automatic source inference, and causal
relations derived from session membership are not implemented.
