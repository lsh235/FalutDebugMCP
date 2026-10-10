# A checkout times out while talking to inventory

[Open the recorded report](https://lsh235.github.io/FaultDebugMCP/reports/inventory_timeout/report.html).

The checkout receives a timeout symptom and the gateway returns HTTP 504.
Select the checkout → inventory RPC to inspect caller status, observed receiver
begin/end and duration. These are independent observations: caller timeout does
not prove that the receiver stopped processing.

The application failure explanation is corroborated with matching native RPC
status. The report preserves unresolved participants and source evidence.
The fixture's delay setting alone is not treated as proof of the cause.

Compare with the [successful checkout](https://lsh235.github.io/FaultDebugMCP/reports/success/report.html).
Evidence: [download](https://lsh235.github.io/FaultDebugMCP/downloads/demo-evidence.zip).
