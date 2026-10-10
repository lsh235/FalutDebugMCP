# A failed checkout caused by a payment process SIGILL

[Open the recorded report](https://lsh235.github.io/FaultDebugMCP/reports/payment_crash/report.html).

The caller sees HTTP 502. The native RPC endpoints record checkout calling
payment; the payment receiver's end is missing. The payment capture contains a
SIGILL and a verified source location in test/shop/boundary.cc.
The source-backed native report is linked from the service report.

The fixture deliberately injects the crash. The assessment is based on matched
RPC identities and the actual native crash, not the injection configuration.
The missing receiver end and incomplete native capture remain visible.
The Python application stack is not captured.

Evidence: [download](https://lsh235.github.io/FaultDebugMCP/downloads/demo-evidence.zip)
and [manifest](https://lsh235.github.io/FaultDebugMCP/evidence.json).
