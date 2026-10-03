# Security policy

## Supported versions

Security fixes target the latest released version and the default branch. Older releases may not receive fixes.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through a GitHub Security Advisory for this repository. Do not open a public issue for an exploitable bug or attach real crash artifacts containing sensitive data.

Include the affected version or revision, reproduction steps using synthetic data where possible, the impact, and a suggested mitigation if known. Redact credentials, personal data, proprietary source, and host-specific paths.

The project will acknowledge a report when it is received, assess its severity, and coordinate disclosure after a fix or mitigation is available. Do not test against systems or data you do not own or have permission to use.

## Scope notes

The v0.1.0 tool is a local diagnostic collector. It does not provide authentication, remote execution, tenant isolation, or a guarantee that captured source and fault data are safe to publish. Treat bundles and artifacts as sensitive build and debugging data.
