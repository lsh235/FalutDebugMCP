# Improve local-demo preflight diagnostics for unsupported Docker contexts

scripts/try-demo.sh currently supports Linux x86_64 and the local /var/run/docker.sock engine. Rootless/remote engines and Docker Desktop contexts are rejected.

Acceptance:
- On rejection, print the detected OS/architecture/context endpoint and the documented supported setup, without credentials or auth configuration.
- Document WSL2/Desktop as an unvalidated profile unless an actual execution is provided.
- Do not switch contexts, start/stop the daemon, or change unrelated containers.
- Validate rejection without launching fixture containers and keep the supported newcomer path working.

Scope: the preflight section and docs/showcase/README.md.
