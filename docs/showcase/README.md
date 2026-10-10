# Public demo and reproducible local fixture

The public site is https://lsh235.github.io/FalutDebugMCP/.
It contains **recorded synthetic executions**, not a live monitoring backend.
Reports, screenshots and the 42-second silent walkthrough are actual UI outputs.

The three shopping examples come from the hosted N=8 run at revision
8e47cfb6415bd845682c7b854e2a5ee9eda925df:
https://github.com/lsh235/FalutDebugMCP/actions/runs/38070068563.
The original captures and immutable source bundle are included in the evidence
download. English UI labels do not translate captured evidence text.
The separate native C example is a fresh SIGSEGV run of the provenance-enabled
fd_signals fixture from build-v13-p0-core-final. Its incomplete flag is retained.

## Rebuild

Download the hosted shopping artifact and supply its shop-ci-n8 directory.
For the native C sample, capture fd_signals 11 and create a bundle from its
matching build snapshot and binary. Then:

~~~~sh
.venv/bin/python scripts/build-showcase.py \
  --lab build-v13-p0-hosted-shop-final/shopping-fault-evidence/shop-ci-n8 \
  --output build/new-showcase \
  --revision 8e47cfb6415bd845682c7b854e2a5ee9eda925df \
  --run-url https://github.com/lsh235/FalutDebugMCP/actions/runs/38070068563 \
  --native-capture build/showcase-c-capture/fault-674932.fault \
  --native-bundle build/showcase-c-bundle
python3 scripts/build-showcase.py --verify-only --output site
~~~~

Use the actual filename produced by your native capture. A new output directory
is required; the builder does not overwrite an existing site. The manifest
records input provenance and SHA-256 of the packaged files. Checksums provide
integrity, not proof of authorship or lossless capture.

## Local newcomer path

After cloning, run:

~~~~sh
./scripts/try-demo.sh
~~~~

Requires Linux x86_64, Bash, curl, and a local Docker Engine with Compose at
the default Unix socket. No host Python or compiler is needed. The script
downloads the development demo image archive from GitHub Releases, verifies
its checksum and runs the analyzer inside that image.

It mounts the repository read-only, a new output parent read-write, the local
Docker socket, Docker CLI and Compose plugin. Host networking lets the analyzer
reach the gateway's localhost port. It creates and removes only its own randomly
named fixture projects; the report server runs until Ctrl+C.

The image is distributed as a public, login-free release download. GHCR package
visibility requires additional account configuration, so GHCR is not required
for this working path.

Environment overrides: FAULTDEBUG_DEMO_IMAGE, FAULTDEBUG_DEMO_OUTPUT (new absolute
path), FAULTDEBUG_DEMO_PORT, FAULTDEBUG_REPORT_PORT. Use --no-serve to generate
and validate reports without starting the server. Existing outputs are rejected.

## Contribution and feedback

Small tasks are tracked in GitHub Issues with good first issue/help wanted labels.
Share installation failures with OS, Docker versions, the failing step and
sanitized logs. External social posts and Trendshift submissions have not been
sent.
