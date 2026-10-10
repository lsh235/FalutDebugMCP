# A real C fixture produces SIGSEGV

[Open the native report](https://lsh235.github.io/FaultDebugMCP/reports/c-sigsegv/report.html).

A fresh run of the instrumented fd_signals fixture performs the signal-11 path.
The collector reports target returncode -11, signal 11, and two retained native
function events. The snapshot is stable, but trace.complete is false; the
report keeps that distinction.

The report verifies the captured binary Build ID against an immutable source
bundle before presenting the source location. Recorded function context and
static call candidates remain separate. It does not reconstruct missing frames.

Evidence: [capture and matching bundle](https://lsh235.github.io/FaultDebugMCP/downloads/c-sigsegv-evidence.zip).
The showcase manifest records the artifact SHA-256 and support scope.
