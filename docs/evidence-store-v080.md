# v0.8 SQLite evidence store

v0.8 adds a local SQLite schema-v2 projection over completed artifacts. The
store keeps `artifact`, `process`, `evidence`, `relation`, `provenance`, and
`quarantine` records. Evidence classes remain separate:

- `observed`: committed semantic RPC events and producer-supplied peer
  snapshots;
- `derived`: explicit process relations already supported by the analyzer;
- `static_candidates`: possible static or caller-supplied explanations;
- `unresolved`: missing, incomplete, ambiguous, or mismatched evidence; and
- `hypotheses`: caller-supplied hypotheses that are not observations.

Ingest first verifies an FDAR checksum. Optional expected values can be passed
for `build_id`, `binary_sha256`, `source_sha256`, `index_sha256`, `session_id`,
`process_id`, `process_generation`, and the artifact SHA-256. A row is marked
`verified` only when the FDAR checksum and all four supplied build/source/index
provenance values match. A readable artifact without those trust inputs is
stored as `unresolved`. Decode, identity, checksum, and provenance mismatches
are copied into the store's `quarantine/` directory and do not enter valid
artifact queries.

```bash
fault-debug evidence-ingest --db out/evidence.sqlite3 \
  --expected-provenance expected.json artifacts/*.fault
fault-debug evidence-reindex --db out/evidence.sqlite3 artifacts/
fault-debug evidence-sessions --db out/evidence.sqlite3 --trust-state verified
fault-debug evidence-session --db out/evidence.sqlite3 --session-id deployment-42
fault-debug evidence-provenance --db out/evidence.sqlite3
```

The database reopens safely and reindexing the same path replaces its previous
projection. Opening an older v0.6 `ArtifactIndex` database migrates readable
payload rows while retaining the legacy table. Session and artifact ordering
uses explicit session ID, monotonic start time, and stable row IDs; page size
is bounded to 1,000.

MCP exposes read-only `list_sessions`, `get_session`, and `get_provenance`.
They read an allowlisted `evidence.sqlite3` beneath the MCP root and never
ingest or mutate artifacts. Shared session IDs identify a grouping only; they
do not create causal edges. Runtime peer snapshots retain supplied collector
phase and partial status inside observed payloads. Remote storage, encryption,
resident multi-daemon snapshots, and automatic trust from self-declared
provenance are not implemented.
