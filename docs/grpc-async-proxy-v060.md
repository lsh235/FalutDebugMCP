# v0.6.0 gRPC asynchronous proxy semantic fixture

The v0.6 fixture extends the asynchronous gRPC proxy example with a bounded,
numeric semantic RPC trace. It remains a test fixture and does not install a
gRPC interceptor.

## Implemented

- `Echo.Forward` is a unary RPC exercised by three processes: client, proxy,
  and upstream server. The generated protobuf request carries numeric
  `rpc_id`, `trace_id_hi`, and `trace_id_lo` fields. The proxy forwards those
  fields to the upstream request.
- Application-owned boundaries call `fd_rpc_begin` and `fd_rpc_end` from
  `trace.cc`. Events contain the numeric fixture method ID, inbound or outbound
  direction, the propagated RPC and trace IDs, monotonic timestamps, gRPC
  status codes, and end/incomplete flags. Method strings, metadata, request or
  response payloads, and credentials are not recorded.
- Both servers use CompletionQueues. `--workers N` starts N CompletionQueue
  workers per server, and `--max-calls N` provides bounded graceful shutdown.
- `--deadline-ms N` applies an outbound `ClientContext` deadline. The upstream
  `--response-delay-ms N` option delays the application response before
  `Finish`, allowing the deadline path to be exercised. The semantic event
  records contain the resulting status and timestamps; the fixture does not
  emit a dedicated `deadline_ns` field.
- `--fault-after-response` preserves the existing real SIGSEGV path after the
  downstream response completion. The sidecar may therefore contain an
  incomplete terminal event when the process is interrupted.

The independent semantic gate validates committed events, numeric IDs,
inbound/outbound begin/end pairing, sequence ordering, loss/incomplete
handling, and the absence of sensitive fields. A representative run is:

```sh
cmake --build build --target fd_grpc_async_proxy -j2
python3 test/grpc_proxy_test.py --build-dir build --output /tmp/fd-grpc-v060
python3 test/grpc_semantic_validation.py \
  --artifact /tmp/fd-grpc-v060/artifacts/fault-<pid>.fault \
  --binary build/test/fd_grpc_async_proxy \
  --grpc-report /tmp/fd-grpc-v060/report.json \
  --output /tmp/fd-grpc-v060/semantic
```

## Explicit limits

- Streaming RPC is `NOT RUN`: the proto and fixture expose only unary
  `Echo.Forward`, and no streaming event sequence has been independently
  validated.
- Retry or an unavailable-retry scenario is `NOT RUN`: the fixture has no
  `--retry` option and does not emit retry or attempt fields. The semantic gate
  reports `retry_unavailable` as `NOT RUN`.
- Deadline and CompletionQueue worker controls are implemented as fixture
  options, but their dedicated capability checks remain `NOT RUN` until an
  independent invocation contract exercises those paths. Their presence in
  `--help` is not treated as runtime evidence.
- The fixture calls the numeric runtime API at application boundaries; it does
  not provide a gRPC client/server interceptor or automatic library-wide
  instrumentation. Shared RPC or trace IDs do not establish a global causal
  order. Cross-process relations require explicit unique endpoint evidence and
  remain unresolved when that evidence is absent or ambiguous.

The v0.6 artifact and incident-report readers remain backward compatible with
ABI v1 artifacts that have no semantic sidecar. Such artifacts retain their
ordinary function evidence and report the semantic RPC stream as unresolved.
