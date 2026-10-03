# v0.8 resident local agent

The optional resident agent provides a local, bounded peer snapshot path. It
is disabled unless a launcher is given `--agent-socket`; the existing direct
collector path remains unchanged when that option is omitted.

Start it with a socket below the private spool directory:

```text
faultdebug-agent --socket /var/lib/faultdebug/session/agent.sock \
  --spool-root /var/lib/faultdebug/session
faultdebug run --agent-socket /var/lib/faultdebug/session/agent.sock ...
```

The agent accepts only Unix-domain clients. Registration sends one shared
memory FD using `SCM_RIGHTS` and includes `session.schema`, `session_id`, and
the process identity (`process_id`, `process_generation`, `pid`, and
`parent_pid`). Linux peer credentials and `/proc/<pid>/status` parent identity
are checked before the FD is retained. The socket and status/artifact files
are mode `0600`; the spool and staging directories are mode `0700`, and the
socket/status paths must remain below the configured spool root.

After a registered process reports a signal, the agent snapshots the trigger
and live peers in the same session. Every resulting artifact has an identity
based name containing `process_id`, generation, and incident ID. The artifact
envelope contains:

```json
{
  "session": {"schema": 1, "session_id": "..."},
  "process": {"identity": {"process_id": "...", "process_generation": 1}},
  "collector": {
    "status": "limited",
    "phase": "incident_snapshot",
    "incident_id": "...",
    "trigger_process_id": "...",
    "trigger_signal": 11,
    "partial": true
  }
}
```

The trigger record is marked `evidence_class: observed` and carries the
signal. A live peer record is marked `evidence_class: incident_snapshot` and
has `target.signal: null`; it is a bounded view of the peer's current shared
memory, not proof that the peer faulted. Registration, unavailable peers, disk
errors, and agent restart are surfaced in the agent status JSON and request
responses. Payloads and credentials are never sent through this protocol.

This slice does not provide remote delivery, encryption, or a resident
multi-host coordinator. It also does not instrument gRPC internals; callers
must notify the agent at their application-owned fault boundary.
