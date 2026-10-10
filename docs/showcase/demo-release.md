This is a **development demo snapshot**, not stable v1.2 or v1.3 acceptance.

Try the recorded reports without installing anything:
https://lsh235.github.io/FalutDebugMCP/

On Linux x86_64 with a local Docker Engine and Compose:

~~~~sh
git clone https://github.com/lsh235/FalutDebugMCP.git
cd FalutDebugMCP
./scripts/try-demo.sh
~~~~

The script verifies SHA256SUMS, loads the prebuilt image, runs eight independent
shopping services through success, payment SIGILL and inventory timeout, collects
native evidence, removes its fixture containers, and serves the resulting reports.
The analyzer uses the local Docker socket and host networking for this local lab.
No host Python, Clang or CMake installation is needed.

The shopping app is Python with an instrumented C++ boundary. These are native
boundary events, not Python stacks. The intentional crash remains incomplete.
Image publication is gated by the actual newcomer script, not a build-only check.

The tar.gz file is a Docker image archive, to be loaded with docker load.
Its attached checksum records download integrity; the release target identifies
the source revision. This snapshot does not provide Kubernetes or multi-host
validation.
