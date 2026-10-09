# N-process shopping fault laboratory

Implement a runnable test fixture, not a production payment service. Eight core
application processes (gateway, catalog, cart, checkout, inventory, payment,
shipping, notification) communicate over real HTTP in separate containers.
N > 8 adds risk workers, all called during checkout. Each container also has a
FaultDebug collector process; N counts application processes, not collectors.

Acceptance criteria:

1. Build the native instrumented boundary and Docker image; launch isolated
   Compose projects without changing other containers.
2. Successful checkout returns a completed order; replay of the same order ID
   does not reserve or charge twice. Concurrent independent checkouts work.
3. Exercise inventory shortage, payment decline, payment native crash, inventory
   deadline, and notification failure. Assert HTTP results, order state and
   explicit compensation for payment failure.
4. Every process produces a checksummed `.fault` artifact. Native RPC joins use
   session, process identity/generation, trace and RPC IDs, including equal PIDs
   in separate containers. Missing endpoints remain unresolved.
5. Document and interactive HTML show observed service edges, per-request calls,
   origin failures and propagated symptoms. Reasons come from application events
   joined to native RPC evidence, never the injection plan alone. A crash report
   resolves the actual trap instruction against a verified immutable bundle.
6. Inspect the storefront and fault report in a real browser. Record actual
   commands, counts and limitations. Clean up only the fixture's containers.

Implementation order: service fixture and topology generator; scoped RPC join;
multi-service report; unit/regression tests; real Docker scenarios and scale run;
browser verification; documentation and authorized commit/push.

Kubernetes is optional; Docker Compose is the executed deployment backend.
