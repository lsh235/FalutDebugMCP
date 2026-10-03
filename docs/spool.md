# Local artifact spool

`faultdebug spool` provides a local handoff point for completed `.fault`
artifacts. It does not send data to a remote service and does not provide
encryption. Each source is checksum-verified before admission.

The spool requires explicit `--max-bytes` and `--max-files` limits at the API
boundary. The CLI defaults are 64 MiB and 1,000 valid artifacts. When a new
artifact would exceed either limit, the oldest valid spool files are removed
first. An individual artifact larger than `--max-bytes` is rejected.

Writes use a same-directory temporary file, `fsync`, atomic rename, and a
directory `fsync`. Startup removes only abandoned temporary files created by
this spool. A final file is accepted only if its FDAR checksum and length are
valid; malformed final files are reported by recovery and are left for manual
inspection.

`--redact-context-id VALUE` replaces an exact match in the top-level
`context.trace_id` or `context.correlation_id` field with `[REDACTED]` before
writing the spool copy. The implementation does not recursively inspect or
rewrite payload-shaped fields. Source artifacts are never modified.

Example:

```bash
faultdebug spool --root ./spool --max-bytes 67108864 --max-files 1000 \
  --redact-context-id incident-123 ./artifacts/fault-42.fault
```
