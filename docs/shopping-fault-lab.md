# N-process shopping fault laboratory

Run a real shopping workflow across separate Docker containers, inject
controlled faults, and inspect their observed propagation. The fixture uses
Python HTTP services plus an instrumented C++ boundary module. It publishes
numeric RPC events through the FaultDebug native runtime; Python call stacks
are not instrumented. Payments and products are synthetic.

## Build and run

Prerequisites: Linux/glibc, Docker Engine with Compose, and the project's
Python 3.12 environment. No Kubernetes cluster is required.

```sh
docker build -f test/shop/Dockerfile -t faultdebug-shop:dev .
.venv/bin/python test/shop/run.py --processes 8 --requests 4 --concurrency 2 \
  --output build/shop-run
# N=16: eight core services plus eight independently called risk workers
.venv/bin/python test/shop/run.py --processes 16 --requests 24 --concurrency 4 \
  --scenarios success payment_decline --output build/shop-scale
```

`--processes` accepts 8..32. N counts application processes. Each container also
runs a collector and an init process. The runner uses a random Compose project
name to isolate each session and removes only its own containers and network.
See Docker's [project isolation documentation](https://docs.docker.com/compose/how-tos/project-name/).
Gateway ports bind to `127.0.0.1`; peers use container-network DNS and HTTP.
Each application uses a fixed eight-thread HTTP worker pool, preserving native
thread-ring history instead of recycling a native slot for every request.
Collectors run as the host UID/GID so private captures remain readable by the
invoking user. Each container has CPU, memory and PID limits; no privileged
mode, Docker socket, host PID namespace or cluster permissions are needed.

The runner checks readiness, sends real concurrent orders, asserts HTTP and
business state, gracefully stops services, verifies every capture, and writes
reports. Existing output directories are rejected. `--port` changes the
gateway's default port 8860. `--build` builds the image before running.

## Services and injected failures

| Process | Responsibility |
|---|---|
| gateway | Storefront and request routing |
| catalog | Product and demo price |
| cart | Cart quantity; queries catalog |
| checkout | Order orchestration and replay protection |
| inventory | Stock reservation, deadline guard, release |
| payment | Synthetic authorization and idempotent charge |
| shipping | Idempotent shipment |
| notification | Demo confirmation delivery |
| risk-1 .. risk-(N-8) | Independent risk checks, each called before reservation |

The gateway calls cart, then checkout. Cart calls catalog. Checkout calls every
risk worker, inventory, payment, shipping and notification. Direct gateway to
catalog calls also occur when browsing products. Checkout uses an explicit
parent RPC ID for each child call; diagrams must not substitute an imagined
linear cart-to-checkout call for the actual gateway-to-checkout request.

| Scenario | Origin | Result and asserted state |
|---|---|---|
| `success` | None | 200, completed order; replay does not reserve/charge twice |
| `inventory_shortage` | Inventory stock budget override | 409, no order, reservation or charge |
| `payment_decline` | Payment authorization policy | 402, inventory reservation released, no charge |
| `inventory_timeout` | 900 ms inventory delay vs 300 ms caller timeout | 504; receiver checks deadline before stock mutation |
| `notification_failure` | Demo notification provider outage | 200 completed order; notification deferred; downstream 503 remains visible |
| `payment_crash` | Native authorization invariant trap | SIGILL in payment; caller/gateway 502; inventory released |

Failures are selected explicitly per request. There is no random seed or
post-hoc selection of failures to fit expected results. Crash tests use a fresh
session and a single request because the payment process actually exits.

## Reports and evidence

Each scenario directory contains `compose.json`, `run.json`, `containers.log`,
and one evidence directory per service. The top-level `summary.json` records
responses, state assertions, participant identities and the tested image digest.
`bundle/` is copied from that same image's immutable build snapshot.

```text
shop-run/
  index.html
  summary.json
  bundle/
  payment_crash/
    evidence/payment/{events.jsonl,fault-<pid>.fault}
    report/{report.html,report.md,report.json}
    report/fault-<index>/{report.html,report.md,report.json}
```

```sh
# Rebuild a report from saved evidence, without rerunning the workload
.venv/bin/fault-debug service-report build/shop-run/payment_crash/evidence \
  --bundle build/shop-run/bundle --output build/shop-report-copy
# Serve the report index
.venv/bin/python -m http.server 8870 --bind 127.0.0.1 --directory build/shop-run
```

Open `http://127.0.0.1:8870/index.html`. The report shows observed RPC endpoint
pairs, per-request calls, parent RPC IDs, caller durations/status, separate
receiver status/completion, origin failure explanations and immutable source
excerpts. Click a call or service to inspect its evidence. Risk workers are
grouped in the diagram; all individual process identities and calls remain
available. Native crashes link to the existing fault-flow report with the
actual instruction, Build ID and verified C++ source. Markdown is the full
document; JSON retains all evidence and unresolved items. HTML can be printed
to PDF for the selected request.

Native `.fault` checksums are verified before analysis. The report hashes the
same bytes it decodes, and logs are kept separate from native evidence.
Application explanations require matching session/process/generation, PID,
trace and RPC identifiers; failed business status is corroborated against the
native receiver end event. A payment trap explanation additionally requires a
crash on the same recorded native thread. Injection configuration is never an
input to the report. Without an observed explanation the reason stays unknown.
Source snippets come only from the verified bundle, not the current worktree.
Hashes identify captured inputs, not log authenticity or universal causality.
Native capture incompleteness and snapshot consistency gaps remain explicit,
even if the RPC sidecar itself contains valid complete calls.

Equal PIDs across containers are expected. RPC joins use explicit process
identity/generation, session, trace and RPC IDs; PIDs are retained as local
metadata. Legacy PID-only captures remain supported. Mismatched scopes, methods,
multiple endpoint candidates and mixed identity/PID-only pairs stay unresolved.

External browser/load-generator requests have no native counterpart, so their
gateway inbound spans remain unpaired. A crash leaves an incomplete receiver
span. Services not reached after an early failure have no RPC events. The
existing IPC analyzer reports absent IPC evidence separately; this HTTP test
does not invent IPC events. These gaps are reported, not silently discarded.

## Interactive laboratory

```sh
.venv/bin/python test/shop/manage.py up --processes 8 --output build/shop-live
# Open http://127.0.0.1:8860 and select a failure before placing an order
.venv/bin/python test/shop/manage.py stop --output build/shop-live
# stop collects artifacts and creates build/shop-live/report before removal
```

The storefront's report link opens the pre-generated report index on port 8870.
It does not claim that an interactive request has already been included in that
report. Stop the laboratory to generate the report for its current session.
After a native crash, stop and start a new laboratory directory to reset it.
Orders are in-memory and are reset on restart. Notifications have no external
provider, and `deferred` is an observed demo state, not a background delivery
queue. The test server uses Python's [HTTP server](https://docs.python.org/3.12/library/http.server.html)
and is intended for this local test fixture.

## Validation

See [the recorded validation](shopping-fault-lab.validation.md). Docker Compose
is the exercised backend. Kubernetes deployment and production payment/provider
integration are **NOT RUN**. No new release version is claimed.
