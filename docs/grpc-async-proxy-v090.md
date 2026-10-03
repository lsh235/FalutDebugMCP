# v0.9 gRPC semantic fixture

The optional fixture keeps instrumentation at application-owned boundaries.
It does not install a gRPC interceptor and records only numeric RPC fields:
`rpc_id`, the two trace ID words, method ID, attempt, direction, phase,
status, timestamps, and incomplete/loss markers. Payloads, metadata, and
credentials are excluded.

The public `faultdebug/rpc_scope.hpp` helper provides a bounded C++ RAII span;
it is a no-op when the optional sidecar is absent. Existing `fd_rpc_begin` and
`fd_rpc_end` remain unchanged. Attempt-aware callers may use the added
`fd_rpc_begin_attempt` and `fd_rpc_end_attempt` functions. Attempt is stored in
the previously reserved numeric event word, so ABI v1 readers remain valid.

The gRPC fixture exposes deterministic options:

- `--mode=upstream --stream-count=3` with client `--stream` exercises a real
  server-streaming sequence and emits a numeric stream span.
- `--deadline-ms=10` with delayed upstream response exercises cancellation and
  records `DEADLINE_EXCEEDED`.
- `--retry=2` retries `UNAVAILABLE` attempts. The final attempt is numbered 3;
  the inbound boundary remains one begin/end pair.
- `--workers=2` runs multiple CompletionQueue workers in every scenario.
- Client `--json-output` prints only scenario/status/count fields.

The independent scenario gate is:

```sh
python3 test/grpc_v09_scenarios.py \
  --binary build/test/fd_grpc_async_proxy \
  --output /tmp/faultdebug-grpc-v090
```

Its report is a local fixture check. It does not claim production interceptor
coverage, remote delivery, or global cross-process ordering.
